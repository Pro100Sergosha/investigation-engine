"""Lambda entry points. `api` serves the Function URL; `ingest` indexes objects put into S3;
`schema` applies sql/schema.sql for the deploy's custom resource."""

import base64
import hmac
import json
import re
import tempfile
import time
import traceback
from collections import Counter
from dataclasses import asdict
from functools import cache
from pathlib import Path
from urllib.parse import unquote_plus

import boto3
import pg8000.native
from botocore.config import Config

from engine import agent, config, db, index, parsers, search

# The cluster's master user (IAM auth only, created by express configuration). Only `schema`
# connects as it: it owns the tables and creates the `app` role everything else uses.
SCHEMA_USER = "postgres"

# Regional endpoint and SigV4: with the global endpoint (s3.amazonaws.com) a recently created
# bucket answers the browser's preflight/PUT with a 307 redirect to the regional host, and the
# browser drops a redirected CORS request. Virtual-hosted style (<bucket>.s3.<region>...):
# with an explicit endpoint botocore would otherwise build path-style URLs, which AWS plans
# to retire. ingest downloads through the same client.
_s3 = boto3.client(
    "s3",
    region_name=config.REGION,
    endpoint_url=f"https://s3.{config.REGION}.amazonaws.com",
    config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
)
_ssm = boto3.client("ssm", region_name=config.REGION)

# Same rule as the page: no path separators, nothing that needs escaping in an S3 key or a URL.
_FILENAME = re.compile(r"[A-Za-z0-9._-]{1,100}")
_SUFFIXES = (".pdf", ".docx", ".html", ".htm", ".md", ".jsonl")
_UPLOAD_URL_SECONDS = 300
_MAX_UPLOAD_BYTES = 5 * 1024 * 1024
# The Acme files were loaded through uploads/ (`make acme-load`): their file names start with this.
_SEED_FILE_PREFIX = "acme-"
# Daily caps (UTC day) for callers without the admin token; credits are the budget (ADR 0030).
# ~2.3 calls and ~$0.016 per question: 150 calls ~ 65 questions, ~$1 a day (worst case ~$5).
_ASK_LLM_CALLS_PER_DAY = 150
_UPLOADS_PER_DAY = 50
# Ids and OFFSET are Postgres bigint: past these bounds the database would raise, a 500 for
# what is bad input. 18 digits always fit; a billion is far beyond the corpus.
_MAX_ID_DIGITS = 18
_MAX_OFFSET = 1_000_000_000
_MAX_QUESTION = 1000  # characters, as the page's text box


class _BadRequest(Exception):
    """Invalid input from the client: becomes 400 with this message."""


class _Forbidden(Exception):
    """The seed corpus is read-only without the admin token: becomes 403 with this message."""


class _OverDailyCap(Exception):
    """A daily cap is reached: becomes 429 with this message."""


def ingest(event, context):
    """S3 ObjectCreated on uploads/ or bulk/: parse each object and upsert its documents.

    Error policy: a bad file or shard (the parser's ValueError: corrupt, empty, unsupported
    suffix, a broken JSONL line) is logged and skipped, so one broken upload does not block the
    other objects of the event. Bedrock and database errors propagate: the invocation fails and
    Lambda's async retry reruns the whole event. `index.upsert_many` is idempotent (a rerun
    returns "unchanged" before any embedding), so a retry duplicates nothing; it embeds a whole
    file before writing it, so a retry re-embeds only what was not stored.
    """
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        # S3 event keys are URL-encoded ("my file.md" arrives as "my+file.md").
        key = unquote_plus(record["s3"]["object"]["key"])
        _ingest_object(bucket, key)


def _ingest_object(bucket: str, key: str) -> None:
    started = time.monotonic()
    name = key.rsplit("/", 1)[-1]
    log = {"handler": "ingest", "key": key}
    is_jsonl = name.lower().endswith(".jsonl")
    # A key ending in "/" is a folder marker (the S3 console makes them): no file to read.
    if not name or not (key.startswith("uploads/") or (key.startswith("bulk/") and is_jsonl)):
        print(json.dumps({**log, "skipped": "not an upload or a bulk shard"}))
        return

    # The directory (and the file in it) is removed even if parsing or indexing raises. The
    # file keeps its real name: `parse` takes the doc type from the suffix, the title from the
    # stem.
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        _s3.download_file(bucket, key, str(path))
        try:
            if is_jsonl:
                docs = parsers.read_jsonl(path)
                if key.startswith("uploads/"):
                    # Anyone with the page can upload: an uploaded shard only ever touches
                    # upload:* sources, never overwrites hotpotqa:* or another bulk document.
                    for doc in docs:
                        doc.source = f"upload:{name}:{doc.source}"
            else:
                docs = [parsers.parse(path, source=f"upload:{name}")]
        except ValueError as error:
            print(json.dumps({**log, "skipped": str(error)}))
            return
        # The whole file in one call: its chunks are embedded 96 per Bedrock request.
        counts = dict(Counter(status for status, _ in index.upsert_many(docs)))
    seconds = round(time.monotonic() - started, 1)
    print(json.dumps({**log, "counts": counts, "seconds": seconds}))


def schema(event, context):
    """CDK Provider on_event: Create and Update apply the schema, Delete keeps the data.

    The SQL text is a property of the custom resource, so a deploy that changes the file sends
    Update. Without parameters pg8000 uses the simple query protocol: the whole file runs in one
    call, as one implicit transaction, so a broken statement applies nothing.
    """
    if event["RequestType"] != "Delete":
        db.connect(SCHEMA_USER).run(event["ResourceProperties"]["Sql"])
    return {"PhysicalResourceId": "schema"}


def api(event, context):
    """Function URL handler: route, map errors to statuses, log one JSON line per request."""
    started = time.monotonic()
    method = event["requestContext"]["http"]["method"]
    route, item_id = _match(event["rawPath"])
    log = {"handler": "api", "method": method, "route": route}
    try:
        admin = _is_admin(event)
        log["admin"] = admin  # whether, never the token
        response = _dispatch(method, route, item_id, event, log, admin)
    except _BadRequest as error:
        response = _json(400, {"error": str(error)})
    except _Forbidden as error:
        response = _json(403, {"error": str(error)})
    except _OverDailyCap as error:
        response = _json(429, {"error": str(error)})
    except (pg8000.native.InterfaceError, OSError):
        # What escapes db.connect's retries: the cluster is still resuming from 0 ACU (or
        # unreachable). The page retries once after 15 s on 503.
        traceback.print_exc()
        response = _json(503, {"error": "database is resuming, retry in ~15 s"})
    except Exception:
        traceback.print_exc()  # to CloudWatch; the client never sees a traceback
        response = _json(500, {"error": "internal error"})
    ms = round((time.monotonic() - started) * 1000)
    print(json.dumps({**log, "status": response["statusCode"], "ms": ms}))
    return response


def _match(path: str) -> tuple[str, int | None]:
    """The route pattern and the id in it: "/documents/7" -> ("/documents/{id}", 7).

    Paths without an id come back as they are. A non-numeric or zero id matches nothing.
    """
    for prefix in ("/documents/", "/chunks/"):
        rest = path.removeprefix(prefix)
        if rest != path and rest.isascii() and rest.isdigit() and len(rest) <= _MAX_ID_DIGITS:
            if int(rest) > 0:
                return prefix + "{id}", int(rest)
    return path, None


def _is_admin(event: dict) -> bool:
    """True if the request carries the admin token in `x-admin-token` (ADR 0030).

    The Function URL lowercases header names. SSM is asked only when the header is present.
    compare_digest takes the same time wherever the strings differ: no timing oracle.
    """
    sent = (event.get("headers") or {}).get("x-admin-token")
    if not sent:
        return False
    token = _admin_token()
    return bool(token) and hmac.compare_digest(sent.encode(), token.encode())


@cache
def _admin_token() -> str:
    """The SecureString value, read once per container (cold start); "" if none is configured."""
    if not config.ADMIN_TOKEN_PARAM:
        return ""
    response = _ssm.get_parameter(Name=config.ADMIN_TOKEN_PARAM, WithDecryption=True)
    return response["Parameter"]["Value"]


def _is_seed(source: str) -> bool:
    """A document of the seed corpus: HotpotQA (`hotpotqa:*`, from bulk/) or Acme (`upload:acme-*`).

    Everything else is `upload:*` from a public upload. No column for it: the source already
    says where a document came from, and a backfill of 66k rows inside a deploy is a risk.
    """
    return not source.startswith("upload:") or source.startswith("upload:" + _SEED_FILE_PREFIX)


def _dispatch(
    method: str, route: str, item_id: int | None, event: dict, log: dict, admin: bool
) -> dict:
    """The response for one request; a route may add fields to the request's `log` line."""
    if (method, route) == ("GET", "/"):
        # Same origin as the API, so the page needs no CORS (ADR 0008).
        page = (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
        return {
            "statusCode": 200,
            "headers": {"content-type": "text/html; charset=utf-8"},
            "body": page,
        }
    if (method, route) == ("GET", "/health"):
        return _json(200, {"status": "ok"})
    if (method, route) == ("GET", "/documents"):
        params = event.get("queryStringParameters") or {}
        limit = _int_param(params, "limit", default=50, low=1, high=200)
        offset = _int_param(params, "offset", default=0, low=0, high=_MAX_OFFSET)
        documents, total = search.list_documents(limit=limit, offset=offset)
        return _json(200, {"documents": documents, "total": total})
    if (method, route) == ("POST", "/documents/upload-url"):
        body = _body(event)
        return _json(200, _upload_url(body.get("filename"), body.get("size"), admin))
    if (method, route) == ("GET", "/documents/{id}"):
        document = search.document_detail(item_id)
        return _json(200, document) if document is not None else _not_found("document")
    if (method, route) == ("DELETE", "/documents/{id}"):
        document = search.document_detail(item_id)
        if document is None:
            return _not_found("document")
        if _is_seed(document["source"]) and not admin:
            raise _Forbidden(
                "this document belongs to the seed corpus, which is read-only;"
                " upload your own file to try update and delete"
            )
        if not index.delete(item_id):
            return _not_found("document")
        return _json(200, {"deleted": item_id})
    if (method, route) == ("GET", "/chunks/{id}"):
        chunks = search.get_chunks([item_id])
        return _json(200, chunks[0]) if chunks else _not_found("chunk")
    if (method, route) == ("POST", "/ask"):
        return _ask(_body(event).get("question"), log, admin)
    return _json(404, {"error": "not found"})


def _ask(question: object, log: dict, admin: bool) -> dict:
    """Run the agent with the default configuration; add the cited chunks and the LLM usage.

    The daily cap counts Bedrock calls, not questions: a call served from `llm_cache` costs
    nothing and is not counted. It is checked before the run and added after it, so the
    questions running when the cap is reached finish (at most 4 at once, the api's reserved
    concurrency) and overshoot it a little. The admin's calls are counted too, never refused.
    """
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= _MAX_QUESTION:
        raise _BadRequest(f"question: 1-{_MAX_QUESTION} characters")
    if not admin and _usage_today("ask_llm_calls") >= _ASK_LLM_CALLS_PER_DAY:
        raise _OverDailyCap(
            "the daily question budget of this demo is used up; try after 00:00 UTC"
        )
    answer = agent.ask(question.strip())
    cited = [cid for claim in answer.claims + answer.contradictions for cid in claim.citations]
    steps = [entry for entry in answer.trace if entry["step"] == "llm"]
    cache_hits = sum(step["cached"] for step in steps)
    if len(steps) > cache_hits:
        _add_usage("ask_llm_calls", len(steps) - cache_hits)
    log.update(
        answer_status=answer.status,
        llm_steps=len(steps),
        models=sorted({step["model"] for step in steps}),
        input_tokens=_usage(steps, "inputTokens"),
        output_tokens=_usage(steps, "outputTokens"),
        prompt_cache_read_tokens=_usage(steps, "cacheReadInputTokens"),
        llm_cache_hits=cache_hits,
    )
    return _json(200, {**asdict(answer), "sources": search.get_chunks(cited)})


def _usage_today(counter: str) -> int:
    """The counter's value for the current UTC day (0 before its first use that day)."""
    rows = db.run(
        "SELECT n FROM daily_usage WHERE day = (now() AT TIME ZONE 'UTC')::date AND counter = :c",
        c=counter,
    )
    return rows[0][0] if rows else 0


def _add_usage(counter: str, n: int) -> int:
    """Add n to the counter of the current UTC day, atomically; return the new value.

    ponytail: if the connection dies after the server ran it, db.run's retry adds n twice; the
    cap then errs on the safe side.
    """
    rows = db.run(
        "INSERT INTO daily_usage (day, counter, n)"
        " VALUES ((now() AT TIME ZONE 'UTC')::date, :c, :n)"
        " ON CONFLICT (day, counter) DO UPDATE SET n = daily_usage.n + EXCLUDED.n RETURNING n",
        c=counter,
        n=n,
    )
    return rows[0][0]


def _usage(steps: list[dict], key: str) -> int:
    """One Converse token count summed over the LLM steps (cache counts may be absent)."""
    return sum(step["usage"].get(key, 0) for step in steps)


def _upload_url(filename: object, size: object, admin: bool) -> dict:
    if not isinstance(filename, str) or not _FILENAME.fullmatch(filename):
        raise _BadRequest("filename: 1-100 characters of letters, digits, '.', '_', '-'")
    if not filename.lower().endswith(_SUFFIXES):
        raise _BadRequest("filename: unsupported type, allowed: " + " ".join(_SUFFIXES))
    # bool is an int in Python: reject it explicitly.
    if type(size) is not int or not 1 <= size <= _MAX_UPLOAD_BYTES:
        raise _BadRequest(f"size: the file's size in bytes, 1-{_MAX_UPLOAD_BYTES} (5 MB)")
    # Uploading an Acme file name again would update a seed document (same source).
    if filename.startswith(_SEED_FILE_PREFIX) and not admin:
        raise _Forbidden(f"'{_SEED_FILE_PREFIX}*' names belong to the read-only seed corpus")
    if not admin and _add_usage("uploads", 1) > _UPLOADS_PER_DAY:
        raise _OverDailyCap("the daily upload budget of this demo is used up; try after 00:00 UTC")
    key = f"uploads/{filename}"
    # Content-Length is signed: S3 refuses a body of any other size, so the 5 MB limit holds
    # (a presigned PUT has no size range; the browser sets this header from the file itself).
    # No ContentType: a signed Content-Type would have to be sent by the browser exactly, and
    # the page PUTs the raw body without custom headers.
    url = _s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": config.BUCKET, "Key": key, "ContentLength": size},
        ExpiresIn=_UPLOAD_URL_SECONDS,
    )
    return {"url": url, "key": key}


def _body(event: dict) -> dict:
    """The JSON object in the request body; the Function URL base64-encodes non-text bodies."""
    raw = event.get("body") or ""
    try:
        if event.get("isBase64Encoded"):
            raw = base64.b64decode(raw, validate=True)
        body = json.loads(raw)
    except ValueError as error:  # bad base64, bad UTF-8 and bad JSON are all ValueErrors
        raise _BadRequest("body must be a JSON object") from error
    if not isinstance(body, dict):
        raise _BadRequest("body must be a JSON object")
    return body


def _int_param(params: dict, name: str, default: int, low: int, high: int) -> int:
    raw = params.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise _BadRequest(f"{name} must be an integer") from error
    if not low <= value <= high:
        raise _BadRequest(f"{name} must be {low}-{high}")
    return value


def _not_found(what: str) -> dict:
    return _json(404, {"error": f"{what} not found"})


def _json(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }
