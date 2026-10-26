---
title: API contract
status: current
last_updated: 2026-10-26
owner: Pro100Sergosha
---

# 04 API contract

The HTTP interface of the `api` Lambda (Function URL) that the UI (`static/index.html`) and the
smoke check code against. `handlers.api` serves every route below. The UI's stub mode
(`/?stub`) shows canned answers without a backend.

## Conventions

- JSON in and out, `content-type: application/json`, except `GET /` (HTML). A request body may
  arrive base64-encoded (`isBase64Encoded`, the Function URL does that for non-text types);
  it is decoded before parsing.
- Router: hand-written, exact `(method, path)` matches plus `/documents/{id}` and
  `/chunks/{id}`. An id is a positive integer of at most 18 digits (it must fit a Postgres
  bigint); anything else, and a known path with another method, is 404.
- Errors: `{"error": "<human-readable message>"}`, never a traceback:

  | Status | When |
  |---|---|
  | 400 | invalid JSON body or not an object, bad `limit`/`offset`, bad filename, `question` missing, not a string, blank or over 1000 characters (after stripping) |
  | 429 | from Lambda itself, not our JSON: more than 4 requests at once (reserved concurrency of `api`, ADR 0025). The UI says "busy, try again in a minute" |
  | 404 | unknown route, malformed id, unknown document or chunk id |
  | 503 | `{"error": "database is resuming, retry in ~15 s"}`: a pg8000 `InterfaceError` or `OSError` escaped `db.connect`'s retries (cluster resuming from 0 ACU, or unreachable). The UI waits 15 s and retries once |
  | 500 | `{"error": "internal error"}` for anything else; the traceback goes to CloudWatch only |

- Logs: one JSON line per request, `{"handler": "api", "method", "route", "status", "ms"}`;
  `route` is the pattern (`/documents/{id}`), not the raw path. `POST /ask` adds
  `answer_status`, `llm_steps`, `models` (the models that answered, sorted), `input_tokens`,
  `output_tokens`, `prompt_cache_read_tokens` (Bedrock prompt cache) and `llm_cache_hits`
  (calls served from `llm_cache`). No custom metrics.
- Ids are integers. Timestamps are ISO 8601 strings in UTC.
- Document text is untrusted: the UI renders it as text (`textContent`), never as HTML.

## Routes

| Method and path | Request | Response 200 |
|---|---|---|
| `GET /` | - | the UI page (`text/html`) |
| `GET /health` | - | `{"status": "ok"}` |
| `GET /documents?limit=50&offset=0` | `limit` 1-200, default 50; `offset` 0-10^9, default 0 | `{"documents": [Document], "total": int}`, newest first |
| `GET /documents/{id}` | - | `Document` plus `"text": str` and `"metadata": {}` |
| `POST /documents/upload-url` | `{"filename": str}` | `{"url": str, "key": str}` |
| `DELETE /documents/{id}` | - | `{"deleted": id}` |
| `GET /chunks/{id}` | - | `Source` plus `"ord": int` |
| `POST /ask` | `{"question": str}`, 1-1000 characters after stripping | `Answer` |

`Document` = `{"id", "source", "title", "doc_type", "version", "created_at", "chunks": int}`.

`Source` = `{"chunk_id", "document_id", "title", "source", "text"}`.

`Answer` = the `Answer` dataclass of `src/engine/models.py` as JSON, plus the cited chunks so the
UI needs no extra requests:

```json
{
  "status": "answered | insufficient | conflicting",
  "answer": "the direct answer in a few words, empty when insufficient",
  "claims": [{"text": "...", "citations": [101, 205]}],
  "contradictions": [{"text": "Report A says 14:02, report B says 14:30", "citations": [101, 307]}],
  "sources": [Source, "... one per chunk id cited above"],
  "trace": [{"step": "search", "...": "free-form, shown as JSON in the UI"}]
}
```

`POST /ask` runs `agent.ask(question)` with the defaults (strategy `fixed`, mode `mmr`,
6 steps; the client cannot choose them) and answers within ~80 s
([ADR 0025](adr/0025-agent-loop-seeded-forced-deadline.md)). `sources` holds every chunk cited
in `claims` and `contradictions`, once each, in citation order. A model that fails, times out
or misbehaves gives status 200 with `"status": "insufficient"` and the reason in `trace`, not
an error status. Trace steps: `search` (`query`, `k`, `chunk_ids`, `seed` for the server's
own first search), `llm` (`model`, `cached`, `usage`, `stop_reason`, `forced`, `ms`),
`get_document`, `reprompt`, `deadline`, `error`, and one `grounding` entry with what the
validator dropped.

## Upload, update and delete

1. The UI asks `POST /documents/upload-url` with the file name. The server accepts only
   `[A-Za-z0-9._-]{1,100}` with a supported suffix (`.pdf .docx .html .htm .md .jsonl`,
   case-insensitive), else 400, and returns a presigned S3 `PUT` URL for key
   `uploads/<filename>` (valid 5 minutes). The URL is SigV4 on the regional virtual-hosted
   endpoint (`<bucket>.s3.eu-north-1.amazonaws.com`): with the global endpoint a recently
   created bucket answers the browser's preflight/PUT with a 307 redirect, which breaks CORS.
   Only `host` is signed, so the browser may send any `Content-Type` and no custom headers.
2. The browser `PUT`s the file body to `url`. The S3 event triggers `ingest`, which parses,
   dedups, chunks, embeds and stores it with `source = "upload:<filename>"`. A `.jsonl` upload
   is read as a shard instead: one document per line, `source = "upload:<filename>:<line
   source>"`.
3. Ingestion is asynchronous: the UI polls `GET /documents` until the document appears.

Update = upload a file with the same name: same `source`, new content hash -> `version + 1`, its
chunks replaced in one transaction. Same content hash as any existing document (under any
source) -> skipped as a duplicate. Delete removes the document and its chunks (cascade).

## Ingest

`handlers.ingest` takes S3 `ObjectCreated` events (keys URL-decoded with `unquote_plus`). For
each object it downloads the file into a temporary directory under `/tmp` (removed afterwards,
even on error), then:

| Key | Read with | `source` |
|---|---|---|
| `bulk/**.jsonl` | `parsers.read_jsonl` | from each line |
| `uploads/<name>.jsonl` | `parsers.read_jsonl` | `upload:<name>:<line source>` |
| `uploads/<name>` (other suffix) | `parsers.parse` | `upload:<name>` |
| anything else (`bulk/` non-JSONL, folder markers) | skipped without download | - |

Uploads only ever touch `upload:*` sources: anyone with the page can upload, so an uploaded
shard's line sources are prefixed and cannot overwrite a `hotpotqa:*` or other bulk document.
Only `bulk/` shards (written by the jobs project, not reachable from the page) keep their
sources as they are.

and calls `index.upsert_many` once with all documents of the file (their chunks are embedded 96
per Bedrock request; llm-wiki/03 Write paths). One JSON log line per object:
`{"handler": "ingest", "key", "counts": {"inserted": n, "unchanged": n, ...}, "seconds"}`, or
`"skipped": "<reason>"`.

Error policy:
- A bad file is logged and skipped (`ValueError` from the parser: corrupt, empty, unsupported
  suffix, an invalid JSONL line). The other objects of the event still load. `read_jsonl`
  rejects a whole shard on its first bad line, so one bad line skips its shard.
- Bedrock and database errors propagate: the invocation fails and Lambda's async retry reruns
  the event (2 retries). `index.upsert_many` is idempotent, a rerun returns `unchanged` before
  any embedding, so nothing is duplicated.
- An event that still fails after the retries (or waited longer than 6 h for a free `ingest`)
  is not dropped: Lambda sends it to the SQS queue `IngestFailures` (kept 14 days), with the
  error. `make redrive-ingest` (jobs project) invokes `ingest` again with each stored event and
  deletes the message once the invoke is accepted (llm-wiki/07).
