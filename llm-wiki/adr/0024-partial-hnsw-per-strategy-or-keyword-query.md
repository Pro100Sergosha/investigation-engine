---
title: A partial HNSW index per chunking strategy, and OR semantics for keyword search
status: accepted
date: 2026-10-25
supersedes: none
superseded_by: none
---

# ADR 0024: A partial HNSW index per chunking strategy, and OR semantics for keyword search

## Context

Both chunking strategies live in one `chunks` table, and every search filters on `strategy`
(ADR 0003, PLAN.md section 4 compares them). Two defaults break that search silently:

- **Filtered HNSW returns too few rows.** pgvector scans the HNSW graph first and applies the
  `WHERE` filter afterwards; one scan yields at most `hnsw.ef_search` rows (default 40). With one
  graph over both strategies about half of those rows are filtered out. Measured on pgvector
  0.8.1 (the installed version) with 4,000 rows split evenly: `WHERE strategy = 'fixed' ORDER BY
  embedding <=> q LIMIT 40` returned **21** rows, with no error.
- **Postgres full text ANDs every word.** `plainto_tsquery` and `websearch_to_tsquery` require
  all terms, so a 12-word multi-hop question matches almost no chunk and the keyword half of the
  hybrid search returns nothing.

## Decision

- `sql/schema.sql` drops the shared HNSW index and creates one **partial** HNSW index per
  strategy (`... WHERE strategy = 'fixed'`, `... WHERE strategy = 'structured'`). The filter is
  the index itself, so a scan returns 40 rows of the right strategy. The planner picks the
  partial index for `WHERE strategy = :strategy` because pg8000 sends unnamed statements, which
  Postgres plans with the actual parameter value (checked with `EXPLAIN` through pg8000).
- Keyword search builds an OR query from the user text inside SQL:
  `replace(plainto_tsquery('english', :q)::text, ' & ', ' | ')::tsquery`, ranked by
  `ts_rank_cd`. The text is still a bound parameter; only Postgres' own lexeme output is edited.
  A query of stop words gives an empty query that matches nothing, without an error.

## Consequences

- Dense search gets its full candidate list, with no session state. Each row is in exactly one
  partial index, so insert cost and index size equal the single index.
- A dense query without a strategy filter could no longer use an index. Nothing issues one.
- A third strategy needs a third index in `schema.sql`.
- Recall within each graph still depends on `ef_search = 40` while asking for 40 rows. On random
  1024-d vectors (the worst case) recall@40 against the exact scan was 0.625. Real embeddings
  cluster and do better, but this has not been measured at scale yet.
- OR queries match many more chunks; `ts_rank_cd` then ranks every matching chunk before the
  `LIMIT`, so the cost grows with how common the question's words are. Not measured at scale
  yet (the tables are empty).

## Alternatives considered

**Iterative index scans** (`SET hnsw.iterative_scan = strict_order`, pgvector >= 0.8): also
returned 40 rows in the same test. It is a session setting: `db.run` reuses one connection and
silently opens a new one after a failure, which would drop the setting and bring back the bug, so
it would have to be sent before every query (an extra round trip) or set with `ALTER ROLE`.
The right call if search ever filters on a column with many values (dates, sources).

**Higher `hnsw.ef_search`**: lowers the chance of a short result but never removes it, and it is
the same per-session setting.

**`to_tsquery` from the stemmed words joined with `|`**: equivalent, but stems the words twice
and needs quoting of the lexemes in Python or SQL. The `replace` keeps it in one expression.
