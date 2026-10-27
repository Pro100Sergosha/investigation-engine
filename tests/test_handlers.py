import base64
import json
import shutil
from collections import Counter
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import boto3
import pg8000.native
import pytest

from engine import agent, handlers, index, search
from engine.handlers import api, ingest, schema
from engine.models import Answer, Claim

FIXTURES = Path(__file__).parent / "fixtures"


def _event(
    method: str,
    path: str,
    query: dict | None = None,
    body: str | None = None,
    headers: dict | None = None,
) -> dict:
    event = {"requestContext": {"http": {"method": method}}, "rawPath": path}
    if headers is not None:
        event["headers"] = headers
    if query is not None:
        event["queryStringParameters"] = query
    if body is not None:
        event["body"] = body
        event["isBase64Encoded"] = False
    return event


def _call(event: dict) -> tuple[int, dict]:
    response = api(event, None)
    return response["statusCode"], json.loads(response["body"])


def test_health_logs_one_json_line(capsys):
    assert _call(_event("GET", "/health")) == (200, {"status": "ok"})
    line = json.loads(capsys.readouterr().out)
    assert line["method"] == "GET" and line["route"] == "/health" and line["status"] == 200
    assert isinstance(line["ms"], int)


def test_root_serves_the_ui_page():
    response = api(_event("GET", "/"), None)
    assert response["statusCode"] == 200
    assert response["headers"]["content-type"].startswith("text/html")
    assert "<title>Investigation Engine</title>" in response["body"]


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/nope"),
        ("GET", "/ask"),
        ("POST", "/documents"),
        ("GET", "/documents/abc"),
        ("GET", "/documents/0"),
        ("GET", "/documents/-1"),
        ("GET", "/documents/1/x"),
        ("GET", "/chunks/"),
        ("GET", "/chunks/" + "9" * 19),
    ],
)
def test_unknown_routes_and_bad_ids_are_404(method, path):
    assert _call(_event(method, path))[0] == 404


def test_list_documents_passes_paging(monkeypatch):
    calls = []

    def fake(limit, offset):
        calls.append((limit, offset))
        return [{"id": 1}], 7

    monkeypatch.setattr(search, "list_documents", fake)
    assert _call(_event("GET", "/documents")) == (200, {"documents": [{"id": 1}], "total": 7})
    _call(_event("GET", "/documents", query={"limit": "200", "offset": "50"}))
    assert calls == [(50, 0), (200, 50)]


@pytest.mark.parametrize(
    "query", [{"limit": "0"}, {"limit": "201"}, {"limit": "x"}, {"offset": "-1"}]
)
def test_list_documents_rejects_bad_paging(query):
    status, body = _call(_event("GET", "/documents", query=query))
    assert status == 400 and "error" in body


def test_document_detail_and_404(monkeypatch):
    monkeypatch.setattr(search, "document_detail", lambda i: {"id": i} if i == 5 else None)
    assert _call(_event("GET", "/documents/5")) == (200, {"id": 5})
    assert _call(_event("GET", "/documents/6"))[0] == 404


@pytest.fixture
def usage(monkeypatch):
    """db.run for the daily_usage counters, kept in a Counter ({counter: n})."""
    counters = Counter()

    def run(sql, c, n=None):
        if sql.startswith("INSERT"):
            counters[c] += n
        return [[counters[c]]] if c in counters else []

    monkeypatch.setattr(handlers.db, "run", run)
    return counters


ADMIN = {"x-admin-token": "s3cret-token"}


@pytest.fixture
def admin_token(monkeypatch):
    """The token the api compares against, instead of the SSM parameter."""
    monkeypatch.setattr(handlers, "_admin_token", lambda: ADMIN["x-admin-token"])


@pytest.fixture
def documents(monkeypatch, admin_token):
    """Three stored documents by id: an upload, a HotpotQA and an Acme one; deletes recorded."""
    sources = {5: "upload:report.md", 6: "hotpotqa:Alpha", 7: "upload:acme-inc-201.pdf"}
    deleted = []

    def detail(i):
        return {"id": i, "source": sources[i]} if i in sources else None

    monkeypatch.setattr(search, "document_detail", detail)
    monkeypatch.setattr(index, "delete", lambda i: deleted.append(i) or True)
    return deleted


def test_delete_an_upload_and_404(documents):
    assert _call(_event("DELETE", "/documents/5")) == (200, {"deleted": 5})
    assert _call(_event("DELETE", "/documents/8"))[0] == 404
    assert documents == [5]


@pytest.mark.parametrize("document_id", [6, 7])
def test_delete_of_a_seed_document_is_403(documents, document_id):
    status, body = _call(_event("DELETE", f"/documents/{document_id}"))
    assert status == 403 and "read-only" in body["error"]
    assert documents == []


@pytest.mark.parametrize(
    "headers", [{"x-admin-token": "wrong"}, {"x-admin-token": ""}, {"x-other": "s3cret-token"}]
)
def test_a_wrong_admin_token_is_rejected(documents, headers):
    assert _call(_event("DELETE", "/documents/6", headers=headers))[0] == 403
    assert documents == []


def test_the_admin_token_deletes_a_seed_document(documents, capsys):
    assert _call(_event("DELETE", "/documents/6", headers=ADMIN)) == (200, {"deleted": 6})
    out = capsys.readouterr().out
    assert json.loads(out)["admin"] is True and ADMIN["x-admin-token"] not in out


def test_no_admin_without_a_configured_parameter(monkeypatch):
    monkeypatch.setattr(handlers.config, "ADMIN_TOKEN_PARAM", "")
    handlers._admin_token.cache_clear()
    assert not handlers._is_admin(_event("GET", "/", headers={"x-admin-token": "anything"}))


def test_the_admin_token_is_read_from_ssm_once(monkeypatch):
    calls = []

    class FakeSsm:
        def get_parameter(self, Name, WithDecryption):
            calls.append((Name, WithDecryption))
            return {"Parameter": {"Value": ADMIN["x-admin-token"]}}

    monkeypatch.setattr(handlers, "_ssm", FakeSsm())
    monkeypatch.setattr(handlers.config, "ADMIN_TOKEN_PARAM", "/investigation/admin-token")
    handlers._admin_token.cache_clear()
    try:
        assert handlers._is_admin(_event("GET", "/", headers=ADMIN))
        assert not handlers._is_admin(_event("GET", "/", headers={"x-admin-token": "nope"}))
        assert not handlers._is_admin(_event("GET", "/"))
    finally:
        handlers._admin_token.cache_clear()
    assert calls == [("/investigation/admin-token", True)]


def test_chunk_and_404(monkeypatch):
    chunk = {"chunk_id": 9, "document_id": 1, "title": "t", "source": "s", "text": "x", "ord": 0}
    monkeypatch.setattr(search, "get_chunks", lambda ids: [chunk] if ids == [9] else [])
    assert _call(_event("GET", "/chunks/9")) == (200, chunk)
    assert _call(_event("GET", "/chunks/10"))[0] == 404


@pytest.mark.parametrize(
    "body",
    ["{}", '{"question": "   "}', '{"question": 5}', json.dumps({"question": "a" * 1001}), "[]"],
)
def test_ask_rejects_bad_questions(monkeypatch, body):
    monkeypatch.setattr(agent, "ask", lambda question: pytest.fail("agent must not run"))
    status, response = _call(_event("POST", "/ask", body=body))
    assert status == 400 and "error" in response


def test_ask_returns_answer_with_cited_sources_and_logs_llm_usage(monkeypatch, capsys, usage):
    tokens = {"inputTokens": 100, "outputTokens": 20, "cacheReadInputTokens": 50}
    answer = Answer(
        status="conflicting",
        answer="14:02",
        claims=[Claim("Started 14:02.", [5])],
        contradictions=[Claim("14:02 vs 14:30.", [5, 9])],
        trace=[
            {"step": "llm", "model": "haiku", "cached": True, "usage": tokens},
            {"step": "search", "query": "q"},
            {"step": "llm", "model": "gpt-oss", "cached": False, "usage": tokens},
        ],
    )
    questions, asked_ids = [], []
    monkeypatch.setattr(agent, "ask", lambda q: questions.append(q) or answer)

    def get_chunks(ids):
        asked_ids.append(ids)
        return [{"chunk_id": i} for i in dict.fromkeys(ids)]

    monkeypatch.setattr(search, "get_chunks", get_chunks)
    status, body = _call(_event("POST", "/ask", body='{"question": "  When?  "}'))
    assert status == 200 and questions == ["When?"]
    assert body["answer"] == "14:02" and body["status"] == "conflicting"
    assert body["claims"] == [{"text": "Started 14:02.", "citations": [5]}]
    assert asked_ids == [[5, 5, 9]] and body["sources"] == [{"chunk_id": 5}, {"chunk_id": 9}]
    line = json.loads(capsys.readouterr().out)
    assert line["route"] == "/ask" and line["status"] == 200
    assert line["llm_steps"] == 2 and line["models"] == ["gpt-oss", "haiku"]
    assert (line["input_tokens"], line["output_tokens"]) == (200, 40)
    assert line["prompt_cache_read_tokens"] == 100 and line["llm_cache_hits"] == 1
    assert usage == {"ask_llm_calls": 1}  # the call served from llm_cache is not counted


def test_ask_over_the_daily_cap_is_429_without_running_the_agent(monkeypatch, usage):
    usage["ask_llm_calls"] = handlers._ASK_LLM_CALLS_PER_DAY
    monkeypatch.setattr(agent, "ask", lambda question: pytest.fail("agent must not run"))
    status, body = _call(_event("POST", "/ask", body='{"question": "When?"}'))
    assert status == 429 and "daily" in body["error"]


def test_the_admin_token_skips_the_ask_cap(monkeypatch, usage, admin_token):
    usage["ask_llm_calls"] = handlers._ASK_LLM_CALLS_PER_DAY
    answer = Answer(status="insufficient", answer="", claims=[], contradictions=[], trace=[])
    monkeypatch.setattr(agent, "ask", lambda question: answer)
    monkeypatch.setattr(search, "get_chunks", lambda ids: [])
    event = _event("POST", "/ask", body='{"question": "When?"}', headers=ADMIN)
    assert _call(event)[0] == 200


@pytest.fixture
def s3_with_fake_credentials(monkeypatch):
    """The module's client, rebuilt with fake credentials: presigning is offline signing."""
    meta = handlers._s3.meta
    client = boto3.client(
        "s3",
        region_name=meta.region_name,
        endpoint_url=meta.endpoint_url,
        config=meta.config,
        aws_access_key_id="AKIAEXAMPLE",
        aws_secret_access_key="secret",
    )
    monkeypatch.setattr(handlers, "_s3", client)
    monkeypatch.setattr(handlers.config, "BUCKET", "docs-bucket")


def _upload(filename: str, size: int = 1234, headers: dict | None = None) -> dict:
    body = json.dumps({"filename": filename, "size": size})
    return _event("POST", "/documents/upload-url", body=body, headers=headers)


def test_upload_url_is_a_regional_sigv4_put(s3_with_fake_credentials, usage):
    status, body = _call(_upload("a-1.MD"))
    assert status == 200 and body["key"] == "uploads/a-1.MD"
    url = urlsplit(body["url"])
    # Regional host: the global one redirects a new bucket's CORS PUT with a 307.
    assert url.hostname == "docs-bucket.s3.eu-north-1.amazonaws.com"
    assert url.path == "/uploads/a-1.MD"
    params = parse_qs(url.query)
    assert params["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert params["X-Amz-Expires"] == ["300"]
    # The size is signed (S3 refuses any other body length); no Content-Type to match.
    assert params["X-Amz-SignedHeaders"] == ["content-length;host"]
    assert usage == {"uploads": 1}


def test_an_acme_file_name_is_403_unless_admin(s3_with_fake_credentials, usage, admin_token):
    status, body = _call(_upload("acme-inc-201.pdf"))
    assert status == 403 and "seed" in body["error"]
    assert _call(_upload("acme-inc-201.pdf", headers=ADMIN))[0] == 200


def test_uploads_over_the_daily_cap_are_429(s3_with_fake_credentials, usage):
    usage["uploads"] = handlers._UPLOADS_PER_DAY - 1
    assert _call(_upload("a.md"))[0] == 200
    status, body = _call(_upload("a.md"))
    assert status == 429 and "daily" in body["error"]


def test_upload_url_accepts_a_base64_body(s3_with_fake_credentials, usage):
    event = _event("POST", "/documents/upload-url")
    event["body"] = base64.b64encode(b'{"filename": "r.pdf", "size": 10}').decode()
    event["isBase64Encoded"] = True
    assert _call(event)[1]["key"] == "uploads/r.pdf"


@pytest.mark.parametrize(
    "body",
    [
        '{"filename": "notes.txt", "size": 10}',
        '{"filename": "a.md"}',
        '{"filename": "a.md", "size": 0}',
        '{"filename": "a.md", "size": 5242881}',
        '{"filename": "a.md", "size": "10"}',
        '{"filename": "a.md", "size": true}',
        '{"filename": "../x.md"}',
        '{"filename": "a b.md"}',
        '{"filename": "' + "a" * 98 + '.md"}',
        '{"filename": 5}',
        "{}",
        "not json",
        "[]",
        "",
    ],
)
def test_upload_url_rejects_bad_input(body):
    status, response = _call(_event("POST", "/documents/upload-url", body=body))
    assert status == 400 and "error" in response


def test_database_resuming_is_503(monkeypatch):
    def resuming(limit, offset):
        raise pg8000.native.InterfaceError("connection refused")

    monkeypatch.setattr(search, "list_documents", resuming)
    status, body = _call(_event("GET", "/documents"))
    assert status == 503 and "resuming" in body["error"]


def test_unexpected_error_is_500_without_traceback(monkeypatch, capsys):
    def broken(document_id):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(search, "document_detail", broken)
    response = api(_event("GET", "/documents/1"), None)
    assert response["statusCode"] == 500
    assert json.loads(response["body"]) == {"error": "internal error"}
    assert "secret detail" not in response["body"]
    assert "Traceback" in capsys.readouterr().err  # it goes to CloudWatch instead


# ---------- ingest ----------


def _s3_event(*keys: str) -> dict:
    return {
        "Records": [{"s3": {"bucket": {"name": "docs-bucket"}, "object": {"key": k}}} for k in keys]
    }


@pytest.fixture
def ingest_env(monkeypatch, tmp_path):
    """S3 downloads copy a fixture (by file name, "+" decoded); upserts are recorded."""
    upserts = []
    downloads = []

    def download_file(bucket, key, filename):
        downloads.append(key)
        source = tmp_path / key.rsplit("/", 1)[-1]
        if not source.exists():
            source = FIXTURES / key.rsplit("/", 1)[-1].replace(" ", "")
        shutil.copy(source, filename)

    def upsert_many(docs):
        upserts.extend(docs)
        return [("inserted", len(upserts) - len(docs) + i + 1) for i in range(len(docs))]

    monkeypatch.setattr(handlers._s3, "download_file", download_file)
    monkeypatch.setattr(index, "upsert_many", upsert_many)
    return upserts, downloads, tmp_path


def test_ingest_bulk_shard(ingest_env, capsys):
    upserts, _, _ = ingest_env
    ingest(_s3_event("bulk/hotpotqa/shard.jsonl"), None)
    assert [d.source for d in upserts] == ["hotpotqa:Alpha", "hotpotqa:Beta"]
    line = json.loads(capsys.readouterr().out)
    assert line["key"] == "bulk/hotpotqa/shard.jsonl" and line["counts"] == {"inserted": 2}


def test_ingest_upload_uses_upload_source_and_decodes_the_key(ingest_env):
    upserts, downloads, _ = ingest_env
    ingest(_s3_event("uploads/run+book.md"), None)
    assert downloads == ["uploads/run book.md"]
    assert [(d.source, d.title, d.doc_type) for d in upserts] == [
        ("upload:run book.md", "Runbook", "md")
    ]


def test_ingest_prefixes_sources_of_an_uploaded_shard(ingest_env):
    upserts, _, _ = ingest_env
    ingest(_s3_event("uploads/shard.jsonl"), None)
    assert [d.source for d in upserts] == [
        "upload:shard.jsonl:hotpotqa:Alpha",
        "upload:shard.jsonl:hotpotqa:Beta",
    ]


def test_ingest_skips_a_bad_file_and_keeps_going(ingest_env, capsys):
    upserts, _, tmp_path = ingest_env
    (tmp_path / "broken.jsonl").write_text('{"source": "x"\n', encoding="utf-8")
    (tmp_path / "notes.txt").write_text("text", encoding="utf-8")
    ingest(_s3_event("uploads/broken.jsonl", "uploads/notes.txt", "uploads/runbook.md"), None)
    assert [d.source for d in upserts] == ["upload:runbook.md"]
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert "line 1" in lines[0]["skipped"] and "unsupported" in lines[1]["skipped"]


def test_ingest_ignores_other_objects(ingest_env):
    _, downloads, _ = ingest_env
    ingest(_s3_event("bulk/labels.json", "uploads/"), None)
    assert downloads == []


def test_ingest_lets_database_errors_propagate(ingest_env, monkeypatch):
    def down(docs):
        raise pg8000.native.InterfaceError("gone")

    monkeypatch.setattr(index, "upsert_many", down)
    with pytest.raises(pg8000.native.InterfaceError):
        ingest(_s3_event("uploads/runbook.md"), None)


def test_schema_delete_keeps_the_data():
    # Delete makes no AWS call: without credentials it would fail if it tried.
    assert schema({"RequestType": "Delete"}, None) == {"PhysicalResourceId": "schema"}
