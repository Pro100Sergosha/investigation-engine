.DEFAULT_GOAL := help
.PHONY: help install lint fmt test check synth diff diff-pr deploy verify smoke dataset dataset-stats schema diff-cicd deploy-cicd bootstrap

# CLI pinned here, library pinned in uv.lock. npx downloads it once and caches it.
CDK := npx --yes aws-cdk@2.1146.1

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

test:  ## Run tests
	uv run pytest -q

check: lint test synth  ## Everything CI runs before a deploy

synth:  ## Synthesize CloudFormation templates (no AWS calls)
	cd cdk && $(CDK) synth --quiet

diff:  ## Show what a deploy would change. Read it before deploying.
	cd cdk && $(CDK) diff Investigation-prod

diff-pr:  ## Read-only diff for PR builds (template compare via the lookup role, no change set)
	cd cdk && $(CDK) diff Investigation-prod --method=template

deploy:  ## Deploy the application stack (CodeBuild does this on push to main)
	cd cdk && $(CDK) deploy Investigation-prod --require-approval never

verify:  ## Fail if the deployed application stack differs from the code
	cd cdk && $(CDK) diff Investigation-prod --fail

smoke:  ## Smoke-check /health on the deployed Function URL
	curl --fail --silent --show-error "$$(aws cloudformation describe-stacks 	  --stack-name Investigation-prod 	  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)health"

# Jobs: run in CodeBuild investigation-jobs (TARGET=<target>), which sets BUCKET, CLUSTER_ARN,
# SECRET_ARN and DB_NAME. They read only shell variables, so they also run anywhere those are set.
dataset:  ## Job: HotpotQA -> dedup -> JSONL shards in s3://$BUCKET/bulk/ (ingest loads them)
	uv run python scripts/dataset.py --bucket $$BUCKET

dataset-stats:  ## Job: dataset counts and dedup stats only, writes nothing
	uv run python scripts/dataset.py --bucket $$BUCKET --dry-run

schema:  ## Job: apply sql/schema.sql (deploys do this already; for repairs)
	uv run python scripts/schema.py --cluster-arn $$CLUSTER_ARN --secret-arn $$SECRET_ARN --database $$DB_NAME

diff-cicd:  ## Show what deploy-cicd would change
	cd cdk && $(CDK) diff Investigation-Cicd-prod

deploy-cicd:  ## By hand only: deploy the CodeBuild projects (read diff-cicd first)
	cd cdk && $(CDK) deploy Investigation-Cicd-prod --require-approval never

bootstrap:  ## One-time: CDK bootstrap of the account/region
	cd cdk && $(CDK) bootstrap aws://988277499209/eu-north-1
