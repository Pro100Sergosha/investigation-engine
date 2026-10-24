"""Settings from environment variables: the only module that reads them.

In AWS the CDK stack sets them on the Lambdas and the jobs project. Defaults are empty so that
tests import the package without any AWS resources.
"""

import os

from dotenv import load_dotenv

load_dotenv()

EMBED_MODEL = os.environ.get("EMBED_MODEL", "amazon.titan-embed-text-v2:0")

# Aurora through the Data API: cluster, credentials secret (an ARN, not the password), database.
CLUSTER_ARN = os.environ.get("CLUSTER_ARN", "")
SECRET_ARN = os.environ.get("SECRET_ARN", "")
DB_NAME = os.environ.get("DB_NAME", "")

# Documents bucket: uploads/ (presigned browser PUTs) and bulk/ (JSONL shards) trigger ingest.
BUCKET = os.environ.get("BUCKET", "")
