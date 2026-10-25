"""CDK app: three stacks in account 988277499209, eu-north-1, split by lifecycle (ADR 0020).

Investigation-Cicd-prod  CodeBuild PR diff + deploy on main. Deployed by hand: make deploy-cicd.
Investigation-Data-prod  The Aurora cluster. Deployed by CodeBuild, rarely changes.
Investigation-prod       The application. Deployed by CodeBuild on every push to main.
"""

from pathlib import Path

import aws_cdk as cdk
from aws_cdk import aws_codebuild as codebuild
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_destinations as destinations
from aws_cdk import aws_logs as logs
from aws_cdk import aws_rds as rds
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_s3_notifications as s3n
from aws_cdk import aws_sqs as sqs
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
DB_NAME = "postgres"  # express configuration creates only the default database


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
            # One deploy at a time, the rest queue in merge order. Parallel deploys raced on
            # 2026-10-24: two pushed the same image tag (ECR tags are immutable) and one deployed
            # Investigation-prod while the stack it imports from was still being created.
            concurrent_build_limit=1,
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
        concurrent_build_limit: int | None = None,
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
            concurrent_build_limit=concurrent_build_limit,
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
    """Stateful resources that hold data and rarely change: the Aurora cluster.

    A stack of its own so that a code deploy of Investigation-prod can never replace the
    database (ADR 0020). Investigation-prod imports the cluster's endpoint and resource id as
    CloudFormation exports: never remove an export it still uses in the same deploy.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # The Free plan creates Aurora only with express configuration (ADR 0021): no VPC, an
        # internet access gateway in front of the cluster, IAM auth only, the default engine
        # version (17.9 on 2026-10-24) and a serverless writer it creates by itself, hence the
        # L1 resource. Express rejects an initial database name (the database is `postgres`).
        # Deletion protection and capacity were added after the create, as an update: express
        # accepts few settings at create time and the Aurora guide's list of them is wrong.
        self.cluster = rds.CfnDBCluster(
            self,
            "Db",
            engine="aurora-postgresql",
            db_cluster_identifier="investigation",
            deletion_protection=True,
            # 0 ACU: the writer pauses after 5 idle minutes and costs only storage until the
            # next connection (~15 s resume). 4 ACU is enough for the bulk load and HNSW upkeep.
            # Express created exactly this range; it is pinned here so the code says so.
            serverless_v2_scaling_configuration=rds.CfnDBCluster.ServerlessV2ScalingConfigurationProperty(
                min_capacity=0, max_capacity=4, seconds_until_auto_pause=300
            ),
        )
        # Not in aws-cdk-lib 2.274's schema yet (synth warns), but in the live CloudFormation
        # registry. Create-only: it never changes after the first deploy.
        self.cluster.add_property_override("WithExpressConfiguration", True)
        # A bad deploy or a deleted stack must not lose the corpus.
        self.cluster.cfn_options.deletion_policy = cdk.CfnDeletionPolicy.SNAPSHOT
        self.cluster.cfn_options.update_replace_policy = cdk.CfnDeletionPolicy.SNAPSHOT


class AppStack(cdk.Stack):
    """The application: the documents bucket, the api and ingest Lambdas, the jobs project.

    Lambdas and CodeBuild run outside any VPC and reach Aurora through its internet access
    gateway with IAM auth tokens (ADR 0021). The bucket stays here with its notifications: they
    point at `ingest`, and a bucket in another stack would make the two stacks depend on each
    other. The schema custom resource is here too: it runs the app image and `engine.db`.
    """

    def __init__(
        self, scope: Construct, construct_id: str, cluster: rds.CfnDBCluster, **kwargs
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

        db_env = {"DB_HOST": cluster.attr_endpoint_address, "DB_NAME": DB_NAME}
        data_env = {**db_env, "BUCKET": bucket.bucket_name}
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

        # Events Lambda gave up on (2 retries failed, or too old) land here instead of being
        # dropped; `make redrive-ingest` reruns them. Depth is visible in the console, no alarm.
        failures = sqs.Queue(
            self,
            "IngestFailures",
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            enforce_ssl=True,
            retention_period=cdk.Duration.days(14),
        )
        ingest = lambda_.DockerImageFunction(
            self,
            "Ingest",
            code=lambda_.DockerImageCode.from_image_asset(image, cmd=["engine.handlers.ingest"]),
            architecture=lambda_.Architecture.X86_64,
            memory_size=1024,
            timeout=cdk.Duration.minutes(15),
            # Caps parallel Bedrock calls and database connections during the bulk load: the
            # eu.* Cohere pool allows ~20 requests/min, and two workers (each a 96-text request
            # every 2-3 s while embedding a shard, then its writes) fill it. Throttled S3 events
            # wait in Lambda's async queue instead of failing.
            reserved_concurrent_executions=2,
            # 6 h is Lambda's maximum (and default), set so the queue wait is visible here: a
            # full bulk load (134 shards on two workers) must start within it.
            max_event_age=cdk.Duration.hours(6),
            retry_attempts=2,
            on_failure=destinations.SqsDestination(failures),
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

        jobs = self._jobs_project(
            {
                **data_env,
                "INGEST_FAILURES_QUEUE": failures.queue_url,
                "INGEST_FUNCTION": ingest.function_name,
            }
        )
        # redrive-ingest: read and delete failure records, invoke ingest again.
        failures.grant_consume_messages(jobs)
        ingest.grant_invoke(jobs)
        # Jobs write shards (bulk/), the Acme corpus and evaluation results, and read them back.
        jobs.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject", "s3:PutObject"], resources=[bucket.arn_for_objects("*")]
            )
        )
        jobs.add_to_role_policy(
            iam.PolicyStatement(actions=["s3:ListBucket"], resources=[bucket.bucket_arn])
        )

        # IAM database auth: rds-db:connect names one database user of this cluster. Everything
        # logs in as `app` (data access only); only the schema function logs in as `postgres`.
        def db_user(name: str) -> str:
            return (
                f"arn:aws:rds-db:{self.region}:{self.account}:dbuser:"
                f"{cluster.attr_db_cluster_resource_id}/{name}"
            )

        for grantee in (api, ingest, jobs):
            grantee.add_to_role_policy(
                iam.PolicyStatement(actions=["rds-db:connect"], resources=[db_user("app")])
            )
        # ingest only embeds; api and the jobs also call the LLMs.
        self._allow_bedrock(ingest, llm=False)
        self._allow_bedrock(api, llm=True)
        self._allow_bedrock(jobs, llm=True)

        self._schema(image, db_env, db_user("postgres"))

    # Converse and ConverseStream are authorized by these two actions; there is no separate
    # bedrock:Converse action.
    _INVOKE = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]

    def _allow_bedrock(self, grantee: iam.IGrantable, llm: bool) -> None:
        # Every caller embeds (chunks or queries) with Cohere Embed V4 (ADR 0022).
        self._allow_eu_profile(grantee, "cohere.embed-v4:0")
        if not llm:
            return
        in_region = f"arn:aws:bedrock:{self.region}::foundation-model"
        grantee.grant_principal.add_to_principal_policy(
            iam.PolicyStatement(
                actions=self._INVOKE,
                resources=[
                    f"{in_region}/openai.gpt-oss-120b*",
                    f"{in_region}/qwen.qwen3-235b-a22b-2507*",
                ],
            )
        )
        self._allow_eu_profile(grantee, "anthropic.claude-haiku-4-5-*")

    def _allow_eu_profile(self, grantee: iam.IGrantable, model: str) -> None:
        # Cohere Embed V4 and Claude Haiku 4.5 exist here only through eu.* cross-Region
        # profiles. A call needs the profile and the model in every EU Region the profile may
        # route to; the condition allows the model only when the call comes through the profile.
        profile = f"arn:aws:bedrock:{self.region}:{self.account}:inference-profile/eu.{model}"
        grantee.grant_principal.add_to_principal_policy(
            iam.PolicyStatement(actions=self._INVOKE, resources=[profile])
        )
        grantee.grant_principal.add_to_principal_policy(
            iam.PolicyStatement(
                actions=self._INVOKE,
                resources=[f"arn:aws:bedrock:*::foundation-model/{model}"],
                conditions={"StringLike": {"bedrock:InferenceProfileArn": profile}},
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

    def _schema(self, image: str, db_env: dict[str, str], master_user: str) -> None:
        """Apply sql/schema.sql on every deploy where it changed (ADR 0019, 0021).

        A custom resource whose properties carry the SQL text: CloudFormation sends Update
        whenever the text changes, and engine.handlers.schema runs the whole file again.
        """
        handler = lambda_.DockerImageFunction(
            self,
            "SchemaFn",
            code=lambda_.DockerImageCode.from_image_asset(image, cmd=["engine.handlers.schema"]),
            architecture=lambda_.Architecture.X86_64,
            timeout=cdk.Duration.minutes(5),
            environment=db_env,
        )
        handler.add_to_role_policy(
            iam.PolicyStatement(actions=["rds-db:connect"], resources=[master_user])
        )
        provider = cr.Provider(self, "SchemaProvider", on_event_handler=handler)
        cdk.CustomResource(
            self,
            "Schema",
            service_token=provider.service_token,
            # The host too: a new cluster gets the schema even if the file did not change.
            properties={
                "DbHost": db_env["DB_HOST"],
                "Sql": (ROOT / "sql" / "schema.sql").read_text(),
            },
        )


app = cdk.App()
cdk.Tags.of(app).add("Project", "investigation-engine")
CicdStack(app, "Investigation-Cicd-prod", env=ENV)
data = DataStack(app, "Investigation-Data-prod", env=ENV)
AppStack(app, "Investigation-prod", cluster=data.cluster, env=ENV)
app.synth()
