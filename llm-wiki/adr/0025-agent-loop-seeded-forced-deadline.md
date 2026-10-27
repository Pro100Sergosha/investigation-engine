---
title: The agent loop: seeded search, forced final answer, own deadline, citable documents
status: accepted
date: 2026-10-26
supersedes: none
superseded_by: none
---

# ADR 0025: The agent loop: seeded search, forced final answer, own deadline, citable documents

## Context

ADR 0005 decided on an own tool-calling loop (`search`, `get_document`, `final_answer`) with a
step cap and server-side citation checks, but not how the loop behaves at its edges. These facts
shape it:

- Claude Haiku 4.5 allows **10 requests/min** (ADR 0017 update): every LLM call per question
  counts, in the eval sweep most of all.
- `POST /ask` runs in the `api` Lambda, which times out at **90 s**. A single `llm.converse` used
  to be unbounded in the worst case: 4 attempts x (5 s connect + 30 s read) + 7-10 s of waits,
  then the same again on gpt-oss-120b (ADR 0023): about 290 s.
- gpt-oss-120b, the fallback, **accepts Converse `toolChoice` but ignores it** (measured
  2026-10-26: forced to `final_answer`, it still called `search`; offered only `final_answer`, it
  called it). It also accepts a forced turn whose history holds a `search` toolUse that is no
  longer offered; so does Haiku.
- Haiku caches only prefixes of >= 4,096 tokens; the system prompt plus tools is ~1.5k, but the
  history passes 4k after one or two searches.
- The eval compares `max_steps=1` (single-shot RAG) with the loop (PLAN.md section 4).
- The Function URL has no auth, so anyone with the link can make the api spend Bedrock credits.

## Decision

`agent.ask(question, strategy="structured", mode="mmr", max_steps=6)` in `src/engine/agent.py`:

- **Seeded search.** Before the first LLM call the server runs `search.search(question, k=8)`
  with the run's `strategy` and `mode` and puts the hits into the first user message. That saves
  the call in which the model would only ask for this search, and `max_steps=1` is then
  single-shot RAG with no special case.
- **Tools.** `search(query, k)`: k defaults to 8, any int is clamped to 1..40
  (`search.CANDIDATES`), anything else becomes 8. `get_document(document_id)`: the document's
  chunks of the current strategy in order (`search.document_chunks`), cut at 8,000 characters
  (~2k tokens), each with its chunk id, so its text is citable like a search result.
  `final_answer(claims, contradictions, answer, status)` with a JSON schema;
  `grounding.build_answer` validates it. Citable = every chunk id the seed search, a `search`
  call or a `get_document` call showed in this run.
- **Forced final answer.** The last allowed step offers only `final_answer` and sets
  `toolChoice: {"tool": {"name": "final_answer"}}`. Offering only that tool is what makes it work
  on gpt-oss; `toolChoice` makes Haiku skip its preamble text. `llm.converse(tool_choice=...)`
  puts it into `toolConfig`, and into the cache key only when set, so existing `llm_cache` rows
  keep their keys.
- **Own deadline, 80 s.** `ask` sets `deadline = start + 80 s` and passes it to
  `llm.converse`. `llm.ATTEMPT_SECONDS = 35` is the longest one attempt can take (connect 5 +
  read 30). Rules:
  - the agent starts an LLM call only if >= 35 s remain, otherwise it stops and abstains;
  - with < 45 s left (one attempt + 10 s for a search) the call is forced to `final_answer`;
  - inside `llm`, a retry starts only if wait + 1 s jitter + 35 s still fit before the deadline,
    and the fallback only if 35 s fit.

  Worst case: the last call starts at t = 45 s with 35 s left and ends by t = 80 s, with no retry
  or fallback after it. The handler then reads the cited chunks (one indexed query) and answers
  inside the 10 s left of the Lambda's 90 s. The deadline bounds the LLM, not search:
  `embed_query` uses botocore's adaptive retries (up to 10 attempts) and `db.connect` waits up to
  ~60 s for a resuming cluster. A search that overruns makes the next step see too little time
  and abstain, but it can still push the request past 90 s
  ([14 Known gaps](../14-known-gaps.md)).
- **Reprompt policy (each costs a step).** Text instead of a tool call: the text is kept and a
  user turn asks for tool calls. A `final_answer` that `build_answer` rejects (ValueError): the
  error goes back in its `toolResult`. Errors are written in the result text, not Converse's
  `status: "error"`, which is documented for Claude only while the same history may go to
  gpt-oss. A reply cut off before any block (`max_tokens`): no empty assistant turn is appended
  (Converse rejects it); a nudge is added to the last user turn, which also changes the cache key.
  Measured live: Haiku sometimes sends `claims` as a string holding the JSON list. The agent
  decodes such strings before validation instead of spending a step on a reprompt.
- **Errors.** A `ClientError` or `BotoCoreError` that escapes `llm` (or `embed`) ends the run
  as `insufficient` with the error in the trace and one log line, never a 500. Database errors
  propagate (the handler answers 503 while the cluster resumes).
- **Prompt.** A short system prompt: split multi-part questions into sub-searches, compare
  sources on dates, times, causes and numbers, report contradictions with >= 2 chunks from
  different documents, abstain instead of guessing, keep `answer` to a few words for EM/F1.
  Passages are untrusted data. Each passage goes to the model as one JSON object per line
  (`json.dumps`): quotes and newlines in a document are escaped, so a document cannot close its
  passage and pose as the conversation. The real defence is mechanical: tools are read-only and
  `build_answer` drops citations of chunks that were never shown.
- **Prompt caching of the history.** `llm.converse(cache_history=True)` adds a second Claude
  `cachePoint` after the last message (on a copy, the history and the cache key stay as they
  are). The agent sets it on every call except the forced last one: nothing reads that cache
  afterwards, and changing the tool list invalidates it anyway.
- **Reserved concurrency 4 on `api`.** It caps what an unauthenticated flood of `POST /ask` can
  spend (gpt-oss, Cohere query embeddings; Haiku is capped by its quota anyway) and the database
  connections. Requests beyond it get 429, which the page reports as "busy".
- **Log line.** `POST /ask` adds `answer_status`, `llm_steps`, `models`, `input_tokens`,
  `output_tokens`, `prompt_cache_read_tokens` and `llm_cache_hits` to the request's JSON line.

## Consequences

- Measured on 2026-10-26 against the deployed corpus (66,555 HotpotQA documents) from the
  laptop: a bridge question took 6 Haiku calls and 34.7 s, `answered` with the right
  citations. From step 3 on, the history was read from the prompt cache (6.4k, 9.0k, 11.4k
  tokens). Cost about $0.041 instead of $0.064 without the history cache point. A comparison
  question with `max_steps=2` took 2 calls, 12.7 s, ~$0.009, `answered` "yes".
- `max_steps=1` and the agent share one code path, so the eval compares like with like.
- The deadline makes the 90 s limit hold for the LLM part by construction, and the rule fits in
  one sentence. The price: a call that cannot start with 35 s left is not made at all, even
  though a typical call takes 2-3 s. Under heavy throttling the agent abstains rather than
  risk a timeout.
- The forced step changes the tool list, so it never reads the prompt cache: it pays full input
  price for the whole history (11.9k tokens in the measured run).
- No token counter: the budget per question is the step cap, k <= 40 and the 8,000-character
  document cap. Worst case (five searches of 40 long chunks) is ~60k tokens on the last step and
  ~$0.2 per question.
- Decoding string-encoded `claims` is a small leniency in front of a strict validator. A string
  that is not valid JSON still goes back to the model.
- The search part of the deadline is open (see above). Closing it needs an `embed.py` change:
  a query client with bounded retries and a short read timeout.

## Alternatives considered

**Let the model make the first search**: the textbook loop, but one more Haiku call per
question at 10 requests/min, and single-shot RAG would need its own code path.

**Force only with `toolChoice` and keep all tools on the last step**: the tools + system prefix
stays the same, which would keep its cache point valid. But gpt-oss ignores `toolChoice`, so
after a fallback the "final" step would call `search` and the run would end without an answer.
The right call if the fallback model ever honours `toolChoice`.

**A hard timeout around the whole run** (`signal.alarm`, or a worker thread with
`future.result(timeout)`): it would bound search too. The alarm raises at an arbitrary point,
possibly in the middle of a pg8000 exchange on the shared connection, which the next request
would then reuse broken. A thread that times out keeps running and shares the same connection.
Both trade a clear rule for hard-to-reproduce bugs.

**Raise the api timeout towards Lambda's 15 minutes**: no deadline logic, but the user waits
minutes in the worst case, and the page and the deploy smoke check are built around 90 s.

**`get_document` as context only, not citable**: no helper needed, but a fact read there could
not be cited, and the model would cite a nearby search chunk instead, which grounding cannot
tell apart from a real citation.

**Plain-text delimiters (`<passage>...</passage>`)**: easier to read, but a document containing
the closing tag ends its passage early. JSON escaping gives the same structure without that
hole.

## Update 2026-10-26

The full eval (llm-wiki/09) found the contradiction output broken in practice: the model wrote
each side of a conflict as its own `contradictions` entry citing one chunk, `grounding` dropped
every such entry (it wants >= 2 distinct citations, ADR 0005), and the answer came back
`answered` or `insufficient` (5 of 12 contradictory questions); the agent also answered from the
first source (9 of 12 cited fewer than 2 documents). Contradiction recall was 0.25.

The validator rule stays (one chunk cannot contradict itself). The prompt and the tool schema
now say what a contradiction is: one entry per disagreement, its text names each value and its
document, its citations come from both sides; before answering, check what every document on
the same event says about the asked fact; for status `conflicting` the short answer lists the
values. The prompt's example is a neutral "1998 or 2001", not a value from the question set.

Measured on the next `agent` run: contradiction recall 0.25 -> 0.67, precision 0.75 -> 1.00,
judge on contradictory questions 0.08 -> 0.58, overall judge 0.74 -> 0.82, no contradiction
dropped by `grounding`, no answerable question flagged `conflicting`. Cost $0.38 for 72
questions (was $0.41), p95 latency 45.6 s (was 40.0 s).

## Update 2026-10-26 (cost)

The costs above ($0.38, was $0.41) left out Bedrock prompt-cache tokens (ADR 0027 update of
the same date). Repriced from the committed traces, the current `agent` run cost $1.16 for 72
questions (~$0.016 per question); the $0.41 run is not recomputable and was higher than quoted.

## Update 2026-10-27 (prompt injection)

An audit for the prompt-injection tests (EVALUATION.md section 8) confirmed the fencing as
decided: every passage, `title` included, reaches the model as an escaped JSON line, server
notes stay outside it, and the system prompt names passages as untrusted data. Nothing was
changed without a measured failure. `grounding.build_answer` now also lists the citations it
removed (`dropped_citations` in its trace entry), so the eval can see a model citing a chunk
an injection named but the run never showed. The residual risk is a model that believes an
injected sentence and cites the injected chunk for it: grounding cannot tell that apart from a
real fact. The injection eval (8 questions, six overt injection styles, the injected chunk in the seed search of each) found nothing followed: 8/8 resisted, $0.09.
