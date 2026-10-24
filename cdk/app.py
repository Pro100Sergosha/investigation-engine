"""CDK app: two stacks in account 988277499209, eu-north-1.

Investigation-Github-prod  OIDC trust for GitHub Actions. Deployed once by hand: make deploy-github.
Investigation-prod         The application. Deployed by CI on every push to main: make deploy.
"""

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from constructs import Construct

ROOT = Path(__file__).resolve().parent.parent
ENV = cdk.Environment(account="988277499209", region="eu-north-1")
GITHUB_OWNER, GITHUB_REPO = "Pro100Sergosha", "investigation-engine"


class GithubStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        provider = iam.OidcProviderNative(
            self,
            "GithubOidc",
            url="https://token.actions.githubusercontent.com",
            client_ids=["sts.amazonaws.com"],
        )
        # Newer repos get immutable subject claims with numeric ids (owner@123/repo@456),
        # older ones the classic form. Both are pinned to main only.
        role = iam.Role(
            self,
            "DeployRole",
            role_name="investigation-deploy",
            max_session_duration=cdk.Duration.hours(1),
            assumed_by=iam.WebIdentityPrincipal(
                provider.oidc_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                    },
                    "StringLike": {
                        "token.actions.githubusercontent.com:sub": [
                            f"repo:{GITHUB_OWNER}/{GITHUB_REPO}:ref:refs/heads/main",
                            f"repo:{GITHUB_OWNER}@*/{GITHUB_REPO}@*:ref:refs/heads/main",
                        ]
                    },
                },
            ),
        )
        # The role can do nothing itself except assume the CDK bootstrap roles,
        # which is all `cdk deploy` needs.
        role.add_to_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[f"arn:aws:iam::{self.account}:role/cdk-hnb659fds-*"],
            )
        )
        cdk.CfnOutput(self, "DeployRoleArn", value=role.role_arn)


class AppStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        api = lambda_.DockerImageFunction(
            self,
            "Api",
            code=lambda_.DockerImageCode.from_image_asset(str(ROOT), cmd=["engine.handlers.api"]),
            architecture=lambda_.Architecture.X86_64,
            memory_size=1024,
            timeout=cdk.Duration.seconds(90),
        )
        url = api.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)
        cdk.CfnOutput(self, "ApiUrl", value=url.url)


app = cdk.App()
cdk.Tags.of(app).add("Project", "investigation-engine")
GithubStack(app, "Investigation-Github-prod", env=ENV)
AppStack(app, "Investigation-prod", env=ENV)
app.synth()
