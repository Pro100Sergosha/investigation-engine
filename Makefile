.DEFAULT_GOAL := help
.PHONY: help install lint fmt test check synth diff deploy verify smoke diff-cicd deploy-cicd bootstrap

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

deploy:  ## Deploy the application stack (CodeBuild does this on push to main)
	cd cdk && $(CDK) deploy Investigation-prod --require-approval never

verify:  ## Fail if the deployed application stack differs from the code
	cd cdk && $(CDK) diff Investigation-prod --fail

smoke:  ## Smoke-check /health on the deployed Function URL
	curl --fail --silent --show-error "$$(aws cloudformation describe-stacks 	  --stack-name Investigation-prod 	  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl'].OutputValue" --output text)health"

diff-cicd:  ## Show what deploy-cicd would change
	cd cdk && $(CDK) diff Investigation-Cicd-prod

deploy-cicd:  ## By hand only: deploy the CodeBuild projects (read diff-cicd first)
	cd cdk && $(CDK) deploy Investigation-Cicd-prod --require-approval never

bootstrap:  ## One-time: CDK bootstrap of the account/region
	cd cdk && $(CDK) bootstrap aws://988277499209/eu-north-1
