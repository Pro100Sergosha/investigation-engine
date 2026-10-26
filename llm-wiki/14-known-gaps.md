---
title: Known gaps
status: current
last_updated: 2026-10-26
owner: Pro100Sergosha
---

# 14 Known gaps

What does not work yet, or works on a temporary arrangement. Remove an entry in the same commit
that closes it.

| Gap | Why | Closes when |
|---|---|---|
| A PDF page becomes one paragraph: paragraph boundaries inside a page are lost, so fixed and structured chunking behave alike on PDFs | pypdf rarely emits blank lines between paragraphs (`parsers._read_pdf`) | split on vertical gaps between lines (pypdf `visitor_text`) if PDF retrieval measurably suffers |
| DOCX tables, headers, footers and text boxes are not indexed | `parsers._read_docx` reads body paragraphs only | an Acme document keeps facts in a table |
| Branch protection is off: a red PR can be merged by hand | GitHub free plan offers it only on public repositories | the repository is made public (required for submission anyway) |
| Claude Haiku 4.5 limited to 10 requests/min per profile (`eu.*` and `global.*`); an eval sweep (three answer runs) takes ~50 min | Bedrock quota of a new account ([ADR 0017](adr/0017-bedrock-claude-haiku-llm.md) update) | the account-level increase to 10,000 is approved |
| Query embeddings share the Cohere `eu.*` pool (20 requests/min) with the bulk load: search and eval during a load are throttled and slow | one pool per profile ([ADR 0022](adr/0022-cohere-embed-v4-batched.md)) | accepted: never run a load and an eval at once; `global.*` adds a second pool if needed |
| A full reload costs ~11M of the pool's 16.2M tokens/day: at most one full reload per day | Cohere daily token quota | accepted; a second reload waits a day |
| Failed `ingest` events wait in `IngestFailures` until someone runs `make redrive-ingest` (kept 14 days); nothing alerts | no CloudWatch alarm (cost rule) | accepted: check the queue depth after a bulk load or a failed upload |
| Schema changes are additive only (`IF NOT EXISTS`); a new index over a loaded table holds the deploy for minutes | schema applied by a custom resource on deploy ([ADR 0021](adr/0021-aurora-express-iam-auth.md)) | accepted; a destructive change gets a one-off job |
| `concurrent_build_limit=1` on `investigation-deploy` is in the code but not deployed: merges in quick succession still race (2026-10-24: ECR "tag is immutable", a stack deployed before the stack it imports from) | `Investigation-Cicd-prod` is deployed only by hand | the owner runs `make diff-cicd` + `make deploy-cicd`; until then merge one PR at a time |
| The database endpoint is public (internet access gateway) | the Free plan creates Aurora only with express configuration ([ADR 0021](adr/0021-aurora-express-iam-auth.md)) | accepted: IAM-only auth, TLS, no password exists |
| Old paid account `788607671121` still exists, no budget on it | abandoned in favour of the Free-plan project ([ADR 0011](adr/0011-free-plan-aws-project.md)) | closed in the console, or a budget alert added |
| No SSE streaming of answers | not supported on Python Lambda Function URLs ([ADR 0008](adr/0008-function-url-not-api-gateway.md)) | accepted, listed as future work |
| Search latency from the Lambda and the cost of OR keyword queries over the full corpus are not measured (laptop: dense 0.7 s, hybrid 1.0 s, mmr 1.1 s, mostly network) | measured before the bulk load, from Tbilisi | measured after the bulk load |
| The prompt cache misses the first agent call and the forced last one: the system prompt + tools (~1.5k tokens) are below Haiku 4.5's 4,096-token minimum, and the forced step changes the tool list, so it pays full price for the whole history (~12k tokens in a 6-step run) | Claude's cache minimum; forcing `final_answer` by the tool list ([ADR 0025](adr/0025-agent-loop-seeded-forced-deadline.md)) | accepted: steps 3-6 of a run read the history from the cache (measured ~35% cheaper per question) |
| When both Haiku pools fail, answers silently come from gpt-oss-120b; when `eu.*` fails, questions are processed in the `global.*` pool, possibly outside the EU | `llm.py` falls back `eu.*` -> `global.*` -> gpt-oss ([ADR 0028](adr/0028-haiku-global-pool-before-gpt-oss.md)) | accepted: the trace and the eval record `model` per call; real customer data would drop `global.*` |
| A resuming database can still push `POST /ask` past the api Lambda's 90 s (502 instead of an answer); a throttled query embedding fails within ~13 s and the question abstains | `db.connect` waits up to ~60 s ([ADR 0025](adr/0025-agent-loop-seeded-forced-deadline.md)); `embed_query` has its own bounded client ([ADR 0028](adr/0028-haiku-global-pool-before-gpt-oss.md)) | warm the database before a demo; never run a bulk load during a demo |
| One bad line in a JSONL shard skips the whole shard | `parsers.read_jsonl` raises on the first bad line, `ingest` skips the file ([04](04-api-contract.md#ingest)) | a shard fails in practice; then skip per line in `read_jsonl` |
| The Function URL has no auth: anyone with the URL can upload and `DELETE` documents | `auth_type=NONE` ([ADR 0008](adr/0008-function-url-not-api-gateway.md)) | the custom domain with a secret header (planned 2026-10-28) |
| Judge correctness is one model's opinion (Qwen3-235B); its agreement with a human is unmeasured | LLM-as-judge ([ADR 0027](adr/0027-eval-runner-retrieval-sweep-qwen-judge.md)) | ~10 verdicts are checked by hand and the agreement is reported in EVALUATION.md |
| A cold first request can get 502 instead of 503: `db.connect` may wait longer than the api Lambda's 90 s | resume retries in `db.connect` ([ADR 0021](adr/0021-aurora-express-iam-auth.md)) | warm the database before a demo; accepted |
| Contradiction recall is 0.67 (`agent`, 8 of 12): 4 contradictory questions are still answered from one document (an incident report against a status page or a later report) | the agent reads the first source that answers; the prompt asks to check every document on the event, the model does not always do it ([09](09-evaluation.md#results), [ADR 0025](adr/0025-agent-loop-seeded-forced-deadline.md) update) | accepted for the MVP; next step: a server-side second search for the asked fact excluding the cited document before `final_answer` |
| 5 of 72 `agent` answers need a reprompt (16 with the prompt of #31): Haiku sends `final_answer.claims` as a string with tool-call markup instead of a list | model output; the agent reprompts on a malformed answer ([ADR 0025](adr/0025-agent-loop-seeded-forced-deadline.md)) | accepted: the reprompt recovers it at the cost of one more call; a tighter tool schema if it starts losing answers |
