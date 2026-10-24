---
title: HotpotQA for scale and labels, synthetic Acme corpus for investigation
status: accepted
date: 2026-10-24
supersedes: none
superseded_by: none
---

# ADR 0006: HotpotQA for scale and labels, synthetic Acme corpus for investigation

## Context

The task requires 50,000+ documents, at least 3 file formats, cross-document links, preserved source
identity, incomplete and contradictory data, and a repeatable evaluation with retrieval metrics.
No single public dataset has all of that.

## Decision

Two corpora:
- **HotpotQA `distractor` validation** (7,405 questions x 10 paragraphs), deduplicated by
  title + text, for scale and free gold labels (supporting titles/sentences give Recall@K, MRR and
  citation accuracy). If unique paragraphs are below 50k, add part of `train`. The subset script uses
  a fixed seed and is committed.
- **Synthetic "Acme Payments"**: 60-100 incident reports (PDF), change logs (Markdown), runbooks
  (DOCX) and status pages (HTML), generated once by an LLM and committed, with planted contradictions
  and gaps listed in `data/acme/GROUND_TRUTH.md`.

## Consequences

Scale and labels come for free; the investigation-style questions (the task's own example is a
payment outage) and contradictions exist because we planted them, so detection can be measured.
The cost: Acme is synthetic and small, which the evaluation report must say; HotpotQA paragraphs
are already short, so the chunking comparison is weak on it and is done on Acme.

## Alternatives considered

**danluu/post-mortems** as a real incident corpus: dropped for time.

**Only HotpotQA**: no contradictions, no multiple formats.
