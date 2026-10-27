---
title: Acme corpus generated from a hand-written spec, every fact checked verbatim in the parsed file
status: accepted
date: 2026-10-26
supersedes: none
superseded_by: none
---

# ADR 0026: Acme corpus generated from a hand-written spec, every fact checked verbatim in the parsed file

## Context

ADR 0006 adds a small synthetic "Acme Payments" corpus to HotpotQA: incident reports, change
logs, runbooks and status pages in four formats, with planted contradictions and gaps, so that
multi-document, contradictory and unanswerable questions exist and can be scored. The scores are
only as good as the labels: if a generated document leaves out a planted value, or invents one
that was meant to be missing, the evaluation measures the generator instead of the system. The
generation also has to run in CodeBuild (ADR 0018), on Haiku limited to 10 requests/min shared
with the agent and the eval, and be explainable line by line.

## Decision

- **The scenario is hand-written, the prose is not.** `data/acme/spec.json` holds the company
  (services, people), 64 documents (id, date, services, title, summary, required facts,
  references to other documents by id), 14 planted contradictions (which documents disagree,
  with which values), 6 gaps (facts absent everywhere) and 42 questions. Haiku writes each
  document's body from its spec entry; it never decides a fact.
- **Ground-truth check on the parsed file.** Each document is rendered, then read back with
  `engine.parsers.parse`, the function `ingest` uses. Every required fact (its facts plus the ids
  it references) must appear in the extracted text, case- and whitespace-insensitive (PDF line
  wrapping, "Approved by" at a sentence start); the words listed for each gap must not appear.
  On a miss there is one retry that names what was wrong; still wrong -> the job fails listing
  the documents. `validate` checks the spec itself: unique well-formed ids, known services and
  references, each contradiction value is a required fact of its document and the values
  differ, every gold document exists, unanswerable questions have no gold and no answer.
- **Labels are derived, not written twice.** `GROUND_TRUTH.md` and `questions.jsonl` are
  generated from the spec (`make acme-labels`); a contradictory question's answer and gold
  documents come from the contradiction it names. A test fails if the committed labels differ
  from the spec, and another if a committed file no longer holds its facts.
- **Formats:** incident reports PDF, change records Markdown, runbooks DOCX, status pages HTML.
  Title, document id, date and the `Services:` line are rendered from the spec where the parser
  finds them (first heading or PDF/DOCX metadata title, PDF/DOCX creation date). Text is
  sanitized to ASCII first, so every format carries the same characters.
- **PDF is written by hand** (~50 lines in `gen_acme.py`: Helvetica lines wrapped with
  `textwrap`, pages, xref table), like the test helper in `tests/test_parsers.py`. No new
  dependency.
- **Generated once, committed.** `make acme` (CodeBuild) writes to `s3://$BUCKET/jobs/acme/`
  (inert); the files are downloaded and committed under `data/acme/files/`. `make acme-load`
  (CodeBuild) copies them to `uploads/`, so `ingest` indexes them exactly like UI uploads, with
  `source = upload:<file name>`, the form the gold labels use.
- **Pacing and cost.** One Haiku call per document (plus retries), 7 s between uncached calls;
  `llm.converse` caches by prompt, so a rerun after a fix costs only the changed documents.

## Consequences

The labels cannot drift from the documents: a planted value that is not in the parsed file fails
the job, and a spec edit that is not reflected in the labels fails the tests. The ingest path is
exercised for four formats by the same files the evaluation uses. The corpus is reproducible
without the LLM (the committed files) and regenerable with it.
The costs: the spec is ~600 lines of hand-written JSON, and its realism is limited by what one
person wrote in an afternoon; 64 documents is small, which the evaluation report must say. The
check proves presence of the planted facts, not absence of everything else: the model can still
invent a detail that accidentally contradicts another document (the prompt forbids new times,
numbers, people and causes, and the files were read after generation, but nothing mechanical
enforces it), and gaps without listed words are only enforced by the prompt. Reading the first
run found exactly that: INC-306 and STS-401 invented times that contradicted INC-301 and
INC-401, and INC-201 gave a model-level reason (gap G03) and the report date as the deploy date;
their summaries now pin the times and the gap, and the job was rerun. The hand-written PDF has no
headings in its extracted text and approximate line wrapping. A Haiku throttle falls back to
gpt-oss-120b (ADR 0023), so a document may be written by the other model; the job logs the model
counts (all 64 final documents were written by Haiku).

Measured cost (four `acme` runs on 2026-10-25/26, reruns served from `llm_cache`): 95 uncached
Haiku calls (64 documents, 22 retries, 9 calls after spec fixes), 98,975 input + 30,953 output
tokens, **$0.28**; ~15 minutes for the first run, ~2 minutes for a cached rerun. 19 of 64
documents needed the one retry (a fact paraphrased: "Approved by" placement, a time written in
timeline form, a gap word such as "revenue"); three availability reports failed twice until
their facts took the bullet form the model writes.

## Alternatives considered

**Fully LLM-invented corpus** (ask the model for incidents, contradictions and questions):
fastest to start, but the ground truth would be whatever the model says it planted, unchecked;
contradictions and gaps would have to be found by reading every document.

**Real post-mortems** (danluu/post-mortems, ADR 0006): realistic, but no planted contradictions,
no gold labels, one format (web pages), and licensing per source.

**Templates without an LLM** (fill-in-the-blank documents): exact and free, but every document of
a kind would read alike, which makes retrieval and the chunking comparison unrealistically easy.

**fpdf2 for the PDFs**: a real layout engine with headings that look typeset, but it pulls Pillow,
fontTools and defusedxml for what ~50 lines of standard library do here; worth it only if the
files must look professionally typeset.

## Update 2026-10-27

"Hand-written" above means a fixed spec written up front, not generated by the `acme` job at
run time. The spec itself was written by a Claude Code subagent in wave 3 (#28), not by the
author, so "what one person wrote in an afternoon" is wrong: its realism is limited by one model
session, and the author's part is the reading of the generated files (AI_USAGE.md).
