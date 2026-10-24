-- The whole database schema (llm-wiki/03-data-model.md). Applied as the master user by the
-- Schema custom resource (engine.handlers.schema) on the first deploy and on every deploy that
-- changes this file, in one call and one transaction, so every statement must be idempotent.
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

-- Built while the table is empty, then maintained on every insert: building it over a loaded
-- table inside a deploy would hold the custom resource for minutes.
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

-- The role the Lambdas and jobs log in as, by IAM token (rds_iam), with data access only: it
-- cannot create, alter or drop tables, so an injected statement cannot destroy the schema.
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app') THEN
        CREATE ROLE app LOGIN;
    END IF;
END
$$;
GRANT rds_iam TO app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO app;
