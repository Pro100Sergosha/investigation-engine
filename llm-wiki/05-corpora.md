---
title: Corpora
status: current
last_updated: 2026-10-25
owner: Pro100Sergosha
---

# 05 Corpora

Two corpora ([ADR 0006](adr/0006-hotpotqa-plus-synthetic-acme-corpus.md)): HotpotQA for scale and
gold labels, the synthetic Acme corpus for investigation questions and planted contradictions.

## HotpotQA (bulk)

**Source.** HotpotQA distractor dev set, `hotpot_dev_distractor_v1.json` (46,320,117 bytes,
SHA256 `4e9ecb5c...7104ea`), CC BY-SA 4.0. URL from the
[HotpotQA README](https://github.com/hotpotqa/hotpot):
`http://curtis.ml.cmu.edu/datasets/hotpot/hotpot_dev_distractor_v1.json`. The CMU host was
unreachable on 2026-10-24, so `scripts/dataset.py` falls back to the Wayback Machine snapshot
`https://web.archive.org/web/20260310132809id_/<official URL>` (`id_` = raw bytes, no Wayback
banner). Either way the SHA256 is checked, so the counts below are reproducible. Only the dev split
is used: the train split is not needed for 50k (see the counts).

Each row: `{_id, question, answer, type, level, supporting_facts: [[title, sent_idx]],
context: [[title, [sentences]]]}`, 10 paragraphs per question (a few have fewer).

**Paragraph -> document.** Each context paragraph becomes a `ParsedDoc`:
`source = "hotpotqa:<title>"`, `title`, `doc_type = "jsonl"`, `metadata = {"dataset": "hotpotqa"}`,
`text = "".join(sentences).strip()`. HotpotQA sentences after the first carry their own leading
space (230,827 of 232,787 such sentences in dev); the 1,960 that do not are cuts the sentence
splitter made inside a sentence (`'... album "Lucifer'`, `'", which peaked ...'`). `"".join`
rebuilds the original Wikipedia paragraph; `" ".join` would insert spaces inside quotes and
domain names (`990WBOB. com`).

**Dedup**, in file order, no randomness:

1. Empty text -> skipped, counted as `empty`.
2. A `source` already kept with the same `engine.index.content_hash` -> `exact_duplicates`.
3. A `source` already kept with a *different* text -> `title_conflicts`; the first text seen wins.
   The source must be unique because an update is keyed by source: a second text would silently
   replace the first.
4. Same text as a kept document under another title -> `exact_duplicates`. `ingest` dedups by the
   same `content_hash`, so it would drop it anyway.

**Real counts** (measured on the checked file; `make dataset-stats` prints the same):

| | |
|---|---|
| questions | 7,405 (bridge 5,918, comparison 1,487) |
| paragraphs seen | 73,700 |
| **unique documents** | **66,555** (>= 50,000: `meets_50k: true`) |
| exact duplicates | 7,145 (of which 36 are the same text under a different title) |
| title conflicts | 0 |
| empty | 0 |
| shards | 134 (133 x 500 + 55) |
| text length | mean 532 characters, max 8,237 |

All 13,783 distinct supporting titles survive dedup, so every gold label points at an indexed
document.

**S3 layout** (bucket from `--bucket`):

| Key | Content | Triggers |
|---|---|---|
| `jobs/dataset/stats.json` | the stats above | nothing |
| `jobs/dataset/questions.jsonl` | one line per question: `_id, question, answer, type, level, supporting_titles` (gold, as `hotpotqa:<title>` sources, deduped) | nothing |
| `bulk/hotpotqa/shard-00000.jsonl` ... | 500 `ParsedDoc` per line-delimited file, keys `source, title, doc_type, text, metadata` (`read_jsonl` contract) | `ingest` |

The labels are uploaded before the shards. Shard names are deterministic, so a rerun overwrites the
same keys; `ingest` dedups by hash and updates by source, so a rerun does not duplicate data.

**Run** (never on the laptop, [ADR 0018](adr/0018-cloud-only-ingestion-and-jobs.md)):

```
aws codebuild start-build --project-name investigation-jobs \
  --environment-variables-override name=TARGET,value=dataset
```

`TARGET=dataset-stats` downloads and prints the stats without uploading (`--dry-run`).

**Load** (shards -> `ingest` -> Aurora). Each shard is one `ingest` invocation; at most 2 run at
once. `ingest` calls `index.upsert_many` with the whole shard: dedup checks for all 500
documents, then one Cohere Embed V4 request per 96 distinct chunk inputs, then one transaction
per document ([ADR 0022](adr/0022-cohere-embed-v4-batched.md)). Numbers:

| | |
|---|---|
| tokens per document | ~158 ("<title>\n\n<text>"; 96 documents = 15,180 tokens) |
| corpus | ~10.5-11M tokens, ~$1.3; ~11M of the pool's 16.2M tokens/day |
| requests | ~700 at 96 texts, 2.2-3.2 s each; the `eu.*` pool allows 20/min and 300k tokens/min |
| expected time | ~35-40 min for the corpus, bound by the pool, not by the database (~0.03 s per document) |

History: the first load (2026-10-25, Titan V2, one request per chunk, 5 workers) stalled at
1,853 documents: Titan throttled beyond ~1 request/s and Lambda dropped the shards after its
retries. Those documents carry Titan vectors, which do not compare with Cohere's: they must be
deleted and the corpus reloaded with Cohere ([14 Known gaps](14-known-gaps.md)). A shard Lambda gives up on now lands in the
`IngestFailures` queue (`make redrive-ingest` reruns it); rerunning `dataset` also works, since
`ingest` skips what is stored.

## Acme (synthetic)

A fictional European payment processor, "Acme Payments", January-April 2026, for the questions
HotpotQA cannot ask: investigations across documents, planted contradictions, missing facts
([ADR 0026](adr/0026-acme-corpus-spec-driven-generation.md)). Six services (`payments-api`,
`ledger`, `card-gateway`, `fraud-scorer`, `notifications`, `merchant-portal`), 14 people, the
acquiring bank NorthBank. The centre is the task's own example: the card payment outage of
**2026-03-12** (`CHG-1042` cut the ledger connection pool from 200 to 20), told by a postmortem,
the change record, a preliminary report blaming NorthBank, a webhook backlog report, an
emergency change, a follow-up change, a runbook and the public status page, which disagree.

| | |
|---|---|
| documents | **64**: 11 incident reports (PDF), 28 change records (Markdown), 12 runbooks (DOCX), 13 status page entries (HTML); routine changes and maintenance notices are filler so retrieval is not trivial |
| planted contradictions | **14** (start and end time, root cause, merchant and webhook counts, approver, deploy times, durations, a stale runbook timeout, rolled back or not, ...) |
| gaps | **6** facts absent from every document (lost revenue, SLA credits, ...) |
| questions | **42**: 15 multi_doc, 3 multi_hop, 12 contradictory, 6 unanswerable, 6 simple |
| generation cost | 95 Haiku calls over four runs (64 documents, 22 retries, 9 after spec fixes), ~99k input + ~31k output tokens, **$0.28** ([ADR 0026](adr/0026-acme-corpus-spec-driven-generation.md)) |

**Files** (`data/acme/`):

| Path | What |
|---|---|
| `spec.json` | the hand-written scenario: company, documents (id, date, services, title, summary, required facts, references), contradictions, gaps, questions. The single source of truth |
| `files/acme-<kind>-<id>.<ext>` | the corpus, e.g. `acme-inc-301.pdf`, `acme-chg-1042.md`, `acme-rb-03.docx`, `acme-sts-301.html` |
| `.gitattributes` | `files/** -text`: the files are kept byte for byte (the PDFs are pure ASCII; CRLF on a Windows checkout would break their xref offsets) |
| `GROUND_TRUTH.md` | generated from the spec: documents table, every contradiction with its values, every gap, question -> answer -> gold documents |
| `questions.jsonl` | generated from the spec, the eval runner's input: `{"id": "acme-001", "question", "type", "answer" (null if unanswerable), "gold_sources": ["upload:acme-inc-301.pdf", ...]}`; a contradictory question's gold sources are the conflicting documents |

**How it is generated** (`make acme`, CodeBuild `TARGET=acme`, `scripts/gen_acme.py`):
1. `validate(spec)`: ids `INC|CHG|RB|STS-<digits>` unique, known services and references, each
   contradiction value is a required fact of its document and the values differ, gold
   documents exist, unanswerable questions have neither gold nor answer.
2. Labels written from the spec (`make acme-labels` does only this, no AWS).
3. Per document, one Haiku call through `llm.converse` (cached in Postgres): a system prompt with
   the company, the rules (copy each required fact exactly, add no new times, numbers, people,
   ids or causes, never mention the gaps) and the kind's shape; a user prompt with the document's
   spec. 7 s between uncached calls (Haiku: 10 requests/min, shared).
4. Render: title, `Document: <id>`, `Date:` and `Services: a, b` lines from the spec, then the
   model's body (`##` headings, paragraphs, bullets), sanitized to ASCII. Markdown and HTML with
   the standard library, DOCX with python-docx (title in the Title style and core properties,
   creation date), PDF with a small hand-written writer (Helvetica, title and creation date in
   the Info dictionary).
5. **Check:** parse the file with `engine.parsers.parse` and require every fact and every
   referenced id in the extracted text (case- and whitespace-insensitive); the words listed for
   the gaps must be absent. One retry with the problems named; then the job fails listing the
   documents.
6. Upload `files/`, the labels and the spec to `s3://$BUCKET/jobs/acme/` (inert prefix). The
   files are downloaded and committed; tests re-check every committed file against the spec.
7. Read the files: the check proves the planted facts are present, not that nothing else was
   invented. The first run's review found invented times in INC-306 and STS-401 and a leaked
   gap in INC-201; their summaries now pin them.

**Load:** `make acme-load` (CodeBuild `TARGET=acme-load`) copies `data/acme/files/` to
`s3://$BUCKET/uploads/`: `ingest` parses and indexes each file like a UI upload, with
`source = upload:<file name>`, the form `gold_sources` uses. Re-running it is harmless (same
content hash -> skipped).
