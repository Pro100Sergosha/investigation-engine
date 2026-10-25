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

Arrives in wave 3 (`acme` job, `scripts/gen_acme.py`, `data/acme/GROUND_TRUTH.md`).
