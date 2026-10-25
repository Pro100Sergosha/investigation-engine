---
title: API contract
status: current
last_updated: 2026-10-25
owner: Pro100Sergosha
---

# 04 API contract

The HTTP interface of the `api` Lambda (Function URL) that the UI (`static/index.html`) and the
smoke check code against. `handlers.api` serves every route below except `POST /ask`, which
arrives with the agent; until then it answers 404 like any unknown route, and the UI's stub mode
(`/?stub`) is the only way to see an answer.

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
  | 400 | invalid JSON body or not an object, bad `limit`/`offset`, bad filename |
  | 404 | unknown route, malformed id, unknown document or chunk id |
  | 503 | `{"error": "database is resuming, retry in ~15 s"}`: a pg8000 `InterfaceError` or `OSError` escaped `db.connect`'s retries (cluster resuming from 0 ACU, or unreachable). The UI waits 15 s and retries once |
  | 500 | `{"error": "internal error"}` for anything else; the traceback goes to CloudWatch only |

- Logs: one JSON line per request, `{"handler": "api", "method", "route", "status", "ms"}`;
  `route` is the pattern (`/documents/{id}`), not the raw path. No custom metrics.
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
| `POST /ask` (not served yet, 404) | `{"question": str}`, 1-1000 characters | `Answer` |

`Document` = `{"id", "source", "title", "doc_type", "version", "created_at", "chunks": int}`.

`Source` = `{"chunk_id", "document_id", "title", "source", "text"}`.

`Answer` = the `Answer` dataclass of `src/engine/models.py` as JSON, plus the cited chunks so the
UI needs no extra requests:

```json
{
  "status": "answered | insufficient | conflicting",
  "claims": [{"text": "...", "citations": [101, 205]}],
  "contradictions": [{"text": "Report A says 14:02, report B says 14:30", "citations": [101, 307]}],
  "sources": [Source, "... one per chunk id cited above"],
  "trace": [{"step": "search", "...": "free-form, shown as JSON in the UI"}]
}
```

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
   is read as a bulk shard instead: each line keeps its own `source`.
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
| `uploads/<name>.jsonl` | `parsers.read_jsonl` | from each line |
| `uploads/<name>` (other suffix) | `parsers.parse` | `upload:<name>` |
| anything else (`bulk/` non-JSONL, folder markers) | skipped without download | - |

and calls `index.upsert` for every document, one after another. One JSON log line per object:
`{"handler": "ingest", "key", "counts": {"inserted": n, "unchanged": n, ...}, "seconds"}`, or
`"skipped": "<reason>"`.

Error policy:
- A bad file is logged and skipped (`ValueError` from the parser: corrupt, empty, unsupported
  suffix, an invalid JSONL line). The other objects of the event still load. `read_jsonl`
  rejects a whole shard on its first bad line, so one bad line skips its shard.
- Bedrock and database errors propagate: the invocation fails and Lambda's async retry reruns
  the event (2 retries). `index.upsert` is idempotent, a rerun returns `unchanged` before any
  embedding, so nothing is duplicated.
