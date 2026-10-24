"""CDK app: three stacks in account 988277499209, eu-north-1, split by lifecycle (ADR 0020).

Investigation-Cicd-prod  CodeBuild PR diff + deploy on main. Deployed by hand: make deploy-cicd.
Investigation-Data-prod  VPC, Aurora, its secret, the schema. Deployed by CodeBuild, rarely changes.
Investigation-prod       The application. Deployed by CodeBuild on every push to main.
"""

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_codebuild as codebuild
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_logs as logs
from aws_cdk import aws_rds as rds
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_notifications as s3n
from aws_cdk import custom_resources as cr
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
DB_NAME = "investigation"


def _connection_statement() -> iam.PolicyStatement:
    """Lets a CodeBuild role clone the repo through the GitHub connection (both service names)."""
    return iam.PolicyStatement(
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
        # CodeBuild checks the role's access to the connection while creating the project and its
        # webhook, so these permissions must exist before the project: inline in the role. The
        # role's DefaultPolicy (added by add_to_role_policy) has no DependsOn from the project and
        # is created in parallel, which failed the first deploys.
        role = iam.Role(
            self,
            f"{construct_id}Role",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
            inline_policies={
                "ConnectionAndCdk": iam.PolicyDocument(
                    statements=[
                        _connection_statement(),
                        # CDK commands work by assuming the bootstrap roles; only the ones needed.
                        iam.PolicyStatement(
                            actions=["sts:AssumeRole"],
                            resources=[
                                f"arn:aws:iam::{self.account}:role/"
                                f"cdk-hnb659fds-{bootstrap}-role-{self.account}-{self.region}"
                                for bootstrap in assume_roles
                            ],
                        ),
                    ]
                )
            },
        )
        # GitHub auth comes from the account-level CodeBuild source credential, which points at
        # CONNECTION_ARN (imported once with the CLI, see llm-wiki/07).
        project = codebuild.Project(
            self,
            construct_id,
            project_name=name,
            role=role,
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
        return project


class DataStack(cdk.Stack):
    """Stateful resources that hold data and rarely change: the VPC, Aurora, its secret, the schema.

    A stack of its own so that a code deploy of Investigation-prod can never replace the
    database (ADR 0020). The VPC exists only because an Aurora cluster must live in one (ADR 0019).
    Investigation-prod imports the cluster and secret ARNs as CloudFormation exports: never remove
    an export it still uses in the same deploy.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Isolated subnets only: no internet gateway, no NAT, no route out. Nothing in the
        # VPC needs one. Aurora needs subnets in two AZs. CDK checks these against the
        # Region's AZs, a lookup cached in cdk.context.json, which is committed because CI
        # synthesizes without AWS credentials.
        vpc = ec2.Vpc(
            self,
            "Vpc",
            availability_zones=["eu-north-1a", "eu-north-1b"],
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="db", subnet_type=ec2.SubnetType.PRIVATE_ISOLATED, cidr_mask=24
                )
            ],
        )
        # 17.9: Data API needs 17.4+, pgvector 0.8 (halfvec) and 0-ACU auto-pause are in it.
        self.cluster = rds.DatabaseCluster(
            self,
            "Db",
            engine=rds.DatabaseClusterEngine.aurora_postgres(
                version=rds.AuroraPostgresEngineVersion.VER_17_9
            ),
            writer=rds.ClusterInstance.serverless_v2("Writer", publicly_accessible=False),
            # 0 ACU: the writer pauses after 5 idle minutes and costs only storage until the
            # next request (~15 s resume). 4 ACU is enough for the bulk load and HNSW upkeep.
            serverless_v2_min_capacity=0,
            serverless_v2_max_capacity=4,
            enable_data_api=True,
            credentials=rds.Credentials.from_generated_secret("postgres"),
            default_database_name=DB_NAME,
            vpc=vpc,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_ISOLATED),
            backup=rds.BackupProps(retention=cdk.Duration.days(1)),
            # A bad deploy or a deleted stack must not lose the corpus.
            deletion_protection=True,
            removal_policy=cdk.RemovalPolicy.SNAPSHOT,
        )
        self._schema(self.cluster)

    def _schema(self, cluster: rds.DatabaseCluster) -> None:
        """Apply sql/schema.sql on every deploy where it changed (ADR 0019).

        A custom resource whose properties carry the SQL text: CloudFormation sends Update
        whenever the text changes, and the handler re-runs every (idempotent) statement.
        """
        code = (ROOT / "scripts" / "schema.py").read_text()
        handler = lambda_.Function(
            self,
            "SchemaFn",
            runtime=lambda_.Runtime.PYTHON_3_12,
            handler="index.handler",
            code=lambda_.Code.from_inline(code),
            timeout=cdk.Duration.minutes(5),
        )
        cluster.grant_data_api_access(handler)
        provider = cr.Provider(self, "SchemaProvider", on_event_handler=handler)
        schema = cdk.CustomResource(
            self,
            "Schema",
            service_token=provider.service_token,
            properties={
                "ClusterArn": cluster.cluster_arn,
                "SecretArn": cluster.secret.secret_arn,
                "Database": DB_NAME,
                "Sql": (ROOT / "sql" / "schema.sql").read_text(),
            },
        )
        # The whole cluster construct: the writer instance must exist before any statement.
        schema.node.add_dependency(cluster)


class AppStack(cdk.Stack):
    """The application: the documents bucket, the api and ingest Lambdas, the jobs project.

    Lambdas and CodeBuild run outside any VPC and reach Aurora only through the Data API
    (ADR 0015). The bucket stays here with its notifications: they point at `ingest`, and a
    bucket in another stack would make the two stacks depend on each other.
    """

    def __init__(
        self, scope: Construct, construct_id: str, cluster: rds.DatabaseCluster, **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        bucket = s3.Bucket(
            self,
            "Documents",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=cdk.RemovalPolicy.RETAIN,
            # The browser PUTs uploads straight to S3 with a presigned URL. Any origin is fine:
            # CORS only limits which pages a browser lets make the call, the signature is what
            # authorizes it, and naming the Function URL here would be a circular reference.
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.PUT],
                    allowed_origins=["*"],
                    allowed_headers=["*"],
                    max_age=3000,
                )
            ],
        )

        data_env = {
            "CLUSTER_ARN": cluster.cluster_arn,
            "SECRET_ARN": cluster.secret.secret_arn,
            "DB_NAME": DB_NAME,
            "BUCKET": bucket.bucket_name,
        }
        image = str(ROOT)
        api = lambda_.DockerImageFunction(
            self,
            "Api",
            code=lambda_.DockerImageCode.from_image_asset(image, cmd=["engine.handlers.api"]),
            architecture=lambda_.Architecture.X86_64,
            memory_size=1024,
            timeout=cdk.Duration.seconds(90),
            environment=data_env,
        )
        url = api.add_function_url(auth_type=lambda_.FunctionUrlAuthType.NONE)
        cdk.CfnOutput(self, "ApiUrl", value=url.url)

        ingest = lambda_.DockerImageFunction(
            self,
            "Ingest",
            code=lambda_.DockerImageCode.from_image_asset(image, cmd=["engine.handlers.ingest"]),
            architecture=lambda_.Architecture.X86_64,
            memory_size=1024,
            timeout=cdk.Duration.minutes(15),
            # Caps parallel Bedrock and Data API load during the bulk load; throttled S3
            # events wait in Lambda's async queue (up to 6 h) instead of failing.
            reserved_concurrent_executions=5,
            environment=data_env,
        )
        for prefix in ("uploads/", "bulk/"):
            bucket.add_event_notification(
                s3.EventType.OBJECT_CREATED,
                s3n.LambdaDestination(ingest),
                s3.NotificationKeyFilter(prefix=prefix),
            )

        # api presigns uploads (the URL carries the api role's permission) and reads nothing
        # else from S3; ingest reads what triggered it.
        api.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:PutObject"], resources=[bucket.arn_for_objects("uploads/*")]
            )
        )
        ingest.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[bucket.arn_for_objects("uploads/*"), bucket.arn_for_objects("bulk/*")],
            )
        )

        jobs = self._jobs_project(data_env)
        # Jobs write shards (bulk/), the Acme corpus and evaluation results, and read them back.
        jobs.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject"], resources=[bucket.arn_for_objects("*")]
            )
        )
        jobs.add_to_role_policy(
            iam.PolicyStatement(actions=["s3:ListBucket"], resources=[bucket.bucket_arn])
        )

        # Data API on the cluster + read the credentials secret (grant_data_api_access does both).
        for grantee in (api, ingest, jobs):
            cluster.grant_data_api_access(grantee)
        # ingest only embeds; api and the jobs also call the LLMs.
        self._allow_bedrock(ingest, llm=False)
        self._allow_bedrock(api, llm=True)
        self._allow_bedrock(jobs, llm=True)

    def _allow_bedrock(self, grantee: iam.IGrantable, llm: bool) -> None:
        # Converse and ConverseStream are authorized by these two actions; there is no
        # separate bedrock:Converse action.
        invoke = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
        in_region = f"arn:aws:bedrock:{self.region}::foundation-model"
        models = [f"{in_region}/amazon.titan-embed-text-v2:0"]
        if llm:
            models += [
                f"{in_region}/openai.gpt-oss-120b*",
                f"{in_region}/qwen.qwen3-235b-a22b-2507*",
            ]
        grantee.grant_principal.add_to_principal_policy(
            iam.PolicyStatement(actions=invoke, resources=models)
        )
        if not llm:
            return
        # Claude Haiku 4.5 exists here only through the eu.* cross-Region profile. A call needs the
        # profile and the model in every EU Region the profile may route to; the condition allows
        # the model only when the call comes through that profile.
        haiku = (
            f"arn:aws:bedrock:{self.region}:{self.account}"
            ":inference-profile/eu.anthropic.claude-haiku-4-5-*"
        )
        grantee.grant_principal.add_to_principal_policy(
            iam.PolicyStatement(actions=invoke, resources=[haiku])
        )
        grantee.grant_principal.add_to_principal_policy(
            iam.PolicyStatement(
                actions=invoke,
                resources=["arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-*"],
                conditions={"StringLike": {"bedrock:InferenceProfileArn": haiku}},
            )
        )

    def _jobs_project(self, data_env: dict[str, str]) -> codebuild.Project:
        """investigation-jobs: long one-off jobs started by hand (ADR 0018), no webhook."""
        # Inline for the same reason as CicdStack._project: CodeBuild checks the role's access
        # to the connection while creating the project, before a DefaultPolicy would exist.
        role = iam.Role(
            self,
            "JobsRole",
            assumed_by=iam.ServicePrincipal("codebuild.amazonaws.com"),
            inline_policies={
                "Connection": iam.PolicyDocument(statements=[_connection_statement()])
            },
        )
        return codebuild.Project(
            self,
            "Jobs",
            project_name="investigation-jobs",
            role=role,
            source=codebuild.Source.git_hub(
                owner=GITHUB_OWNER, repo=GITHUB_REPO, webhook=False, report_build_status=False
            ),
            build_spec=codebuild.BuildSpec.from_source_filename(".codebuild/jobs.yml"),
            environment=codebuild.BuildEnvironment(
                build_image=codebuild.LinuxBuildImage.STANDARD_7_0,
                compute_type=codebuild.ComputeType.SMALL,
                privileged=False,
            ),
            environment_variables={
                name: codebuild.BuildEnvironmentVariable(value=value)
                for name, value in data_env.items()
            },
            timeout=cdk.Duration.hours(2),
            # One job at a time: two jobs would share the Bedrock quota and the database.
            concurrent_build_limit=1,
            logging=codebuild.LoggingOptions(
                cloud_watch=codebuild.CloudWatchLoggingOptions(
                    log_group=logs.LogGroup(
                        self,
                        "JobsLogs",
                        retention=logs.RetentionDays.ONE_MONTH,
                        removal_policy=cdk.RemovalPolicy.DESTROY,
                    )
                )
            ),
        )


app = cdk.App()
cdk.Tags.of(app).add("Project", "investigation-engine")
CicdStack(app, "Investigation-Cicd-prod", env=ENV)
data = DataStack(app, "Investigation-Data-prod", env=ENV)
AppStack(app, "Investigation-prod", cluster=data.cluster, env=ENV)
app.synth()
