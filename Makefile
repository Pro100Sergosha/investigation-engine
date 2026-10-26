.DEFAULT_GOAL := help
.PHONY: help install lint fmt test check synth diff diff-pr deploy verify smoke dataset dataset-stats acme acme-labels acme-load redrive-ingest eval diff-cicd deploy-cicd bootstrap

# CLI pinned here, library pinned in uv.lock. npx downloads it once and caches it.
CDK := npx --yes aws-cdk@2.1146.1
# Deployed by CodeBuild on merge, data first (Investigation-prod imports its exports, ADR 0020).
STACKS := Investigation-Data-prod Investigation-prod

# Locally use the `aws login` profile; in CodeBuild credentials come from the project role.
ifndef CI
export AWS_PROFILE := investigation
endif

help:  ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install:  ## Create the virtualenv with all dependencies
	uv sync

lint:  ## Lint and check formatting
	uv run ruff check .
	uv run ruff format --check .

fmt:  ## Format and apply safe lint fixes
	uv run ruff format .
	uv run ruff check --fix .

# Fake credentials: boto3 clients are created at import (once per cold start) and resolve
# credentials then; the `aws login` profile would need botocore[crt] for that. Tests never call
# AWS, and with fake keys an accidental call fails instead of touching the real account.
test: export AWS_ACCESS_KEY_ID := test
test: export AWS_SECRET_ACCESS_KEY := test
test:  ## Run tests
	uv run pytest -q

check: lint test synth  ## Everything CI runs before a deploy

synth:  ## Synthesize CloudFormation templates (no AWS calls)
	cd cdk && $(CDK) synth --quiet

diff:  ## Show what a deploy would change. Read it before deploying.
	cd cdk && $(CDK) diff $(STACKS)

diff-pr:  ## Read-only diff for PR builds (template compare via the lookup role, no change set)
	cd cdk && $(CDK) diff $(STACKS) --method=template

deploy:  ## Deploy the data and application stacks (CodeBuild does this on push to main)
	cd cdk && $(CDK) deploy $(STACKS) --require-approval never

verify:  ## Fail if a deployed data or application stack differs from the code
	cd cdk && $(CDK) diff $(STACKS) --fail

# /documents proves the database path on every deploy. A paused cluster resumes on the first
# connection (the api waits for it); if it still answers 503, curl retries (it treats 503 and
# timeouts as transient).
smoke:  ## Smoke-check /health and the database path (/documents) on the deployed Function URL
	url="$$(aws cloudformation describe-stacks --stack-name Investigation-prod \
	  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)" && \
	curl --fail --silent --show-error "$${url}health" && echo && \
	curl --fail --silent --show-error --max-time 100 --retry 3 --retry-delay 15 \
	  "$${url}documents?limit=1" && echo

# Jobs: run in CodeBuild investigation-jobs (TARGET=<target>), which sets BUCKET, DB_HOST,
# DB_NAME, INGEST_FAILURES_QUEUE and INGEST_FUNCTION. They read only shell variables, so they
# also run anywhere those are set.
dataset:  ## Job: HotpotQA -> dedup -> JSONL shards in s3://$BUCKET/bulk/ (ingest loads them)
	uv run python scripts/dataset.py --bucket $$BUCKET

dataset-stats:  ## Job: dataset counts and dedup stats only, writes nothing
	uv run python scripts/dataset.py --bucket $$BUCKET --dry-run

acme:  ## Job: Acme corpus from data/acme/spec.json (Haiku), checked, to s3://$BUCKET/jobs/acme/
	uv run python -u scripts/gen_acme.py --bucket $$BUCKET

# Fake keys as in `test`: importing engine.llm creates a boto3 client, and no call is made.
acme-labels: export AWS_ACCESS_KEY_ID := test
acme-labels: export AWS_SECRET_ACCESS_KEY := test
acme-labels:  ## Rewrite data/acme/GROUND_TRUTH.md and questions.jsonl from the spec (no AWS)
	uv run python scripts/gen_acme.py --labels-only

# Through uploads/, exactly like a UI upload: ingest stores each file as upload:<file name>.
acme-load:  ## Job: copy data/acme/files/ to s3://$BUCKET/uploads/ (ingest indexes them)
	aws s3 cp data/acme/files/ s3://$$BUCKET/uploads/ --recursive

redrive-ingest:  ## Job: rerun the ingest events in the IngestFailures queue (Lambda gave up)
	uv run python scripts/redrive_ingest.py --queue-url $$INGEST_FAILURES_QUEUE --function $$INGEST_FUNCTION

# CONFIG: retrieval | embeddings (no LLM) | agent | agent-structured | single-shot |
# agent-gpt-oss; LIMIT=N for a dry run.
eval:  ## Job: run the eval set in CONFIG -> s3://$BUCKET/jobs/eval/<config>.json
	uv run python -m eval.run --config $(CONFIG) --bucket $$BUCKET $(if $(LIMIT),--limit $(LIMIT))

diff-cicd:  ## Show what deploy-cicd would change
	cd cdk && $(CDK) diff Investigation-Cicd-prod

deploy-cicd:  ## By hand only: deploy the CodeBuild projects (read diff-cicd first)
	cd cdk && $(CDK) deploy Investigation-Cicd-prod --require-approval never

bootstrap:  ## One-time: CDK bootstrap of the account/region
	cd cdk && $(CDK) bootstrap aws://988277499209/eu-north-1
