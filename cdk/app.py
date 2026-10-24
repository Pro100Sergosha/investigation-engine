"""CDK app: two stacks in account 988277499209, eu-north-1.

Investigation-Cicd-prod  CodeBuild PR diff + deploy on main. Deployed by hand: make deploy-cicd.
Investigation-prod       The application. Deployed by CodeBuild on every push to main.
"""

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_codebuild as codebuild
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from constructs import Construct

ROOT = Path(__file__).resolve().parent.parent
ENV = cdk.Environment(account="988277499209", region="eu-north-1")
GITHUB_OWNER, GITHUB_REPO = "Pro100Sergosha", "investigation-engine"
GITHUB_OWNER_ID = "139613549"  # numeric GitHub user id, for the webhook actor filter
# Created once with the CLI and confirmed in the console (the GitHub handshake cannot be IaC).
CONNECTION_ARN = (
    "arn:aws:codeconnections:eu-north-1:988277499209:connection/"
    "f4261920-5155-419e-a77d-a46964caa408"
)
GITHUB_TOKEN_PARAM = "/investigation/github-token"  # SecureString, PR comments only


class CicdStack(cdk.Stack):
    """CodeBuild projects triggered by GitHub webhooks through CodeConnections.

    GitHub OIDC is impossible here: the Free-plan SCP denies iam:*Provider* (ADR 0012).
    Buildspecs live in .codebuild/, so changing a build needs no redeploy of this stack.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)
        pr_diff = self._project(
            "PrDiff",
            "investigation-pr-diff",
            ".codebuild/pr-diff.yml",
            codebuild.FilterGroup.in_event_of(
                codebuild.EventAction.PULL_REQUEST_CREATED,
                codebuild.EventAction.PULL_REQUEST_UPDATED,
                codebuild.EventAction.PULL_REQUEST_REOPENED,
            ).and_base_ref_is("^refs/heads/main$"),
            privileged=False,
            # PR code is untrusted: read-only lookup role only, enough for `cdk diff
            # --method=template`. No change sets, no asset publishing, no deploy.
            assume_roles=["lookup"],
        )
        pr_diff.add_to_role_policy(
            iam.PolicyStatement(
                actions=["ssm:GetParameter", "ssm:GetParameters"],
                resources=[
                    f"arn:aws:ssm:{self.region}:{self.account}:parameter{GITHUB_TOKEN_PARAM}"
                ],
            )
        )
        deploy = self._project(
            "Deploy",
            "investigation-deploy",
            ".codebuild/deploy.yml",
            codebuild.FilterGroup.in_event_of(codebuild.EventAction.PUSH).and_head_ref_is(
                "^refs/heads/main$"
            ),
            privileged=True,  # docker build of the Lambda image
            assume_roles=["lookup", "deploy", "file-publishing", "image-publishing"],
        )
        deploy.add_to_role_policy(
            iam.PolicyStatement(
                actions=["cloudformation:DescribeStacks"],
                resources=[
                    f"arn:aws:cloudformation:{self.region}:{self.account}:stack/Investigation-prod/*"
                ],
            )
        )

    def _project(
        self,
        construct_id: str,
        name: str,
        buildspec: str,
        filters: codebuild.FilterGroup,
        privileged: bool,
        assume_roles: list[str],
    ) -> codebuild.Project:
        project = codebuild.Project(
            self,
            construct_id,
            project_name=name,
            # Only the repo owner's events build, so code from forks never runs here.
            source=codebuild.Source.git_hub(
                owner=GITHUB_OWNER,
                repo=GITHUB_REPO,
                webhook=True,
                webhook_filters=[filters.and_actor_account_is(f"^{GITHUB_OWNER_ID}$")],
                report_build_status=True,
            ),
            build_spec=codebuild.BuildSpec.from_source_filename(buildspec),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                compute_type=codebuild.ComputeType.SMALL,
                privileged=privileged,
            ),
            timeout=cdk.Duration.minutes(30),
            logging=codebuild.LoggingOptions(
                cloud_watch=codebuild.CloudWatchLoggingOptions(
                    log_group=logs.LogGroup(
                        self,
                        f"{construct_id}Logs",
                        retention=logs.RetentionDays.ONE_MONTH,
                        removal_policy=cdk.RemovalPolicy.DESTROY,
                    )
                )
            ),
        )
        # The L2 construct has no CodeConnections option: set the source auth directly.
        project.node.default_child.add_property_override(
            "Source.Auth", {"Type": "CODECONNECTIONS", "Resource": CONNECTION_ARN}
        )
        project.add_to_role_policy(
            iam.PolicyStatement(
                actions=[
                    "codeconnections:GetConnection",
                    "codeconnections:GetConnectionToken",
                    "codeconnections:UseConnection",
                    "codestar-connections:GetConnection",
                    "codestar-connections:GetConnectionToken",
                    "codestar-connections:UseConnection",
                ],
                resources=[CONNECTION_ARN],
            )
        )
        # CDK commands work by assuming the bootstrap roles; grant only the ones this build needs.
        project.add_to_role_policy(
            iam.PolicyStatement(
                actions=["sts:AssumeRole"],
                resources=[
                    f"arn:aws:iam::{self.account}:role/cdk-hnb659fds-{role}-role-{self.account}-{self.region}"
                    for role in assume_roles
                ],
            )
        )
        return project


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
CicdStack(app, "Investigation-Cicd-prod", env=ENV)
AppStack(app, "Investigation-prod", env=ENV)
app.synth()
