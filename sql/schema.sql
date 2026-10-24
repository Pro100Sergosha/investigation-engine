-- The whole database schema (llm-wiki/03-data-model.md). Applied by the Schema custom resource
-- (scripts/schema.py) on the first deploy and on every deploy that changes this file, and by
-- hand with `make schema`, so every statement must be idempotent (IF NOT EXISTS).
-- The Data API runs one statement per call: statements are split on ';', so a ';' may appear
-- only at the end of a statement (no functions, no string literals containing it), and
-- comments go on their own lines.
-- Changing an existing table needs an ALTER TABLE ... ADD COLUMN IF NOT EXISTS below:
-- CREATE TABLE IF NOT EXISTS never changes a table that already exists.

CREATE EXTENSION IF NOT EXISTS vector;

-- One row per document. `source` is its identity (upload:<filename>, hotpotqa:<title>);
-- re-uploading the same source with new content bumps `version` and replaces its chunks.
-- `content_hash` is engine.index.content_hash(text): exact dedup across all sources.
-- `text` is the full parsed text, served by GET /documents/{id} and get_document(): it cannot
-- be rebuilt exactly from chunks (fixed chunks overlap and collapse whitespace, structured
-- chunks repeat headings and drop trailing ones).
CREATE TABLE IF NOT EXISTS documents (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source text NOT NULL UNIQUE,
    title text NOT NULL,
    doc_type text NOT NULL,
    content_hash text NOT NULL UNIQUE,
    version int NOT NULL DEFAULT 1,
    text text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);

-- Chunks of every strategy live side by side; search filters on `strategy`.
-- `tsv` is computed by Postgres, so keyword search can never drift from the text.
-- `embedding` is Titan Text Embeddings V2 at 1024 dimensions, stored as half precision.
CREATE TABLE IF NOT EXISTS chunks (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id bigint NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    strategy text NOT NULL,
    ord int NOT NULL,
    text text NOT NULL,
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    embedding halfvec(1024),
    UNIQUE (document_id, strategy, ord)
);

CREATE INDEX IF NOT EXISTS chunks_tsv_idx ON chunks USING gin (tsv);

-- Built while the table is empty, then maintained on every insert: a CREATE INDEX over a
-- loaded table would exceed the Data API's 45 s statement limit.
CREATE INDEX IF NOT EXISTS chunks_embedding_idx ON chunks USING hnsw (embedding halfvec_cosine_ops);

-- No separate index on chunks (document_id): the UNIQUE (document_id, strategy, ord) index
-- starts with it and already serves lookups by document and the cascade delete.

-- LLM responses by hash of (model, prompt): reruns of the evaluation cost nothing.
CREATE TABLE IF NOT EXISTS llm_cache (
    prompt_hash text PRIMARY KEY,
    model text NOT NULL,
    response jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
