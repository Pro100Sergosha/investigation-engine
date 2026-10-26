# Evaluation report

How well the deployed Investigation Engine retrieves, answers, cites, abstains and flags
contradictions, measured on 2026-10-26: methodology, metrics, results and where it fails.

Every number here is recomputed from the committed result files:
`eval/results/{retrieval,agent,agent-structured,single-shot}.json`, and for the earlier prompt
`eval/results/agent.json` at commit `5cfbd5d` (`git show 5cfbd5d:eval/results/agent.json`).
Each answer record keeps the agent's `trace` (searches with chunk ids, documents read, LLM calls,
reprompts, citations dropped by the validator); the failure analysis reads those traces. The
runner is `eval/run.py`, the metric functions are `eval/metrics.py`, and the design decisions are in
[ADR 0027](llm-wiki/adr/0027-eval-runner-retrieval-sweep-qwen-judge.md). The living description
of the evaluation is [llm-wiki/09](llm-wiki/09-evaluation.md).

## Summary

- **Retrieval.** With fixed chunks, Recall@10 is 0.89 in all three search modes. Structured chunks
  reach 0.81-0.83. Hybrid and MMR do not beat plain dense search: they have the same Recall@10 and
  a lower MRR (0.79 vs 0.86). The fusion and MMR parameters were tuned on this same question set,
  so these numbers are optimistic.
- **Answers (`agent`, current prompt).** Judge correctness 0.82 (50 of 61 answerable questions),
  citation precision 0.94, abstention P/R 0.77/0.91, contradiction P/R 1.00/0.67. The citation
  validator dropped no claim in any of the four runs.
- **The loop matters for multi-hop questions:** 0.87 vs 0.52 judge correctness against single-shot
  RAG with the same prompt. Of the 8 questions in that gap, 5 are comparison questions, where
  single-shot abstained on all six.
- **Weakest area: contradictions.** Judge correctness is 0.58. Four of the twelve contradictory
  questions are answered from one document, although in three of them the other document was in
  the first search's hits.
- **The measurement has its own problems.** The judge is a single model and gives different
  verdicts to answers with the same content. The cost column leaves out prompt-cache tokens. The
  set is small (one question moves a type's score by 0.04-0.09) and was used for tuning.

## 1. Methodology

### Corpus

The deployed index holds 66,619 documents:
- 66,555 unique HotpotQA paragraphs from the distractor dev set, deduplicated
  ([llm-wiki/05](llm-wiki/05-corpora.md));
- 64 synthetic "Acme Payments" documents: 11 incident reports (PDF), 28 change records
  (Markdown), 12 runbooks (DOCX) and 13 status page entries (HTML). They contain 14 planted
  contradictions and 6 facts that no document states
  ([ADR 0026](llm-wiki/adr/0026-acme-corpus-spec-driven-generation.md)).

The evaluation runs against the same Aurora index and the same `agent.ask` code that serve the
public URL. There is no separate test index.

### Questions

There are 72 questions, of which 61 are answerable. They come from two fixed files with the same
format: `eval/questions.jsonl` (HotpotQA) and `data/acme/questions.jsonl` (Acme).

| type | HotpotQA | Acme | total |
|---|---|---|---|
| `simple` | 5 | 6 | 11 |
| `multi_hop` | 20 (14 bridge, 6 comparison) | 3 | 23 |
| `multi_doc` | 0 | 15 | 15 |
| `contradictory` | 0 | 12 | 12 |
| `unanswerable` | 5 | 6 | 11 |
| total | 30 | 42 | 72 |

How each group was chosen:
- **HotpotQA `multi_hop`.** The dataset job writes 7,405 dev questions with their labels. These
  were sorted by `sha256(_id)`, and the first 14 `bridge` and the first 6 `comparison` questions
  were taken. The selection is deterministic and nobody hand-picked it. Text, answer and supporting
  titles are copied verbatim. The bridge/comparison split is not a field in the file. In this
  report, "comparison" means the six questions that compare two entities: `hp-5a85fc995542996432c5715f`,
  `hp-5ab296a6554299194fa93415`, `hp-5ae3d0bb5542990afbd1e1e5`, `hp-5a80caac554299260e20a161`,
  `hp-5a8da97c554299068b959d84` and `hp-5a81d54a55429903bc27b9d4`.
- **HotpotQA `simple` and `unanswerable`** (`hp-simple-1..5`, `hp-unanswerable-1..5`) were
  written by hand. A simple question asks one fact from one paragraph. An unanswerable question
  asks about an entity that has a paragraph in the corpus, but for a fact that the paragraph does
  not contain (a cost, a price, a birthplace, a length). Every entity name was checked against the
  HotpotQA dev file: it appears in exactly one paragraph, its own. So a simple question has exactly
  one gold document, and an unanswerable question cannot be answered from some other paragraph.
- **Acme questions** were written by hand in the corpus spec `data/acme/spec.json`, together with
  the documents. Each `contradictory` question targets one planted contradiction. Each Acme
  `unanswerable` question targets one gap. The `multi_doc` questions need two to four documents
  (cause plus fix, timeline, follow-up change plus runbook).

### Gold labels

- **HotpotQA questions** keep the dataset's answer and supporting titles as they are, noise
  included. For example, `hp-5a7e36815542995ed0d166d4` asks about WrestleMania IX but its gold
  paragraph is WrestleMania XXIV, and `hp-5a8ae0ae55429950cd6afbc2` has the gold answer
  "AeroflotRussian Airlines". Gold sources are document sources (`hotpotqa:<title>`), not
  database ids, because ids change on every reload.
- **Acme labels are derived from the spec**, not written twice (`make acme-labels`). A
  contradictory question's gold answer is generated from the contradiction it targets
  (`conflicting: 14:02 UTC (INC-301) vs 14:15 UTC (STS-301)`), and its gold sources are the
  conflicting documents. The generation job checks every planted value verbatim in the parsed
  file, so a label cannot point at a value that the indexed text lacks (ADR 0026).
- **Unanswerable questions** have the gold answer `null` and no gold sources. The runner rejects
  any other combination before it makes a single call.

### The judge

Correctness is decided by Qwen3-235B on Bedrock. The generator is Claude Haiku 4.5, so the judge
comes from a different model family. A Claude judge would be grading its own family's answers,
which is known to make a judge lenient. gpt-oss-120b was also rejected as the judge, because it is
the agent's fallback model and would sometimes grade its own answers (ADR 0027).

The judge receives the question, the gold answer, the system's status, its short answer, its
claims and its contradictions. Its rubric: an answer is correct when it gives the same fact as the
gold answer, and wording, formatting and extra correct detail do not matter. When the gold answer
starts with `conflicting:`, an answer is correct only if it reports the disagreement together with
the conflicting values. The judge replies with a JSON verdict `{"correct", "reason"}`. An
`insufficient` answer to an answerable question is counted as incorrect without a call. All four
answer runs had 0 judge failures.

### How a run works

Runs execute in the CodeBuild project `investigation-jobs` (`make eval CONFIG=<name>` ->
`python -m eval.run`), never on a laptop
([ADR 0018](llm-wiki/adr/0018-cloud-only-ingestion-and-jobs.md)). They call the deployed
Aurora index and Bedrock.

| config | what it runs | LLM |
|---|---|---|
| `retrieval` | each answerable question through `search.search(q, k=10)` in 2 chunking strategies (`fixed`, `structured`) x 3 modes (`dense`, `hybrid`, `mmr`) | none (one Cohere query embedding per question) |
| `agent` | `agent.ask`: fixed chunks, `mmr`, up to 6 steps (the production defaults, [ADR 0029](llm-wiki/adr/0029-weighted-rrf-min-max-mmr-fixed-chunks.md)) | Haiku, judge |
| `agent-structured` | the same with structured chunks | Haiku, judge |
| `single-shot` | `max_steps=1`: the seeded search and one forced `final_answer` (RAG without the loop) | Haiku, judge |

Haiku allows 10 requests/min, and each search embeds its query in a Cohere pool of 20
requests/min. After each question the runner sleeps
`max(0, max(6 s x uncached Haiku calls, 3 s x searches) - elapsed)`. This keeps a run from
silently falling back to gpt-oss. A failed search is retried twice after 20 s. Results go to S3
and reach the repository through a PR.

Two prompt versions appear in the results. Compare like with like:

| row in the tables | file | agent prompt | how it ran |
|---|---|---|---|
| `agent` | `eval/results/agent.json` | current (#32: one contradiction per conflict citing both sides, check every document on the event) | uncached, 167 of 167 LLM calls reached a model |
| `agent`, prompt of #31 | `eval/results/agent.json` at `5cfbd5d` | #31 | rerun mostly from `llm_cache`: 172 of 190 LLM calls were cache hits |
| `agent-structured` | `eval/results/agent-structured.json` | #31 | uncached, 177 of 177 |
| `single-shot` | `eval/results/single-shot.json` | #31 | 64 of 72 calls uncached, 8 cache hits |

### Reproducibility

The question files are fixed and committed, and so are the results and their traces. A rerun
with unchanged prompts is mostly served by `llm_cache` (Postgres, keyed by a hash of the prompt).
That makes it cheap, but it is not an exact replay, for three reasons:
- Near-tied search hits can swap places between runs. That changes the prompt, misses the cache
  and can change the answer (seen on `hp-5a7e36815542995ed0d166d4` and `hp-simple-4`, ADR 0027
  update).
- A cached rerun's cost and latency are not the system's. This is why the "prompt of #31" row
  shows $0.05 and a p50 of 0.7 s.
- Uncached calls are not deterministic either. Between the #31 and #32 runs,
  `hp-5a8c493e554299653c1aa020` flipped from correct to abstained because the model picked
  different sub-queries (section 4.4).

## 2. Metrics

These are the metrics as implemented. Each one is computed per question and then averaged over a
run. A mean skips `None` ("not applicable"). An exception from `ask` would be recorded as an error
and left out of every score. All four answer runs had 0 errors.

| metric | definition | computed over |
|---|---|---|
| Recall@5, Recall@10 | `metrics.recall_at_k`: share of the distinct gold sources found among the sources of the first k chunk hits. A document hit twice takes two positions | answerable questions (61), retrieval run |
| MRR | mean of `metrics.reciprocal_rank`: 1 / rank of the first chunk from a gold document, 0 if there is none in the 10 | same |
| EM | `metrics.exact_match` of the short answer (`Answer.answer`) vs the gold answer after SQuAD normalization (lowercase, strip punctuation, drop a/an/the, collapse spaces) | HotpotQA questions with a gold answer (25); Acme gold answers are sentences, so EM/F1 are `None` there |
| F1 | `metrics.f1`: token multiset overlap after the same normalization. If either side is "yes", "no" or "noanswer" and the two differ, F1 is 0 | same 25 |
| Judge correctness | Qwen3 verdict (section 1). An abstention on an answerable question is `false` without a call. No gold answer -> `None` | questions with a gold answer (61) |
| Citation precision | `metrics.citation_precision`: distinct sources of the cited chunks (claims and contradictions) that are gold, divided by all distinct cited sources. `None` when nothing is cited | answerable questions that cite something (57-61 per run) |
| Abstention P/R | predicted = status `insufficient`, actual = type `unanswerable` | all 72 |
| Contradiction P/R | predicted = status `conflicting`, actual = type `contradictory` | all 72 |
| Cost | uncached LLM calls only: `inputTokens` x input price + `outputTokens` x output price (Haiku `eu.*` $1.10/$5.50, `global.*` $1.00/$5.00, gpt-oss $0.15/$0.60, Qwen $0.22/$0.88 per 1M), judge included. **It leaves out prompt-cache tokens** (section 4.10) | answer runs |
| Latency p50/p95 | seconds of `agent.ask` per question (without the runner's pause), nearest-rank percentile | answer runs |
| Fallback share | share of answers with at least one LLM call not answered by Haiku (`eu.*` or `global.*`) | answer runs |

Citation precision compares documents, not facts. A citation to a correct paragraph that is not
on the gold list counts as a miss. For example, `hp-5ade99235542997c77adee7f` cites the "Dow
AgroSciences" paragraph next to the gold "Dow Chemical Company" and scores 0.5. The numbers below
are therefore a lower bound on citation correctness. The PLAN.md metric "share of claims with
>= 1 valid citation" is not computed separately: the validator removes any claim without a
retrieved citation, and it removed none (0 dropped claims in 4 x 72 answers).

## 3. Results

### Retrieval

`retrieval`, k = 10, 61 answerable questions, 0 errors. Tuned on this set (ADR 0029).

| strategy/mode | Recall@5 | Recall@10 | MRR |
|---|---|---|---|
| fixed/dense | 0.80 | 0.89 | 0.86 |
| fixed/hybrid | 0.83 | 0.89 | 0.79 |
| fixed/mmr (agent default) | 0.82 | 0.89 | 0.79 |
| structured/dense | 0.71 | 0.81 | 0.78 |
| structured/hybrid | 0.73 | 0.81 | 0.77 |
| structured/mmr | 0.74 | 0.83 | 0.78 |

Split by corpus (Recall@10 / MRR):

| strategy/mode | HotpotQA (25) | Acme (36) |
|---|---|---|
| fixed/dense | 0.86 / 0.89 | 0.91 / 0.83 |
| fixed/hybrid | 0.84 / 0.71 | 0.92 / 0.85 |
| fixed/mmr | 0.84 / 0.71 | 0.92 / 0.85 |
| structured/dense | 0.90 / 0.93 | 0.75 / 0.68 |
| structured/hybrid | 0.88 / 0.75 | 0.77 / 0.79 |
| structured/mmr | 0.88 / 0.75 | 0.80 / 0.79 |

Recall@10 by question type:

| strategy/mode | simple (11) | multi_hop (23) | multi_doc (15) | contradictory (12) |
|---|---|---|---|---|
| fixed/dense | 1.00 | 0.83 | 0.84 | 0.96 |
| fixed/hybrid | 1.00 | 0.80 | 0.87 | 0.96 |
| fixed/mmr | 1.00 | 0.80 | 0.87 | 0.96 |
| structured/dense | 0.91 | 0.80 | 0.80 | 0.76 |
| structured/hybrid | 0.91 | 0.78 | 0.80 | 0.81 |
| structured/mmr | 0.91 | 0.78 | 0.83 | 0.85 |

Reading these tables:
- Keyword search helps on Acme, where questions contain exact ids such as `CHG-1042`: MRR 0.85
  vs 0.83. It hurts on HotpotQA: MRR 0.71 vs 0.89, because the OR keyword query over a long
  question matches thousands of paragraphs.
- Overall, dense keeps the best MRR. Hybrid and MMR are the default because they keep the Acme
  gain at the same Recall@10, not because they win (ADR 0029).
- With fixed/mmr, 12 questions miss at least one gold document in the top 10. Three of them are
  explained by the labels or by how the question is phrased: `hp-5a7e36815542995ed0d166d4`
  (WrestleMania label noise), `hp-5a8c493e554299653c1aa020` (asks for "John Ruskin", while the
  gold paragraph is titled "Nardwuar the Human Serviette"), and `acme-004`. That question asks
  which 2026 incidents were attributed to NorthBank, and in all six modes its top 10 are HotpotQA
  paragraphs about other "incidents" (Thames Torso Murders, Bible John, Zodiac Killer, ...), with
  no Acme document at all.

### Answers

| config | prompt | EM | F1 | judge | citation P | abstain P/R | conflict P/R | fallback | cost | p50/p95 s |
|---|---|---|---|---|---|---|---|---|---|---|
| `agent` (fixed, 6 steps) | #32 | 0.52 | 0.73 | 0.82 | 0.94 | 0.77/0.91 | 1.00/0.67 | 0.03 | $0.38 | 10.3/45.6 |
| `agent` | #31 | 0.48 | 0.73 | 0.74 | 0.94 | 0.77/0.91 | 0.75/0.25 | 0.00 | $0.05 (cached rerun) | 0.7/12.9 (cached rerun) |
| `agent-structured` | #31 | 0.52 | 0.73 | 0.70 | 0.93 | 0.83/0.91 | 0.80/0.33 | 0.00 | $0.56 | 6.7/22.8 |
| `single-shot` (1 step) | #31 | 0.32 | 0.53 | 0.62 | 0.94 | 0.48/0.91 | 0.75/0.25 | 0.00 | $0.37 | 5.8/11.4 |

The same scores as counts:

| config | EM (of 25) | judge (of 61) | abstained: correct / all | flagged conflicting: correct / all, of 12 contradictory |
|---|---|---|---|---|
| `agent` | 13 | 50 | 10 / 13 | 8 / 8, 8 of 12 |
| `agent`, #31 | 12 | 45 | 10 / 13 | 3 / 4, 3 of 12 |
| `agent-structured` | 13 | 43 | 10 / 12 | 4 / 5, 4 of 12 |
| `single-shot` | 8 | 38 | 10 / 21 | 3 / 4, 3 of 12 |

Notes on the table:
- **The `agent` (#31) row.** Its quality columns come from the committed file, which is a rerun
  mostly served by the cache. Its first, uncached run is not in a committed file. llm-wiki/09
  quotes that run at $0.41 and 13.4/40.0 s, during the `eu.*` outage
  ([ADR 0028](llm-wiki/adr/0028-haiku-global-pool-before-gpt-oss.md)). Use those figures, not
  $0.05 and 0.7/12.9 s, when comparing cost or latency with this prompt.
- **The `agent` fallback share of 0.03.** It comes from `acme-010` and `acme-012`, which got one
  gpt-oss call each and were still judged correct.
- **The cost column is a lower bound for the two loop configurations**, and it cannot be used to
  compare them with `single-shot` (section 4.10).

### Judge correctness by type

| type | n | `agent` | `agent`, #31 | `agent-structured` | `single-shot` |
|---|---|---|---|---|---|
| simple | 11 | 1.00 (11) | 1.00 (11) | 1.00 (11) | 1.00 (11) |
| multi_hop | 23 | 0.78 (18) | 0.87 (20) | 0.74 (17) | 0.52 (12) |
| - HotpotQA bridge | 14 | 10 | 12 | 12 | 10 |
| - HotpotQA comparison | 6 | 5 | 5 | 3 | 0 |
| - Acme multi-hop | 3 | 3 | 3 | 2 | 2 |
| multi_doc | 15 | 0.93 (14) | 0.87 (13) | 0.93 (14) | 0.93 (14) |
| contradictory | 12 | 0.58 (7) | 0.08 (1) | 0.08 (1) | 0.08 (1) |

## 4. Failure analysis

Where the current configuration (`agent`) fails. The judge marked 11 of the 61 answerable
questions wrong, and 1 of the 11 unanswerable questions was answered:

| failure class | count | ids |
|---|---|---|
| contradiction answered from one document | 4 | `acme-019`, `acme-021`, `acme-023`, `acme-026` |
| conflict flagged, but the short answer takes one side | 1 | `acme-020` |
| abstained after a Bedrock `ServiceUnavailableException` | 2 | `hp-5ac1b1345542994ab5c67dd0`, `hp-5a8e3ea95542995a26add48d` |
| abstained after six searches that never found the bridge entity | 1 | `hp-5a8c493e554299653c1aa020` |
| extra entity in the answer (also a label question) | 1 | `hp-5ac401bb55429919431738f4` |
| correct answer judged wrong | 1 | `hp-5a81d54a55429903bc27b9d4` |
| multi-doc answer missing one fact | 1 | `acme-001` |
| unanswerable question answered | 1 | `acme-033` |

The subsections below give, for each class, the root cause from the trace and a concrete fix with
its cost.

### 4.1 Contradictions answered from one document

These four contradictory questions get a confident single value with status `answered`, in all
four configurations. "Seed rank" is the position of the other side's document in the first
search. That search is the same call as the `retrieval` run's fixed/mmr search for the question
text, so its ranking is recorded there.

| id | conflict (gold) | answered | other side | what the agent did |
|---|---|---|---|---|
| `acme-019` | INC-301 14:02 vs STS-301 14:15 | "14:02 UTC" from INC-301 | STS-301 at seed rank 4 | read INC-301 with `get_document`, answered; 2 LLM calls, no further search |
| `acme-021` | INC-301 1,240 vs STS-301 "fewer than 300" | "1,240 merchants" from INC-301 | STS-301 **not** in the seed's top 10, nor in the one follow-up search ("March 12 2026 outage merchants affected number", almost the question again); fixed/dense ranks it 7 | 2 searches, 2 LLM calls |
| `acme-023` | INC-301 18,400 vs INC-306 26,900 | "26,900" from INC-306 | INC-301 at seed rank 8 | answered from the seed hits in 1 LLM call |
| `acme-026` | INC-202 "3 hours 10 minutes" vs STS-102 "about 2 hours" | "3 hours 10 minutes" from INC-202 | STS-102 at seed rank 7 | answered from the seed hits in 1 LLM call |

**Root cause.**
- In three of the four, the other document was among the hits the model saw. The model still
  answered from the first document that stated the value, in one or two calls, and never did the
  check the prompt asks for ("check what every document on the same event says"). The trace keeps
  chunk ids, not chunk text. So it cannot show whether the shown chunk of the other document
  actually contained the conflicting value, or whether a `get_document` call would have been
  needed to see it.
- In `acme-021` the other side was never retrieved. Dense search had it at rank 7, but hybrid
  fusion and MMR pushed it out of the top 10, and the model's follow-up query repeated the
  question.
- Three of the four "other sides" are public status pages. They use vaguer wording ("fewer than
  300", "about 2 hours") than the incident reports, so the two values look less like competing
  answers to the same question.

**Fix.** A server-side check before `final_answer` is accepted: one more search for the asked
fact that excludes the documents already cited, with its hits shown to the model in a last turn
([14 Known gaps](llm-wiki/14-known-gaps.md) proposes this).
- Cost: one Cohere query and one Haiku call per question. The `agent` run averages 2.3 LLM calls
  per question, so this is about 40% more calls against a quota of 10 requests/min.
- Risk: more `conflicting` flags on answerable questions. The current prompt has none, but each of
  the #31-prompt runs had one (section 4.9).

A cheaper partial fix for `acme-021`: let the agent's follow-up searches use `dense` mode. That
costs nothing, but it is one question, and dense loses on Acme's id-heavy questions.

### 4.2 Conflict flagged, short answer one-sided (`acme-020`)

The question asks whether the March 12 outage was caused by Acme or by the card network. The gold
answer has three values: ledger pool exhaustion (INC-301), slow responses from NorthBank (INC-302)
and a third-party card network (STS-301). The `agent` answer:
- has status `conflicting`;
- has one contradiction citing INC-302, STS-301 and INC-301: "Preliminary reports (INC-302 and
  STS-301) initially blamed NorthBank ... the final postmortem (INC-301) determined the actual root
  cause was Acme's own change CHG-1042";
- has the short answer "Acme's own systems".

The judge marked it wrong ("does not report this disagreement and instead asserts a single
cause").

**Root cause (from the trace).**
- The model's first `final_answer` had a two-sided short answer: "Acme's own systems (according
  to final postmortem) or card network NorthBank (according to preliminary reports)".
- Its `claims` field was malformed (section 4.6). After the first reprompt, the model resubmitted
  with the short answer cut to one side, and a second reprompt followed.
- The contradiction also merges two of the three gold values: STS-301 blames an unnamed
  "third-party card network", not NorthBank.

So the reprompt path changed the content of the answer, and the conflict that was reported is not
the full three-way conflict. Whether the verdict is right is a judgment call, and this case is in
the spot-check (section 5).

**Fix.** For status `conflicting`, build the short answer on the server from the values in the
contradiction text, or reject a `conflicting` answer whose short answer names only one value. It
needs no extra LLM call. The risk is a clumsy short answer, which costs nothing here because EM is
computed only on HotpotQA questions. Fixing the malformed-claims problem (section 4.6) removes the
reprompt that caused this case.

### 4.3 What the #31 -> #32 prompt change fixed

With the #31 prompt, contradiction recall was 0.25, and the traces show two causes:
1. **Contradictions dropped by the validator.** The model wrote each side of a conflict as its own
   `contradictions` entry with a single citation. The validator requires >= 2 distinct citations
   per entry ([ADR 0005](llm-wiki/adr/0005-agent-loop-with-citation-validation.md)), so it dropped
   8 entries in 5 questions: `acme-020`, `acme-022`, `acme-025`, `acme-027`, `acme-030`. In
   `acme-027` this turned a correct conflict into an abstention.
2. **Only one source read.** The agent stopped at the first source that answered: 9 of 12
   contradictory answers cited fewer than 2 documents.

The #32 prompt asks for one entry per conflict citing both sides, and for a check of every document
on the event. Result on the same 12 questions:
- no contradiction was dropped;
- 4 of 12 cited fewer than 2 documents (was 9);
- recall rose from 0.25 to 0.67 and judge correctness from 0.08 to 0.58;
- no answerable question was flagged `conflicting`.

The change was written while looking at these same 12 questions, so this is an in-sample gain
(section 6).

### 4.4 Multi-hop failures of the current agent

Multi-hop judge correctness went from 0.87 (#31 prompt) to 0.78 (current prompt), which is two
questions. Neither change is caused by the new contradiction rules. Both questions are below, with
the other two multi-hop failures.

- **`hp-5ac1b1345542994ab5c67dd0` and `hp-5a8e3ea95542995a26add48d`: Bedrock error.** Both ended
  with a `ServiceUnavailableException` from Converse after 45 s. The first had made 4 searches and
  read the Egerton paragraph, the second had made 2 searches. ADR 0025 turns a Bedrock error into
  `insufficient`, so both count as abstentions on answerable questions. That inflates the
  "abstained" count with infrastructure failures, and `hp-5a8e3ea9...` is also the p95 latency
  value (45.6 s). It was answered correctly in the #31 run. `hp-5ac1b134...` abstained there too,
  but for a different reason: its own claims stated both facts (Field Marshal has been the highest
  rank since 1736; Egerton was a Field Marshal), yet it abstained after five searches. The question
  is noisy ("Sinch", "Egertong", British vs Indian Army). **Fix:** the runner should record
  answers whose trace has an `error` step as errors, not as model abstentions, and report them
  apart. This is a few lines of code with no risk to the system.
- **`hp-5a8c493e554299653c1aa020`: the bridge entity was never found.** "John Ruskin" is the real
  name of the musician Nardwuar, and the gold paragraph is titled "Nardwuar the Human Serviette".
  Retrieval for the question text has Recall@10 0.0 in every fixed mode (structured/mmr 0.5). The
  agent tried five sub-queries ("John Ruskin album name", "John Ruskin", "John Ruskin album
  removal", ...), never got the Nardwuar paragraph, and abstained at the forced last step. In the
  #31 run the query "John Ruskin album named" returned the Nardwuar paragraph at rank 3, and the
  answer was right. The trace keeps chunk ids rather than titles for these searches, so it does not
  show which other John Ruskin the hits were about. The abstention is the correct behaviour for
  what it saw. The flip between runs is variance: one word in a self-chosen query decided the
  question. **Fix:** none cheap at the system level. For analysis, store each search hit's source
  in the trace (a small change in `agent.py`).
- **`hp-5ac401bb55429919431738f4`: extra entity.** All four configurations answer "Ub Iwerks and
  Walt Disney" (or the reverse order), while the gold answer is "Ub Iwerks". The claims cite the
  Oswald and Mickey Mouse paragraphs, which credit both men, but not the gold "Les Clark"
  paragraph (citation precision 0.25). The question expects one person, and the system's answer is
  defensible from what it cites. This is as much a label question as a model error. It is in the
  spot-check.
- **`hp-5a81d54a55429903bc27b9d4`: a judge error.** The answer is "No", with claims "Kyle Patrick
  was in The Click Five as the lead singer" and "Jeff Martin ... is best known for fronting The Tea
  Party, not The Click Five". That matches the gold answer "no", and EM is 1. The judge read the
  first claim as contradicting the answer. It is in the spot-check.

### 4.5 Single-shot vs the loop

Both configurations use the #31 prompt, fixed chunks and `mmr`. The only difference is
`max_steps` (1 vs 6).
- Judge correctness: 0.62 vs 0.74 overall, 0.52 vs 0.87 on multi-hop.
- Abstentions: `single-shot` abstained 21 times, and 11 of those were answerable questions
  (abstention precision 0.48). Nine were multi-hop, plus `acme-004` and `acme-028`.

Where the loop pays off:
- **Comparison questions: 0 of 6 vs 5 of 6.** `single-shot` abstained on all six.
  - In four of them the seed hits already held both gold paragraphs (fixed/mmr Recall@10 1.0:
    `hp-5a85fc99...`, `hp-5ab296a6...`, `hp-5a8da97c...`, `hp-5a80caac...`), so retrieval was not
    the problem. The compared attribute (Academy Award counts, worldwide popularity, campuses in
    the Philippines, Hall of Fame induction) is not stated side by side, and with one forced step
    and an "abstain instead of guessing" rule, Haiku abstains. In the same questions the loop made
    attribute-specific searches first ("Tony Kaye Academy Awards Oscars wins", "Chess popularity
    worldwide millions players", "Western Institute of Technology Philippines campuses ...",
    "Patty Jenkins Rock and Roll Hall of Fame inducted").
  - In the other two (`hp-5ae3d0bb...`, `hp-5a81d54a...`), one gold paragraph was missing from
    the seed hits (Recall@10 0.5), and a second search was needed.
- **Bridge questions:** 10 vs 12 of 14. `hp-5a8e3ea9...` is the textbook case. The seed hits had
  the film but not its director's paragraph. The loop's one follow-up search ("Adriana Trigiani
  based New York city") found it. The reverse also happens: `hp-5ac1b134...` was answered right by
  `single-shot` ("Since 1736"), while the loop abstained after five searches.
- **Questions whose wording misses the documents.**
  - `acme-004`: the seed hits contain no Acme document (section 3, Retrieval). `single-shot` abstained. The loop
    found INC-302 and INC-303 through sub-queries ("2026 incident NorthBank fault"). That answer
    was judged correct in `agent`; the #31 run's answer is in the spot-check.
  - `acme-017`: the seed hits lacked INC-301 in both chunkings. `single-shot` and
    `agent-structured`, which did not search again, named the webhook runbook RB-07. Both `agent`
    runs searched "March 12 2026 outage root cause" first and named RB-03.
- **A malformed answer.** With one step there is no room for a reprompt. `acme-028` lost its
  answer to a malformed `final_answer`.

Where the loop does not help: multi-doc questions (13 of 15 with the loop, 14 with `single-shot`)
and simple questions (11 of 11 in both). There the seed search usually returns everything
needed.

The price of the loop for `agent`: 2.3 LLM calls and 2.1 searches per question on average (vs 1
and 1), p50 10.3 s vs 5.8 s, p95 45.6 s vs 11.4 s. The cost column suggests the two cost the same
($0.38 vs $0.37). That is an artefact of the cost metric (section 4.10).

### 4.6 Malformed `final_answer`

| config | answers with a reprompt | reprompt events | LLM calls in run |
|---|---|---|---|
| `agent` | 5 | 10 | 167 |
| `agent`, #31 | 16 | 27 | 190 |
| `agent-structured` | 12 | 16 | 177 |
| `single-shot` | 1 | 1 | 72 |

There are two patterns in the trace's `reprompt.input`:
- **`claims` sent as a string of tool-call markup**, which fails to parse as JSON ("Expecting
  value: line 2 column 1"):
  `"claims": "\n<parameter name=\"text\">A total of 26,900 webhooks were delayed ...", "citations": [138136]`.
  The model flattens one claim into markup and moves its citations to the top level. This pattern
  accounts for 6 of the 10 events in `agent`, 21 of 27 in the #31 run and 15 of 16 in
  `agent-structured`.
- **A single claim object** `{"text", "citations"}` instead of a list ("claims must be a list"):
  4 events in `agent`, 6 in the #31 run, 1 in `agent-structured`.

[ADR 0025](llm-wiki/adr/0025-agent-loop-seeded-forced-deadline.md) already decodes `claims` sent
as a JSON string. This markup is not JSON, so it goes back to the model as a reprompt. The cost of
each reprompt:
- one extra Haiku call, which is 6% of the calls in `agent` and 14% in the #31 run;
- one step of the six;
- in `single-shot`, the whole answer (`acme-028`);
- in `acme-020`, the content of the answer: the resubmission cut a two-sided short answer to one
  side.

The #32 prompt reduced the problem (16 -> 5 answers) without targeting it.

**Fix.** Repair the two shapes on the server before validation:
- parse the `<parameter name="text">` block together with the top-level `citations` into one claim;
- wrap a lone claim object in a list.

Then let the validator check the result as usual, so wrong citations are still dropped. The cost
is one more leniency in front of a strict validator (ADR 0025 accepted the same trade for JSON
strings). The risk is masking a model regression, so keep counting repairs in the trace.

### 4.7 EM vs F1 vs judge

On the 25 HotpotQA questions, `agent` scores EM 0.52 (13 questions), F1 0.73 and judge 0.80 (20
questions). Of the 12 EM misses, 3 are abstentions (4.4) and 1 is the extra-entity answer (4.4).
The judge marked the other 8 correct:

| id | gold | short answer | F1 |
|---|---|---|---|
| `hp-simple-2` | two | two monks | 0.67 |
| `hp-5adbf44355429944faac23ce` | Honolulu | Honolulu County | 0.67 |
| `hp-5ade99235542997c77adee7f` | Midland, Michigan, United States | Midland, Michigan | 0.67 |
| `hp-5ab6993f554299110f219a2b` | Sierra Nevada mountains | Sierra Nevada | 0.80 |
| `hp-5a88a42f554299206df2b317` | the growing literary style called New Journalism | New Journalism | 0.50 |
| `hp-5a8b20335542996c9b8d5fb3` | shortest player ever to play in the National Basketball Association | Shortest player ever to play in the NBA | 0.75 |
| `hp-5a85fc995542996432c5715f` | Joseph Leo Mankiewicz | Joseph L. Mankiewicz | 0.67 |
| `hp-5a8ae0ae55429950cd6afbc2` | AeroflotRussian Airlines | Aeroflot | 0.00 |

These 8 misses have three different causes:
- In only 2 did the system add words ("two monks", "Honolulu County").
- In 4 the gold span is longer than the answer, or uses a full name where the answer uses an
  abbreviation.
- 2 are label artefacts: the question is "who won more", so the gold is a name variant; and
  "AeroflotRussian Airlines" is two words fused in the dataset, so F1 is 0 for a correct answer.

So tightening the short answer would recover at most 2 EM points of 25 (0.08) on this set. The rest
of the EM-judge gap is EM's strictness against HotpotQA's span labels. The reverse also happens:
`hp-5a81d54a...` has EM 1 and was judged wrong (a judge error, 4.4).

Label noise affects the retrieval and citation numbers too. `hp-5a7e36815542995ed0d166d4` is
answered correctly in every configuration (EM 1). Its claims cite the WrestleMania IX paragraph,
but the gold source is WrestleMania XXIV. That gives citation precision 0.5 and Recall@10 0.5 in
every mode, for a question the system gets right.

### 4.8 Chunking: fixed vs structured

**Retrieval.** Fixed chunks win overall (Recall@10 0.89 vs 0.81-0.83), but only because of Acme:

| corpus | fixed Recall@10 | structured Recall@10 |
|---|---|---|
| Acme | 0.91-0.92 | 0.75-0.80 |
| HotpotQA | 0.84-0.86 | 0.88-0.90 |

On HotpotQA structured is slightly ahead. That is one or two questions, and with 25 questions one
question moves Recall by 0.04.

**Why HotpotQA cannot separate the two chunkers.** A HotpotQA paragraph averages 532 characters,
roughly 90 words. The fixed chunker uses 300-word windows with a 50-word overlap, and the
structured chunker caps a block at 300 words. Both therefore keep almost every paragraph whole,
and the chunks are nearly the same; differences come from ranking near-ties.

**Where it matters: Acme.** Acme documents are long, with sections, lists and tables of times.
- A 300-word cap splits Acme's long sections less evenly than fixed windows do (ADR 0029).
- A PDF page is extracted as one paragraph ([14 Known gaps](llm-wiki/14-known-gaps.md)), so on the
  11 PDFs the structured chunker has no paragraph boundaries to use.
- Acme questions where structured/mmr loses a gold document that fixed/mmr finds: `acme-011`,
  `acme-016`, `acme-018`, `acme-020`, `acme-022`, `acme-029` and `acme-038` (the March
  availability report: Recall@10 0.0 vs 1.0).

**Answers.** With the same prompt (#31), judge correctness is 0.70 (`agent-structured`, 43 of 61)
vs 0.74 (`agent`, 45 of 61), a two-question gap. On the Acme questions both get 23 of 36, with
different misses: for example, `acme-017` is wrong only with structured chunks and `acme-001` only
with fixed. The large retrieval gap on Acme does not show up in the answers, because the agent
compensates with `get_document` (whole documents) and follow-up searches. The per-question
differences in answers look like agent variance (whether it searches again), not like a chunking
effect.

**Conclusion.** Fixed chunks as the default is justified by retrieval on Acme. The difference in
answers is within noise. This set cannot show whether structured chunking pays off on another
corpus.

### 4.9 Abstention errors and false conflict flags

**Missed abstention.** Unanswerable recall is 10 of 11 in all four configurations, and the miss is
always `acme-033` ("Why did fraud-scorer model v3.4 decline so many legitimate payments?"). INC-201
says the model-level analysis is an open follow-up. The system returns status `answered` with "v3.4
exhibited unexpected behavior ... The specific model-level factors remain under investigation".
The content effectively says "not known", but the status claims an answer, so the metric counts a
miss.
- **Fix:** a prompt rule that a document saying a fact is unknown or still under investigation
  means `insufficient`.
- **Risk:** more abstentions on answerable questions, which are already the larger error (below).

**Answerable questions that abstained:**

| config | count | ids and cause |
|---|---|---|
| `agent` | 3 | 2 Bedrock errors and `hp-5a8c493e...` (4.4) |
| `agent`, #31 | 3 | `hp-5ac1b134...` (hedged despite its own claims), `hp-5a81d54a...` (abstained after 7 searches), `acme-027` (both one-citation contradictions dropped, 4.3) |
| `agent-structured` | 2 | the comparisons `hp-5a85fc99...` and `hp-5a8da97c...` |
| `single-shot` | 11 | see 4.5 |

The prompt's "abstain instead of guessing" rule is doing its job on unanswerable questions (recall
0.91). Its errors are on the other side: every run has 2-11 abstentions on answerable questions
against 1 missed abstention.

**False `conflicting` flags** on answerable questions: none in `agent`, one in each #31-prompt run.
- `acme-004` (`agent`, #31) reported a real "at first NorthBank, later INC-301" disagreement, which
  the question itself asks about.
- `hp-5ac1b134...` (`agent-structured`) flagged the question's premise ("an Indian Army officer,
  not a British Army officer") as a contradiction between documents.
- `acme-007` (`single-shot`) reported a real planted conflict (312 vs 297 ledger entries) that the
  question did not ask about.

Two of the three are true conflicts in the corpus, so the precision of 0.75-0.80 understates
detection quality.

### 4.10 Measurement flaw: the cost column leaves out prompt-cache tokens

`run.cost` prices `usage.inputTokens` and `usage.outputTokens`. Bedrock reports prompt-cache
tokens in separate fields, and `totalTokens` is the sum of all four. One record from `agent.json`:
`inputTokens` 5, `cacheWriteInputTokens` 4,930, `outputTokens` 348, `totalTokens` 5,283. A
call with a 4,935-token prompt was priced as 5 input tokens.

| config | `inputTokens` (priced) | `cacheWriteInputTokens` (not priced) | `cacheReadInputTokens` (not priced) |
|---|---|---|---|
| `agent` | 219,081 | 545,726 | 455,645 |
| `agent-structured` | 360,005 | 363,603 | 305,101 |
| `single-shot` | 306,813 | 0 | 0 |

`single-shot` makes one forced call with no history cache point (ADR 0025), so its cost is
complete. The two loop configurations are undercounted, because cache writes are billed at more
than the normal input price, not less. Three consequences:
- "The loop costs the same as single-shot" ($0.38 vs $0.37) is wrong.
- The `agent` per-question cost (about $0.005) disagrees with ADR 0025's live measurement of about
  $0.041 for one six-call bridge question.
- llm-wiki/09's cost figures inherit the same flaw.

**Fix:** price `cacheWriteInputTokens` and `cacheReadInputTokens` at their Bedrock rates in
`run.cost`, a few lines of code. No rerun is needed: every call's `usage` is in the committed
traces, so the cost can be recomputed from the files.

### 4.11 Small-set noise

One question moves a score by 1/n:

| scope | n | one question moves the score by |
|---|---|---|
| judge, overall | 61 | 0.016 |
| HotpotQA EM / F1 | 25 | 0.04 |
| multi-hop | 23 | 0.04 |
| multi-doc | 15 | 0.07 |
| contradictory | 12 | 0.08 |
| simple | 11 | 0.09 |

Between two uncached runs, two multi-hop questions flipped for reasons unrelated to the change
being tested (4.4). So differences below about 0.1 within a type are noise. That covers multi-hop
0.87 vs 0.78 between the prompts, structured vs fixed on answers, and every difference between
hybrid and MMR. What clears the noise:
- contradiction recall 0.25 -> 0.67 (+5 questions; judge +6);
- the loop on multi-hop (+8 questions);
- fixed vs structured retrieval on Acme (0.92 vs 0.80).

### Improvement priorities

In the order of what they fix per unit of work:
1. **Repair the two malformed-claims shapes on the server** (4.6). No extra calls. It removes
   reprompts in 5-16 answers per run and the one-sided rewrite in `acme-020`.
2. **Count tokens correctly** (4.10): price the cache tokens and recompute from the committed
   traces. Without this, no cost comparison between configurations is valid.
3. **Separate infrastructure errors from abstentions in the runner** (4.4). It is a measurement
   fix that changes the reported abstention precision without changing the system.
4. **A second, exclusion search before a contradiction-prone answer is accepted** (4.1). It
   targets the four remaining contradiction misses, for about one Haiku call more per question.
5. **Hold out part of the set** before any further tuning (section 6).

## 5. Judge spot-check

Ten verdicts were chosen from the four result files. They mix verdicts of true and false, question
types and configurations, and they include the two cases llm-wiki/09 flags: `acme-024` and
`acme-004`, both in the `agent` run with the #31 prompt. The author verdict column is for the
author to fill in by hand. Answers are trimmed.

| id | config | question | gold | system answer (status + short answer, trimmed) | judge verdict | author verdict |
|---|---|---|---|---|---|---|
| `hp-simple-2` | `single-shot` | How many monks live at Mariastern Abbey near Banja Luka today? | two | answered: "two monks" | correct | |
| `hp-5a8ae0ae55429950cd6afbc2` | `agent` | What airline was a monopoly with a hub at Sheremetyevo International Airport? | AeroflotRussian Airlines | answered: "Aeroflot" | correct | |
| `hp-5a81d54a55429903bc27b9d4` | `agent` | Were Jeff Martin and Kyle Patrick both in The Click Five? | no | answered: "No" (claims: Kyle Patrick was its lead singer; Jeff Martin fronted The Tea Party) | wrong | |
| `hp-5ac401bb55429919431738f4` | `agent-structured` | Who worked on the origins of Mickey Mouse and created Oswald the Lucky Rabbit? | Ub Iwerks | answered: "Walt Disney and Ub Iwerks" | wrong | |
| `acme-001` | `agent` | What caused the card payment outage on March 12, 2026, and how was it fixed? | CHG-1042 cut max_connections 200 -> 20 ...; rolled back at 14:41 UTC and CHG-1047 restored 200 with a check | answered: "CHG-1042 reduced the ledger connection pool from 200 to 20 ... fixed by rolling back CHG-1042 at 14:41 UTC" (no claim mentions CHG-1047) | wrong | |
| `acme-004` | `agent`, prompt of #31 | Which incidents in 2026 were attributed, at least at first, to NorthBank? | INC-302 (March 12 timeouts) and INC-303 (March 26 3-D Secure failures) | conflicting: "Two incidents: (1) card-gateway authorization timeouts on March 12 ... (2) 3-D Secure challenge failures for Visa cards on March 26" (contradiction: INC-302 blamed NorthBank, INC-301 found CHG-1042) | wrong | |
| `acme-017` | `agent-structured` | Which runbook covers the failure behind the March 12, 2026 outage, and which metric does it watch? | RB-03, ledger_pool_in_use (above 90%) | answered: "RB-07 (webhook backlog runbook); watches webhook_queue_depth metric" | wrong | |
| `acme-020` | `agent` | Was the March 12, 2026 outage caused by Acme's own systems or by the card network? | conflicting: pool exhaustion (INC-301) vs slow NorthBank (INC-302) vs third-party card network (STS-301) | conflicting: "Acme's own systems" (contradiction: INC-302 and STS-301 blamed NorthBank, INC-301 found CHG-1042) | wrong | |
| `acme-024` | `agent`, prompt of #31 | At what time was fraud-scorer model v3.4 deployed on January 21, 2026? | conflicting: 09:30 UTC (CHG-1011) vs 10:15 UTC (INC-201) | conflicting: "09:30 UTC" (contradiction: INC-201 says 10:15, CHG-1011 says 09:30) | wrong | |
| `acme-028` | `agent` | What timeout does card-gateway use for NorthBank authorization requests? | conflicting: 8 seconds (CHG-1007) vs 5 seconds (RB-05) | conflicting: "8 seconds" (contradiction: RB-05 says 5 s, CHG-1007 raised it to 8 s) | correct | |

Agreement: TODO (author)

**Inconsistencies visible in the result files.** These are facts about the files, not verdicts.
The judge gave opposite verdicts to answers of the same shape: status `conflicting`, one value in
the short answer and both values in the contradiction.
- `acme-028`: judged correct in `agent` and wrong in `agent-structured`, with nearly the same
  contradiction text.
- `acme-024` (`agent`, #31) was judged wrong, while `acme-028` in the same run was judged correct.
- `acme-019` (`single-shot`) was judged wrong.
- `acme-024` (`single-shot`) has an empty short answer and both values in its claims and
  contradiction, and was judged correct.

On the other hand, `acme-001` looks inconsistent at first sight but is not: `agent-structured`
gives the same short answer, and the judge accepted it there because its claims mention CHG-1047.

## 6. Threats to validity

- **One judge, unmeasured bias.** All correctness numbers are one model's opinion. Using Qwen3 to
  judge a Claude generator removes self-preference, not leniency or inconsistency. Section 5 shows
  opposite verdicts for equivalent answers. Until the spot-check agreement is filled in, read
  judge numbers as plus or minus a few questions.
- **Tuned on the test set.** The RRF weights, `k0` and the MMR lambda were chosen with this
  question set ([ADR 0029](llm-wiki/adr/0029-weighted-rrf-min-max-mmr-fixed-chunks.md)), and the
  #32 contradiction prompt was written against these 12 contradictory questions. Retrieval
  numbers and the contradiction gain are optimistic. A held-out split would fix this, and there
  is none.
- **Small set.** There are 61 answerable questions and 11-25 per type. Differences below about 0.1
  are noise (4.11).
- **Two prompt versions in one table.** `agent` runs the #32 prompt, and the other three answer
  rows run #31. Only rows with the same prompt can be compared: `agent` (#31), `agent-structured`
  and `single-shot`.
- **Cached reruns.** The `agent` (#31) row is a rerun served mostly by `llm_cache`. Its quality
  columns are close to the first run's but not identical, and its cost and latency are not the
  system's.
- **Cost is undercounted** for the loop configurations (4.10).
- **HotpotQA label noise.** Fused or over-long gold answers and a wrong supporting title
  (4.7) lower EM, citation precision and Recall for answers that are right.
- **The synthetic corpus and the generator share a family.** Haiku wrote all 64 Acme documents
  from a hand-written spec and Haiku answers the questions about them. Its own phrasing may be
  easier for it to retrieve and read than real incident reports would be. The planted values were
  checked verbatim, but the documents' style was not. Acme results (36 of 61 answerable questions)
  may overstate performance on real documents.
- **Run-to-run variance from external services.** The `eu.*` outage
  ([ADR 0028](llm-wiki/adr/0028-haiku-global-pool-before-gpt-oss.md)) and Bedrock errors changed
  which pool answered, and two answers became abstentions. The `fallback` column and the trace's
  per-call `model` make this visible, but it is not controlled.

## 7. How to reproduce

The jobs run in CodeBuild, not on a laptop (ADR 0018). The whole value is one `TARGET`:

```bash
aws codebuild start-build --project-name investigation-jobs --profile investigation \
  --environment-variables-override "name=TARGET,value=eval CONFIG=agent LIMIT=3"
# full runs: value=eval CONFIG=retrieval | agent | agent-structured | single-shot
```

- The result lands in `s3://$BUCKET/jobs/eval/<config>.json` (`<config>-limit<N>.json` for a dry
  run, so it never overwrites a full run). Download it and commit it through a PR. The build log
  ends with the summary as Markdown tables.
- `retrieval` needs no LLM and costs only CodeBuild minutes. An answer run takes 9-22 minutes
  because of pacing.
- Do not run an eval while a bulk load or the Acme generation is running: they share the Cohere and
  Haiku quotas.
- A rerun with unchanged prompts is mostly served by `llm_cache`. Expect a few answers to differ,
  and do not quote its cost or latency.
- Every table in this report can be recomputed from the committed JSON files without any AWS call:
  `summary` holds the aggregates, and `records[].trace` holds the evidence used in section 4.
