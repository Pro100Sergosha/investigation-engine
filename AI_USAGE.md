# AI Usage Report

Which AI tools were used to build this project, what they helped with, where their output was
wrong and what caught it, and what was changed or decided by hand (task section 7).

Two kinds of AI are involved and are kept apart below:

- **Development tools** (section 1): the assistants that wrote and changed the code, docs and
  infrastructure.
- **Models inside the product** (section 2): the models the deployed system calls at run time.
  They are part of the architecture, not development tools.

Everything here is taken from the repository: `git log`, the bodies of PRs #1-#33,
[PLAN.md](PLAN.md), [CLAUDE.md](CLAUDE.md), [llm-wiki/](llm-wiki/index.md) and its ADRs. Lines
marked `TODO (author)` are facts only the author can supply.

## 1. AI tools used to build the system

TODO (author): confirm the tool list and add anything missing.

| Tool | Used for |
|---|---|
| **Claude Code** (CLI), models Claude Opus and Claude Sonnet | The main coding assistant: code, tests, docs, ADRs, CDK, PR descriptions. Opus for tasks with hidden context and for design; Sonnet for tasks fully specified by tests; Haiku not used for code. |
| Claude Code **subagents** | Parallel "waves" of coding agents, each in its own git worktree and branch, each ending in a PR that must pass CI (section 3). |
| Claude Code plugins and configuration | RTK (token-saving CLI proxy), caveman (terse replies), ponytail (minimal-code rules; its `ponytail:` comment convention marks deliberate simplifications in the code, e.g. `src/engine/llm.py`, `src/engine/parsers.py`), security-guidance, python-development skills. |
| `aws-mcp` server and the installed AWS skills | AWS documentation and API access; [CLAUDE.md](CLAUDE.md) tells the assistant to prefer them over memory for AWS work. |
| Claude in Chrome | Checking the deployed UI in the browser (wave 4). |
| GitHub CLI (`gh`) | Creating PRs, watching CI checks. |

What the repository itself shows about the tooling:

- [CLAUDE.md](CLAUDE.md) is the instruction file every session reads: repo rules, AWS Free-plan
  constraints, Definition of Done, rules for keeping docs true.
- Wave PRs end with a "For the main session" section (e.g. #20, #21, #22, #23, #27, #28): notes
  from a coding agent to the coordinating session about files it was not allowed to touch.
- [llm-wiki/07](llm-wiki/07-infrastructure.md) records two limits of the assistant: Claude Code's
  auto mode refuses IAM-changing deploys, so the owner runs those (`make deploy-cicd`), and
  interactive AWS CLI wizards fail inside the Claude Code terminal.

## 2. AI inside the product (not a development tool)

All calls go through Amazon Bedrock with IAM, no external API keys. LLM calls go only through
`src/engine/llm.py`, embeddings only through `src/engine/embed.py`.

| Role | Model | Decision |
|---|---|---|
| Agent: plans sub-searches, calls tools, writes the cited answer | Claude Haiku 4.5, `eu.*` profile, then its `global.*` pool | [ADR 0017](llm-wiki/adr/0017-bedrock-claude-haiku-llm.md), [ADR 0028](llm-wiki/adr/0028-haiku-global-pool-before-gpt-oss.md) |
| Last automatic fallback | gpt-oss-120b (in Region) | [ADR 0017](llm-wiki/adr/0017-bedrock-claude-haiku-llm.md), [ADR 0023](llm-wiki/adr/0023-llm-client-own-retry-fallback-cache.md) |
| Evaluation judge (another model family than the generator) | Qwen3-235B | [ADR 0027](llm-wiki/adr/0027-eval-runner-retrieval-sweep-qwen-judge.md) |
| Embeddings for documents and queries | Cohere Embed V4, `eu.*` profile, 1024 dimensions (Titan Text Embeddings V2 until #24) | [ADR 0022](llm-wiki/adr/0022-cohere-embed-v4-batched.md) |
| Synthetic Acme corpus | Claude Haiku 4.5 wrote the prose of 64 documents from a hand-written spec (`data/acme/spec.json`); every planted fact is checked in the parsed file | [ADR 0026](llm-wiki/adr/0026-acme-corpus-spec-driven-generation.md) |

The model writes text, never facts of the corpus: the scenario, contradictions, gaps and questions
are in the spec, and labels (`GROUND_TRUTH.md`, `questions.jsonl`) are derived from it
(ADR 0026). Generating the corpus cost $0.28 (95 uncached Haiku calls).

## 3. How the work was organised

### Flow

1. **Plan.** [PLAN.md](PLAN.md): decisions, architecture, cost table, schedule, risks. Each
   decision has an ADR with costs and rejected alternatives.
2. **Shared contracts first.** Wave 0 (#4) fixed the dataclasses in `src/engine/models.py` and the
   function signatures every later agent codes against; docstrings are the specification
   ([ADR 0014](llm-wiki/adr/0014-shared-contracts-parallel-streams.md)). Waves 2 and 3 started
   with their own contract PRs (#19, #25).
3. **Parallel agent waves** ([PLAN.md section 5](PLAN.md), "Parallel agent waves"): one owner per
   file per wave; shared files (`models.py`, `cdk/app.py`, `pyproject.toml` + `uv.lock`,
   `handlers.py`) have exactly one owning task; dependencies are added only by the owner of
   `pyproject.toml`; at most 3-4 agents at a time because review, not typing, is the bottleneck;
   at most one agent uses the Bedrock quota for bulk work at once.
4. **Checks on every PR.** GitHub Actions runs `make check` (ruff, pytest, `cdk synth`); CodeBuild
   `investigation-pr-diff` comments the `cdk diff` against production, with a read-only role
   because PR code is untrusted (#1).
5. **Review.** The plan's rule: "The main session reviews and merges; the author reads each PR."
   TODO (author): describe how you reviewed the PRs in practice.
6. **Squash merge, automatic deploy.** A merge to `main` runs CodeBuild `investigation-deploy`:
   `make test deploy verify smoke` ([ADR 0012](llm-wiki/adr/0012-codebuild-cicd-via-codeconnections.md),
   [ADR 0013](llm-wiki/adr/0013-branch-pr-workflow-and-ci.md)).

### Numbers (from `git log` and PLAN.md)

- 39 commits on `main`: 6 before the PR workflow, then 33 squash-merged PRs (#1-#33), all merged
  between 2026-10-24 and 2026-10-26.
- 29 ADRs; 4 have status `superseded` (0004, 0007, 0009, and 0016 for its embedding model
  only) and 7 more are partly replaced by later ones (0002, 0003, 0010, 0015, 0019, 0020, 0023).

| Group | PRs | What |
|---|---|---|
| Setup and process | #1, #2, #3, #9, #11, #18, #33 | CI/CD, the cloud-only plan, the wave rules, doc-accuracy rules, deploy concurrency, progress tracking |
| Wave 0 | #4 | Contracts in `models.py`, signatures, dedup hash, API shapes |
| Wave 1 | #5, #6, #7, #8, #10, #12, #13, #14, #15, #16, #17 | Chunkers, RRF + MMR, parsers, citation validator, eval metrics, HotpotQA dataset job, infra (Aurora, bucket, `ingest`, jobs project; two of the four infra PRs fixed red deploys), UI page |
| Wave 2 | #19, #20, #21, #22, #23, #24 | Wave-2 contracts, LLM client, document API and `ingest` wiring, writes with dedup, hybrid search, Cohere embeddings |
| Wave 3 | #25, #26, #27, #28 | Wave-3 contracts, eval runner, agent loop and `POST /ask`, Acme corpus |
| Fixes driven by measurement | #29, #30, #31, #32 | Haiku fallback, search tuning, eval runner fixes and full results, contradiction output |
| Wave 4 | this PR and two parallel ones | `AI_USAGE.md`, `README.md`, `EVALUATION.md` |

### "Explainable without AI"

The interview requires explaining and changing any line live without AI, which shaped what the
assistants were allowed to produce ([ADR 0001](llm-wiki/adr/0001-own-code-no-rag-frameworks.md),
the prime rule in [CLAUDE.md](CLAUDE.md)):

- No LangChain, LlamaIndex, Haystack, ORMs or web frameworks. LangChain for only the LLM client
  and agent loop was reconsidered and rejected again (ADR 0001 update); RAGAS/DeepEval were
  rejected for the eval (ADR 0027).
- Hand-written core: chunkers, dedup, RRF, MMR, the agent loop, the citation validator, the
  Lambda router, the metrics, even the PDF writer of the Acme generator (~50 lines instead of
  fpdf2, #28).
- A dependency only where writing it by hand is unreasonable (pypdf, python-docx, pg8000).

### Docs kept true in the same PR

Every PR that changes the system updates `llm-wiki/` (the system as it is), the ADRs (new ADR,
superseding ADR, or a dated `## Update` section) and PLAN.md status in the same PR (rules added
in #9 and #18). The reason is practical: each new AI session starts with no memory and acts on
whatever the docs say, so a stale doc leads the next session to wrong changes. PR #18 itself was
caused by this: after wave 1 merged, PLAN.md still showed every task as not done.

## 4. Where the output was wrong or had to change, and what caught it

These are decisions or code that were merged or planned and then shown wrong by a measurement, an
error, a deploy or a review. The record does not say who first proposed each of them.

TODO (author): for each item below, say whether the original choice came from an AI suggestion,
from you, or from both, and how you judged the replacement.

### 4.1 AWS account and CI/CD (#1, ADR 0011, ADR 0012)

- **What happened:** the first dedicated AWS account used IAM Identity Center. Enabling it created
  an AWS Organization, and the account was upgraded to the Paid plan, which breaks the free-tier
  requirement.
- **What showed it:** the upgrade to the Paid plan itself (no hard spending stop any more).
  **Fix:** a new Free-plan AWS project, `aws login`, a
  rule in CLAUDE.md never to enable anything that upgrades the plan
  ([ADR 0011](llm-wiki/adr/0011-free-plan-aws-project.md)).
- Next, the first CI design deployed from GitHub Actions through OIDC. The Free-plan SCP denies
  `iam:*Provider*`, so deploys moved to CodeBuild through CodeConnections
  ([ADR 0012](llm-wiki/adr/0012-codebuild-cicd-via-codeconnections.md)). Creating the CodeBuild
  projects then failed twice on IAM timing (role policy not yet propagated); fixed with
  inline policies (commit messages in #1).

### 4.2 LLM provider: Groq -> Bedrock (ADR 0004 -> ADR 0017, #2)

- **Decided:** Groq's free tier (gpt-oss-120b) with Bedrock as fallback
  ([ADR 0004](llm-wiki/adr/0004-groq-llm-with-postgres-cache.md)).
- **What showed it wrong:** a re-plan on day 1 (#2: "Decisions agreed on 2026-10-24"). Groq needs
  an external API key and caps the free tier at roughly 8k tokens/min, which would stall the
  evaluation, while $100 of AWS credits were available.
- **Fix:** all LLM calls on Bedrock, Claude Haiku as the main model
  ([ADR 0017](llm-wiki/adr/0017-bedrock-claude-haiku-llm.md)).

### 4.3 Database: public RDS -> Aurora Data API -> isolated VPC -> Aurora express with IAM auth

- **ADR 0007** (public RDS, loaded from the laptop) was replaced in #2 by
  **[ADR 0015](llm-wiki/adr/0015-aurora-serverless-data-api.md)** (Aurora Serverless v2 through the
  Data API): RDS would cost ~$18/month idle, and nothing may run on the laptop (ADR 0018).
- **[ADR 0019](llm-wiki/adr/0019-isolated-vpc-schema-custom-resource.md)** (#8) put the cluster in
  its own isolated VPC with a schema custom resource running Data API statements.
- **Caught by a deploy error.** The first deploy of the data stack failed: "To use Aurora clusters
  with free plan accounts you need to set WithExpressConfiguration." An express cluster has no VPC,
  logs in only with IAM tokens, and the Data API would need a password user and a secret anyway.
- **Fix:** [ADR 0021](llm-wiki/adr/0021-aurora-express-iam-auth.md) (#10): every caller connects
  with `pg8000` over TLS and an IAM auth token; no secret, no VPC, no Data API.
- **Two more deploy errors:** the express create rejects an initial database name, although the
  Aurora User Guide says it can be set at creation (#12); deletion protection was then added by a
  later update (#13). Four merges within a minute also ran four deploys in parallel (immutable
  image tag clash, missing export), fixed by one deploy build at a time (#11).

### 4.4 Embeddings: Titan -> Cohere Embed V4 (ADR 0016 -> ADR 0022, #24)

- **Decided:** Titan Text Embeddings V2, one text per request
  ([ADR 0016](llm-wiki/adr/0016-titan-embeddings-no-model-in-lambda.md)). Its 2026-10-24 update
  kept Titan and named Cohere only as the fallback "if the bulk load turns out to be throttled".
- **Caught by the real bulk load:** it stalled at 1,853 of 66,555 documents. Titan throttled beyond
  ~1 request/s (~18 h for the corpus), Lambda's async retries were dropped without a record, and
  Titan batch inference was not authorized for the account.
- **Fix:** Cohere Embed V4, 96 texts per request, whole shards per call, ~35-40 min for the corpus;
  failed `ingest` events kept in an SQS queue with a redrive job
  ([ADR 0022](llm-wiki/adr/0022-cohere-embed-v4-batched.md)).

### 4.5 Haiku `eu.*` outage -> `global.*` fallback (#29, ADR 0028)

- **Decided:** Haiku `eu.*` with retries, then gpt-oss-120b (ADR 0023). #20 noted that spreading
  calls over the `global.*` pool was not done.
- **Caught by the eval dry run:** on 2026-10-26 the `eu.*` profile answered
  `ServiceUnavailableException` to every call for 15+ minutes. The dry run had a fallback share of
  1.0 (it measured gpt-oss, not the system) and one question ran out of the 80 s deadline.
- **Fix:** `eu.*` once, then `global.*` with retries, then gpt-oss; plus a bounded client for query
  embeddings, which closed the "search not bounded by the deadline" gap
  ([ADR 0028](llm-wiki/adr/0028-haiku-global-pool-before-gpt-oss.md)). The full eval (#31) then
  ran through the outage: 130 of 192 calls answered by `global.*`, 0 errors.

### 4.6 Search tuning by the retrieval eval (#30, ADR 0029)

- **Decided:** equal-weight RRF with k0=60, MMR relevance divided by the best score, structured
  chunks + `mmr` as the agent's default (ADR 0003, #5, #23).
- **Caught by the first `retrieval` eval:** that default was the worst of six configurations
  (Recall@10 0.62 against 0.88 for fixed/dense). A live question showed the same: the only relevant
  paragraph was rank 2 in dense, 4 in hybrid, 9 in mmr, so the agent (k=8) never saw it. The ADR
  says both causes were "in our own code": the noisy OR keyword list outranked dense's top hits,
  and the narrow band of RRF scores left similarity to decide MMR.
- **Fix:** weighted RRF (k0=10, keyword at 0.5), min-max MMR relevance, fixed chunks by default
  ([ADR 0029](llm-wiki/adr/0029-weighted-rrf-min-max-mmr-fixed-chunks.md)). The ADR states the cost:
  tuned on the evaluation set itself, so the numbers are optimistic, and hybrid does not clearly
  beat plain dense.

### 4.7 Eval runner: judge input and pacing (#31, ADR 0027 update)

The first full runs found two holes in the runner (#26):

- **The judge did not see the answer's status or contradictions**, so a correct `conflicting`
  answer looked one-sided: 12 of 12 judged wrong. The judge prompt now carries both.
- **Pacing counted only uncached Haiku calls.** A rerun served by `llm_cache` made none, did not
  pause, and its searches burst past the Cohere query pool (20 requests/min): six questions
  abstained on `ThrottlingException`. The runner now also spaces searches 3 s apart.

### 4.8 Contradiction detection (#32, ADR 0025 update)

- **Caught by the full eval (#31):** contradiction recall 0.25. The model split one conflict into
  one `contradictions` entry per side, each citing one chunk; the validator drops contradictions
  with fewer than two citations, so all of them were dropped (5 of 12 contradictory questions);
  9 of 12 answers cited fewer than 2 documents.
- **Fix:** prompt and `final_answer` schema only, the validator rule stays: one entry per
  disagreement citing both sides; check every document on the same event before answering.
- **Measured:** contradiction recall 0.25 -> 0.67, precision 0.75 -> 1.00, overall judge
  0.74 -> 0.82 ([ADR 0025](llm-wiki/adr/0025-agent-loop-seeded-forced-deadline.md) update). Still
  missed: 4 contradictory questions answered from one document
  ([14 Known gaps](llm-wiki/14-known-gaps.md)).

### 4.9 Smaller ones found by live checks and reading the output

- **Acme generator invented facts** (#28, ADR 0026): the mechanical check proves planted facts are
  present, not that nothing else was invented. Reading the first run found invented times in
  INC-306 and STS-401 that contradicted other documents, and a gap (G03) filled in INC-201; their
  spec entries were pinned and the job rerun.
- **Haiku sent `claims` as a JSON string** in a live agent run (#27); the agent now decodes it
  instead of spending a step on a reprompt.
- **HNSW plus a strategy filter returned 21 of 40 rows** (#23, measured on a temp table); fixed
  with one partial index per strategy ([ADR 0024](llm-wiki/adr/0024-partial-hnsw-per-strategy-or-keyword-query.md)).

## 5. Guardrails: what is not left to the model

In the product (sourced in the ADRs named):

- **Citations are checked by code, not by the prompt.** `grounding.build_answer` drops claims that
  cite chunks not retrieved in this run and contradictions with fewer than two distinct valid
  citations (#14, [ADR 0005](llm-wiki/adr/0005-agent-loop-with-citation-validation.md)). Abstaining
  (`insufficient`) is preferred to guessing.
- **Documents are untrusted data.** Passages go to the model as JSON-escaped lines, tools are
  read-only (ADR 0025). Prompt-injection tests are built but not run yet (EVALUATION.md section 8).
- **Cost caps.** At most 6 agent steps, `k` <= 40, `get_document` cut at 8,000 characters, an 80 s
  deadline, reserved concurrency 4 on `api`, Postgres `llm_cache`, eval pacing (ADR 0025,
  ADR 0027). The account is a Free-plan project with $100 credits that closes instead of billing
  ([ADR 0011](llm-wiki/adr/0011-free-plan-aws-project.md)).
- **No secrets to leak.** No LLM API keys (IAM), no database password (IAM auth tokens,
  ADR 0021), the GitHub token in SSM SecureString.
- **The judge is another model family** (Qwen3 grading Claude), and gpt-oss is not the judge
  because it is the agent's fallback (ADR 0027). A hand spot-check of judge verdicts is still open
  (PLAN.md).

In the development process:

- `make check` on every PR, `cdk diff` posted on every PR, `verify` and `smoke` after every deploy.
- The PR diff build has only the read-only CDK lookup role (#1).
- Aurora has deletion protection and a snapshot removal policy, in its own stack so a code deploy
  cannot replace it ([ADR 0020](llm-wiki/adr/0020-data-stack-split-by-lifecycle.md), #13).
- IAM-changing deploys of the CI/CD stack are run by the owner by hand; Claude Code's auto mode
  refuses them ([llm-wiki/07](llm-wiki/07-infrastructure.md)).

## 6. What I changed or decided myself

TODO (author): this section is yours. Suggested topics:

- TODO (author): which architecture decisions were yours (e.g. the Free-plan AWS project, cloud
  only, no frameworks, the HotpotQA + Acme corpus split) and which came from AI proposals.
- TODO (author): which AI suggestions you rejected, and why.
- TODO (author): which modules or functions you rewrote or simplified by hand (e.g. `rank.py`,
  `grounding.py`, `agent.py`), and what you changed.
- TODO (author): how you reviewed each PR (what you read, what you ran, what you asked to change
  before merging).
- TODO (author): what you verified manually (the UI on the public URL, the deployed `POST /ask`,
  AWS console checks, the judge spot-check).
- TODO (author): the hand-written Acme spec (`data/acme/spec.json`): how much of it you wrote.
- TODO (author): what you did by hand in AWS (account setup, `aws login`, quota requests, the
  Anthropic use-case form, `make deploy-cicd`).
- TODO (author): what you would do differently with AI on the next project.
