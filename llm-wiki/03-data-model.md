---
title: Data model
status: current
last_updated: 2026-10-24
owner: Pro100Sergosha
---

# 03 Data model

One Postgres database, `investigation`, on Aurora Serverless v2 (PostgreSQL 17.9 with pgvector),
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
| `embedding` | `halfvec(1024)` | Titan Text Embeddings V2, 1024 dimensions, half precision: half the storage and index size of `vector`; pgvector's HNSW indexes it directly |

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
| `chunks_embedding_idx`, HNSW on `embedding halfvec_cosine_ops` | dense search by cosine distance (`<=>`) |
| unique `(document_id, strategy, ord)` | chunks of one document, the cascade delete, and the re-insert on update. It starts with `document_id`, so a separate index on `document_id` alone would be redundant |
| unique `source`, unique `content_hash` | update-by-source and exact dedup |

The HNSW index is created while the table is empty and then maintained on every insert: building
it over a loaded table inside a deploy would hold the schema custom resource for minutes.

## Write paths

- **Insert**: a new source with an unseen `content_hash` -> one `documents` row + its chunks, in
  one transaction.
- **Update**: same `source`, new `content_hash` -> `version + 1`, new `text`/`content_hash`, old
  chunks deleted and new ones inserted, in one transaction. Same `content_hash` as any existing
  document -> skipped as a duplicate.
- **Delete**: `DELETE FROM documents WHERE id = :id`; the chunks go with it (cascade).

All SQL goes through `db.py` (`db.run(sql, **params)`), parameterized (`:name`), with vectors
sent as text and cast (`'[...]'::halfvec`). Writes must be idempotent (upsert by `source`): a
statement whose connection died is retried once on a new connection.

## Changing the schema

Edit `sql/schema.sql` and merge: the deploy applies it. Every statement must be idempotent, and
`CREATE TABLE IF NOT EXISTS` never changes an existing table, so add columns with
`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` below the table. The file runs in one call (simple
query protocol), as one implicit transaction: a broken statement applies nothing. New tables get
the `app` grants because the `GRANT ... ON ALL TABLES` at the end runs on every apply.
