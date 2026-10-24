"""Apply sql/schema.sql through the RDS Data API: on every deploy, or by hand (make schema).

The CDK app inlines this file as the code of the Schema custom resource's Lambda (python3.12
runtime), so it must stay one file that imports only the standard library and boto3.
"""

import argparse
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError


def statements(sql: str) -> list[str]:
    """Split a script into single statements: the Data API rejects several in one call."""
    lines = [line for line in sql.splitlines() if not line.lstrip().startswith("--")]
    return [part.strip() for part in "\n".join(lines).split(";") if part.strip()]


def apply(sql: str, cluster_arn: str, secret_arn: str, database: str) -> None:
    # Created here, not at import: tests import this module without an AWS Region.
    client = boto3.client("rds-data")
    for statement in statements(sql):
        _execute(client, statement, cluster_arn, secret_arn, database)


def _execute(client, statement: str, cluster_arn: str, secret_arn: str, database: str) -> None:
    # A paused cluster answers DatabaseResumingException for ~15 s, and a just-created one may
    # reject calls briefly. Every error is retried for ~3 minutes: a real SQL error then fails
    # the deploy 3 minutes late, which is cheaper than a failed first deploy.
    for attempt in range(18):
        try:
            client.execute_statement(
                resourceArn=cluster_arn, secretArn=secret_arn, database=database, sql=statement
            )
            return
        except ClientError as error:
            if attempt == 17:
                raise
            print(f"retrying in 10 s: {error.response['Error']['Code']}")
            time.sleep(10)


def handler(event, context):
    """CDK Provider on_event. Create and Update apply the schema; Delete keeps the data."""
    if event["RequestType"] != "Delete":
        props = event["ResourceProperties"]
        apply(props["Sql"], props["ClusterArn"], props["SecretArn"], props["Database"])
    return {"PhysicalResourceId": "schema"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cluster-arn", required=True)
    parser.add_argument("--secret-arn", required=True)
    parser.add_argument("--database", required=True)
    args = parser.parse_args()
    sql = (Path(__file__).resolve().parent.parent / "sql" / "schema.sql").read_text()
    apply(sql, args.cluster_arn, args.secret_arn, args.database)


if __name__ == "__main__":
    main()
