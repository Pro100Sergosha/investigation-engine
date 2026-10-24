---
title: API contract
status: current
last_updated: 2026-10-24
owner: Pro100Sergosha
---

# 04 API contract

The HTTP interface of the `api` Lambda (Function URL) that the UI (`static/index.html`) and the
smoke check code against. Built so far: `GET /health` only; the rest is the agreed contract the
UI is written against with stub responses until `handlers.py` serves it.

## Conventions

- JSON in and out, `content-type: application/json`, except `GET /` (HTML).
- Errors: `{"error": "<human-readable message>"}` with status 400 (bad input), 404 (unknown id or
  route), 503 (database is resuming from a pause, retry in ~15 s), 500 (anything else). Never a
  traceback.
- Ids are integers. Timestamps are ISO 8601 strings in UTC.
- Document text is untrusted: the UI renders it as text (`textContent`), never as HTML.

## Routes

| Method and path | Request | Response 200 |
|---|---|---|
| `GET /` | - | the UI page (`text/html`) |
| `GET /health` | - | `{"status": "ok"}` |
| `GET /documents?limit=50&offset=0` | `limit` 1-200, default 50 | `{"documents": [Document], "total": int}`, newest first |
| `GET /documents/{id}` | - | `Document` plus `"text": str` and `"metadata": {}` |
| `POST /documents/upload-url` | `{"filename": str}` | `{"url": str, "key": str}` |
| `DELETE /documents/{id}` | - | `{"deleted": id}` |
| `GET /chunks/{id}` | - | `Source` plus `"ord": int` |
| `POST /ask` | `{"question": str}`, 1-1000 characters | `Answer` |

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
   `[A-Za-z0-9._-]{1,100}` with a supported suffix (`.pdf .docx .html .htm .md .jsonl`), else
   400, and returns a presigned S3 `PUT` URL for key `uploads/<filename>` (valid 5 minutes).
2. The browser `PUT`s the file body to `url`. The S3 event triggers `ingest`, which parses,
   dedups, chunks, embeds and stores it with `source = "upload:<filename>"`.
3. Ingestion is asynchronous: the UI polls `GET /documents` until the document appears.

Update = upload a file with the same name: same `source`, new content hash -> `version + 1`, its
chunks replaced in one transaction. Same content hash as any existing document (under any
source) -> skipped as a duplicate. Delete removes the document and its chunks (cascade).
