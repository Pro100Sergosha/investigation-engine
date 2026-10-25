---
title: Data model
status: current
last_updated: 2026-10-25
owner: Pro100Sergosha
---

# 03 Data model

One Postgres database, the default `postgres` (express configuration creates no other), on Aurora Serverless v2 (PostgreSQL 17.9 with pgvector),
express configuration, reached over TLS with IAM auth tokens through `engine.db`
([ADR 0021](adr/0021-aurora-express-iam-auth.md)). The whole schema is
[`sql/schema.sql`](../sql/schema.sql); how it gets applied is in
[07 Infrastructure](07-infrastructure.md#database-schema).

Two roles: `postgres` (master, owns the tables, used only by the schema custom resource) and `app`
(`LOGIN`, `rds_iam`, `SELECT/INSERT/UPDATE/DELETE` on all tables, `USAGE` on sequences), which
`api`, `ingest` and the jobs log in as. `app` cannot create, alter or drop anything.

## Tables

```
documents 1 ──< chunks          llm_cache (standalone)
```

### `documents`: one row per document

| Column | Type | Why |
|---|---|---|
| `id` | `bigint` identity, PK | the id in the API and in `Hit.document_id` |
| `source` | `text`, **unique** | the identity of a document (`upload:<filename>`, `hotpotqa:<title>`); re-uploading the same source is an *update* |
| `title` | `text` | shown with every citation |
| `doc_type` | `text` | `pdf`, `docx`, `html`, `md`, `jsonl` (`ParsedDoc.doc_type`) |
| `content_hash` | `text`, **unique** | `engine.index.content_hash(text)`: sha256 of the normalized text. The same content under any source is a duplicate and is skipped |
| `version` | `int`, default 1 | `+1` on every update of the same source with new content |
| `text` | `text` | the full parsed text, for `GET /documents/{id}` and `get_document()` |
| `metadata` | `jsonb`, default `{}` | `ParsedDoc.metadata` (date, services, ...) |
| `created_at` | `timestamptz`, default `now()` | newest-first listing |

`text` is stored once here and not rebuilt from chunks: fixed chunks overlap and collapse
whitespace, structured chunks repeat headings, so neither reproduces the document.

### `chunks`: the search units

| Column | Type | Why |
|---|---|---|
| `id` | `bigint` identity, PK | the id that claims cite (`Claim.citations`) |
| `document_id` | `bigint` -> `documents(id)` **on delete cascade** | deleting a document removes its chunks in the same statement |
| `strategy` | `text` | `fixed` or `structured` (`chunking.py`). Both strategies live side by side so the evaluation can compare them without reloading; search filters on it |
| `ord` | `int` | position within the document for that strategy |
| `text` | `text` | what is embedded, searched and shown |
| `tsv` | `tsvector`, generated `to_tsvector('english', text)` stored | keyword search; computed by Postgres, so it can never drift from `text` |
| `embedding` | `halfvec(1024)` | Cohere Embed V4 (`search_document`, ADR 0022), 1024 dimensions, half precision: half the storage and index size of `vector`; pgvector's HNSW indexes it directly |

`unique (document_id, strategy, ord)`: a document has one chunk per position per strategy.

### `llm_cache`: LLM responses by prompt hash

| Column | Type | Why |
|---|---|---|
| `prompt_hash` | `text`, PK | hash of model + prompt, computed by `llm.py` |
| `model` | `text` | which model answered |
| `response` | `jsonb` | the raw Converse response |
| `created_at` | `timestamptz` | when it was cached |

Reruns of the evaluation and repeated demo questions cost nothing.

## Indexes

| Index | Serves |
|---|---|
| `chunks_tsv_idx`, GIN on `tsv` | keyword search (`@@`, `ts_rank_cd`) |
| `chunks_embedding_fixed_idx`, `chunks_embedding_structured_idx`: partial HNSW on `embedding halfvec_cosine_ops WHERE strategy = '<strategy>'` | dense search by cosine distance (`<=>`) within one strategy. A shared index returned ~half the rows: pgvector filters after the scan, which yields at most `hnsw.ef_search` (40) rows ([ADR 0024](adr/0024-partial-hnsw-per-strategy-or-keyword-query.md)) |
| unique `(document_id, strategy, ord)` | chunks of one document, the cascade delete, and the re-insert on update. It starts with `document_id`, so a separate index on `document_id` alone would be redundant |
| unique `source`, unique `content_hash` | update-by-source and exact dedup |

The HNSW indexes are created while the table is empty and then maintained on every insert: building
them over a loaded table inside a deploy would hold the schema custom resource for minutes.

## Write paths

Every document write is `engine.index.upsert_many(docs) -> [(status, id)]` or
`index.delete(id)`; `upsert(doc)` is `upsert_many([doc])[0]`. `ingest` passes a whole file (one
upload, or a 500-document shard), so uploads and the bulk load take the same path. The result is
the same as storing the documents one after another, in order. For each document, in order (the
first three steps cost no Bedrock call, so rerunning a shard is free):

1. Blank text -> `empty`, nothing stored.
2. `source` known with the same `content_hash` -> `unchanged` (a rerun).
3. `content_hash` stored under another source -> `duplicate`, with that document's id.
   A document with the same `source` or `content_hash` as an *earlier document of the same
   batch that is about to be written* skips the checks and waits for a second round, after that
   one is stored; there the checks above see it (`duplicate`, `unchanged` or `updated`). So two
   documents of one shard never both insert.
4. Chunk every remaining document with both strategies (`fixed`, `structured`, `ord` from 0) and
   embed the distinct inputs of all of them in one `embed.embed_documents` call (96 texts per
   Bedrock request). The embedding input is `"<title>\n\n<chunk>"` (a chunk alone often lacks
   its subject's name); `chunks.text` stores the chunk alone, which is what keyword search and
   citations see. A ~90-word HotpotQA paragraph is the same single chunk under both strategies,
   so it is embedded once.
5. Per document, one transaction. **Insert** (new source): `documents` row + its chunks ->
   `inserted`. **Update** (known source, new hash): `UPDATE` title, doc_type, text, metadata,
   content_hash, `version = version + 1`; `DELETE` its chunks; `INSERT` the new ones ->
   `updated`. Embedding happens before any `BEGIN`, so a transaction never waits on Bedrock.

- **Delete**: `DELETE FROM documents WHERE id = :id RETURNING id`; the chunks go with it
  (cascade). `False` if the id is unknown.
- **Concurrent ingests** (up to 2 Lambdas on different shards): the document `INSERT` has
  `ON CONFLICT DO NOTHING`. If another transaction stored the same source or the same text after
  the checks, Postgres waits for it, inserts nothing, and that document goes to the second round,
  where the checks return `unchanged` or `duplicate`. An update that collides on `content_hash`
  fails with a unique violation, rolls back and raises: loud, nothing half-written.

All SQL goes through `db.py`, parameterized (`:name`). Vectors are sent as JSON text and cast
(`CAST(:embedding AS halfvec(1024))`), metadata as `CAST(:metadata AS jsonb)`. Single statements
use `db.run`: a statement whose connection died is retried once on a new connection, so it must be
idempotent. Multi-statement writes use `with db.transaction() as conn:` and only `conn.run`
inside: a dead connection is replaced only before `BEGIN`, nothing inside is retried, success
commits, any error rolls back and re-raises. A failed `upsert_many` therefore leaves only
complete documents behind (those written before the error), and the Lambda's async retry reruns
the shard, where step 2 skips what was already stored. The shard is embedded before its first
write, so a Bedrock failure re-embeds the whole shard on the retry.

### Measured (2026-10-25, production Aurora, `test:` rows deleted afterwards)

Writes (with Titan, one embedding request per document; the database part is unchanged):

| | from the laptop (88 ms round trip) | in-region (CodeBuild `investigation-jobs`) |
|---|---|---|
| insert, ~90-word doc | 1.94 s (Titan 0.23 s, the rest round trips) | 0.137 s (Titan 0.108 s, database 0.03 s) |
| rerun (`unchanged`) | 0.26 s, 0 Bedrock calls | 2 ms, 0 Bedrock calls |

A parameterized `conn.run` measured three round trips (pg8000's extended query protocol) and a
plain one (`BEGIN`, `COMMIT`) one, so an insert is ~18 round trips; the statements themselves,
including the HNSW insert, take a few ms. Only the round-trip time differs between the two
columns (88 ms vs 0.8 ms). The database part of a 500-document shard is ~15 s in-region, a rerun
of it ~1 s: well inside the 15-minute ingest timeout, so one INSERT per chunk stays.

Embedding with Cohere Embed V4: 96 HotpotQA documents per request, 2.2-3.2 s; a shard of 500
needs ~6 requests, bound by the 20 requests/min of the `eu.*` pool (ADR 0022). From the laptop,
`upsert_many` of four `test:` documents (A, A's text under another source, B, A's source with new
text) returned `inserted, duplicate, inserted, updated` with one embedding request per round;
the rerun took 0.52 s with 0 Bedrock calls.

## Changing the schema

Edit `sql/schema.sql` and merge: the deploy applies it. Every statement must be idempotent, and
`CREATE TABLE IF NOT EXISTS` never changes an existing table, so add columns with
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` below the table. The file runs in one call (simple
query protocol), as one implicit transaction: a broken statement applies nothing. New tables get
the `app` grants because the `GRANT ... ON ALL TABLES` at the end runs on every apply.
