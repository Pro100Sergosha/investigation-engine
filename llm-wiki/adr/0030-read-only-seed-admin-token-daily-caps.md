---
title: Read-only seed corpus, admin token from SSM, daily caps on the public API
status: accepted
date: 2026-10-26
supersedes: 0008 (protection only: "reserved concurrency plus the budget alert")
superseded_by: none
---

# ADR 0030: Read-only seed corpus, admin token from SSM, daily caps on the public API

## Context

The Function URL is public with auth `NONE` ([ADR 0008](0008-function-url-not-api-gateway.md)),
and the only protection was reserved concurrency 4 on `api` plus the budget alert. On the live
demo anyone could:

- `DELETE /documents/{id}` any of the 66k seed documents (HotpotQA + Acme), or overwrite an Acme
  document by uploading a file with its name (`make acme-load` stored them through `uploads/` as
  `upload:acme-*`, the same sources a UI upload produces);
- loop `POST /ask`: reserved concurrency limits how *fast* credits burn, not how *much*. Four
  parallel questions at ~$0.016 each, bounded only by Haiku's 10 requests/min per pool (two
  pools, plus gpt-oss behind them): ~20 calls a minute at ~$0.007 is over $100 a day in theory,
  and the account has $100 in all;
- upload many large files, each embedded with Cohere (the presigned PUT had no size limit).

Reviewers of the take-home must still add, update and delete documents through the UI, so
writes cannot simply be closed, and there are no user accounts to tell a reviewer from anyone
else.

## Decision

Three small rules in `handlers.py`, no new AWS service:

1. **The seed corpus is read-only through the public API.** A document is seed when its
   `source` does not start with `upload:` (HotpotQA, `hotpotqa:*`, from `bulk/` shards) or starts
   with `upload:acme-` (the Acme files). `DELETE /documents/{id}` of a seed document is 403, and
   `POST /documents/upload-url` refuses file names starting with `acme-` (403), which is the
   only way an upload could map to an existing seed source (`ingest` prefixes every uploaded
   source with `upload:`, and an uploaded JSONL shard's lines with `upload:<file>:`). Every
   other upload stays updatable and deletable by anyone, as before. The rule reads existing
   data: no `seed` column, no backfill of 66k rows inside a deploy.
2. **Admin bypass with a secret header.** `x-admin-token` is compared with `hmac.compare_digest`
   against the SSM SecureString `/investigation/admin-token` (random 32 bytes, created once with
   the CLI, AWS managed key `aws/ssm`). The api reads it once per container, only when a request
   carries the header; the value is never logged (the log line has `admin: true/false`), never
   in an env var (only the parameter *name* is, `ADMIN_TOKEN_PARAM`) or the image. The admin can
   delete or re-upload seed documents and is not refused by the daily caps.
3. **Daily caps per UTC day, in Postgres.** Table `daily_usage (day, counter, n)`, one row per
   day and counter, written through `db.run` with parameterized SQL:
   - `ask_llm_calls`: Bedrock calls of `POST /ask` that missed `llm_cache` (a cached call costs
     nothing and is not counted). Checked before the agent runs, added after it. At 150 the
     api answers 429 `{"error": ...}` until 00:00 UTC. 150 calls is ~65 questions at the
     measured 2.3 calls per question, ~$1 a day; the worst case (6-step runs over long chunks)
     is ~$5 a day.
   - `uploads`: upload URLs handed out, 50 a day, one atomic `INSERT ... ON CONFLICT DO UPDATE
     ... RETURNING n`; over the cap is 429.
   - **Upload size**: the request now carries `size` (1 byte - 5 MB, else 400) and the
     presigned PUT signs `Content-Length`, so S3 refuses a body of any other size. A presigned
     PUT has no size range; the browser sets the header from the file, the page sends no
     custom header.

Reserved concurrency 4 on `api` stays (account quota 400, 394 unreserved, checked with
`aws lambda get-account-settings` on 2026-10-26): it caps how fast, the daily caps cap how much.

## Consequences

- The worst a stranger can do in a day: delete or overwrite other people's uploads, spend
  ~$1-5 of Haiku, and upload 50 files of 5 MB (~$0.3 of Cohere each in the worst case of dense
  text, usually far less: PDF and DOCX bytes are mostly not text). At that rate the $100 lasts
  weeks, not hours.
- One more SELECT before every question and one upsert after it (~ms against a warm cluster).
- The caps are global, not per visitor: one abuser uses up the day for every reviewer. The 429
  message says when it resets; the author can still demo with the admin header.
- Questions running when the cap is reached finish (at most 4 at once) and overshoot it a
  little. If a connection dies after the upsert ran, `db.run`'s retry counts it twice: the cap
  errs on the safe side.
- The seed rule is a naming convention: a future seed corpus loaded through `uploads/` needs
  its own reserved prefix in `_is_seed`. A reviewer cannot use a file name starting with
  `acme-` (a different case, `ACME-...`, is a different key and source and works).
- The UI cannot send the admin header; the admin uses `curl -H "x-admin-token: ..."`.
- Rotating the token: `aws ssm put-parameter --overwrite`, then a new container must start (a
  deploy, or wait until the warm ones are recycled).

## Alternatives considered

**Custom domain behind a Cloudflare Worker that adds a secret header** (the plan for
2026-10-28): hides the Function URL and lets the Worker rate-limit per IP. It does not by itself
protect the seed corpus (the Worker forwards every visitor's DELETE), it needs a domain and a
second platform the interview must explain, and the raw Function URL stays reachable unless the
api checks the header, which is the same code as the admin token. Still useful later for a
custom domain and per-IP limits; it can be added on top.

**Function URL auth `AWS_IAM`**: real authentication, but every request must be SigV4-signed.
The browser page has no AWS credentials; Cognito identity pools to hand them out are a service
and a sign-in flow more, and reviewers would need accounts.

**API Gateway with usage plans and API keys**: per-key throttling and daily quotas out of the
box, but the 30 s integration timeout breaks `/ask` (ADR 0008), an API key in a public page is
not a secret, and usage plans are REST API only (more expensive, more resources).

**AWS WAF rate-based rules**: per-IP limits, but WAF attaches to CloudFront or API Gateway,
not to a Function URL, and costs $5 a month per web ACL plus rules: real money from the
credits for a demo.

**A `seed boolean` (or `origin`) column**: explicit, but needs `ALTER TABLE ... ADD COLUMN` and
an `UPDATE` of 66k rows inside the deploy's schema transaction (minutes holding the custom
resource and locking `documents`), while the `source` already says the same.

**A cutoff on `id` or `created_at`** ("everything stored before the freeze is seed"): no naming
rule, but a magic number from production that is wrong after any reload, and it does not stop
re-uploading an Acme file name (the update keeps the old id).

**Lower reserved concurrency (1-2) without a daily cap**: free and one line, but it still lets
a loop run all day; and one slow question would block page loads.

**Per-IP counters in Postgres**: fairer than a global cap, but IPs rotate cheaply, the table
grows with every visitor, and it is more code for a demo that lives a few weeks.

**Presigned POST with a `content-length-range` policy** instead of a signed `Content-Length`:
the standard way to bound an upload's size without knowing it in advance, but the page would
switch from a raw `PUT` to a multipart form and the bucket CORS to `POST`; the browser knows the
exact size anyway.
