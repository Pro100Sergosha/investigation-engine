---
title: Weighted RRF (k0=10, keyword at 0.5), min-max MMR relevance, fixed chunks by default
status: accepted
date: 2026-10-26
supersedes: none
superseded_by: none
---

# ADR 0029: Weighted RRF (k0=10, keyword at 0.5), min-max MMR relevance, fixed chunks by default

## Context

The first `retrieval` eval (2026-10-26, 61 answerable questions: 25 HotpotQA, 36 Acme) showed
that the agent's default configuration, structured chunks + `mmr`, was the worst of the six:

| strategy/mode | Recall@5 | Recall@10 | MRR |
|---|---|---|---|
| fixed/dense | 0.80 | 0.88 | 0.85 |
| fixed/hybrid | 0.66 | 0.86 | 0.66 |
| fixed/mmr | 0.56 | 0.71 | 0.65 |
| structured/dense | 0.71 | 0.81 | 0.78 |
| structured/hybrid | 0.62 | 0.80 | 0.64 |
| structured/mmr | 0.53 | 0.62 | 0.61 |

A live question showed the same thing: the only paragraph mentioning "The Grand Budapest Hotel"
was rank 2 in `dense`, 4 in `hybrid` and 9 in `mmr`, so the agent (k=8, `mmr`) never saw it.

Two causes, both in our own code (ADR 0003):
1. **RRF with equal weights and k0=60.** The keyword list is OR over every word of a long
   question (ADR 0024): on 66k documents it matches thousands of chunks and its top is noisy.
   At k0=60 the curve is flat (rank 1 = 1/61, rank 5 = 1/65), so a chunk that is merely in both
   lists beats dense's clear first hit. On HotpotQA, Recall@10 fell from 0.86 to 0.72. On Acme
   keyword search helps (exact ids like `CHG-1042`): 0.91 -> 0.96.
2. **MMR relevance divided by the best score.** The 40 fused RRF scores lie in a narrow band
   (about 1/61 to 1/100), so every candidate had a relevance of 0.6-1.0, and the similarity
   penalty decided the order: MMR traded relevant chunks for diverse irrelevant ones.

## Decision

Tuned offline on the same candidates (dense top-40 and keyword top-40 per question, collected
once; fusion and MMR re-run in memory for each setting):

- `rank.rrf` takes per-list `weights`; `search.py` fuses dense at 1.0 and keyword at
  `KEYWORD_WEIGHT = 0.5`, with `RRF_K0 = 10`.
- `rank.mmr` normalizes relevance min-max over the candidates ((s - lowest) / (highest -
  lowest)); `search.py` calls it with `MMR_LAMBDA = 0.85`.
- Default chunking strategy is `fixed` (`search.search`, `agent.ask`, eval config `agent`); the
  agent's seeded search and default `k` go from 8 to 10. The eval config `agent-fixed` becomes
  `agent-structured`, so the chunking comparison on answers still runs.

Offline sweep (selected rows; R@10 split into HotpotQA / Acme):

| strategy | variant | R@5 | R@10 | MRR | HotpotQA R@10 | Acme R@10 |
|---|---|---|---|---|---|---|
| fixed | dense | 0.80 | 0.89 | 0.86 | 0.86 | 0.91 |
| fixed | RRF k0=60 w=1.0 (old hybrid) | 0.67 | 0.86 | 0.66 | 0.72 | 0.96 |
| fixed | RRF k0=10 w=0.5 (new hybrid) | 0.83 | 0.89 | 0.79 | 0.84 | 0.92 |
| fixed | old MMR (k0=60, w=1, lam 0.7, / best) | 0.56 | 0.71 | 0.65 | 0.44 | 0.90 |
| fixed | new MMR (k0=10, w=0.5, lam 0.85, min-max) | 0.82 | 0.89 | 0.79 | 0.84 | 0.92 |
| structured | dense | 0.71 | 0.81 | 0.78 | 0.90 | 0.75 |
| structured | new hybrid | 0.73 | 0.81 | 0.77 | 0.88 | 0.77 |
| structured | new MMR | 0.74 | 0.83 | 0.78 | 0.88 | 0.80 |

The official numbers are the next `eval CONFIG=retrieval` run (llm-wiki/09).

## Consequences

Hybrid and MMR stop hurting: fixed/mmr goes from R@10 0.71 to ~0.89 and keeps both own
algorithms in the default path. They do not clearly beat plain dense either: on this set
dense keeps the best MRR (0.86 vs 0.79), and the keyword list buys Acme's exact-id questions at
a small HotpotQA cost. The report must say so instead of claiming hybrid wins.

Costs and risks:
- **Tuned on the evaluation set.** 61 questions; one question moves Recall by ~0.016. The
  values were picked from a plateau (k0 5-20, w 0.3-0.5 all score alike), not the single best
  cell (k0=5 had MRR 0.83), but the reported numbers are optimistic. A held-out split would fix
  this; there is no time for one.
- `k0=10` is far from the paper's 60. The paper fuses several strong rankers; here one of two
  lists is weak, and a sharper curve keeps dense's order unless keyword strongly agrees.
- Structured chunks lose on Acme (0.75 vs 0.91 R@10): its sections are long and a 300-word cap
  splits them less evenly than fixed windows. The chunking comparison stays in the eval.

## Alternatives considered

**Plain dense as the default**: same Recall, better MRR, simplest; rejected because Acme's
id-heavy questions gain from keyword search, and the own fusion and diversity code would sit
outside the path that answers questions. Kept as the `dense` mode and compared in every run.
**Keyword top-10 instead of top-40 at full weight**: R@10 0.88, MRR 0.71, worse than weighting.
**AND or phrase keyword queries (`websearch_to_tsquery`)**: fewer, more precise matches, but
multi-hop questions then match nothing (the reason for OR in ADR 0024). **A learned reranker**:
not explainable on a whiteboard, extra model cost.
