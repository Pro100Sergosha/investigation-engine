"""Settings from environment variables: the only module that reads them.

In AWS the CDK stack sets them on the Lambdas and the jobs project. Defaults are empty so that
tests import the package without any AWS resources.
"""

import os

from dotenv import load_dotenv

load_dotenv()

EMBED_MODEL = os.environ.get("EMBED_MODEL", "amazon.titan-embed-text-v2:0")

# Aurora (express configuration): writer endpoint, database, and the login role. No password:
# engine.db signs an IAM auth token for DB_USER (ADR 0021).
DB_HOST = os.environ.get("DB_HOST", "")
DB_NAME = os.environ.get("DB_NAME", "")
DB_USER = os.environ.get("DB_USER", "app")

# Documents bucket: uploads/ (presigned browser PUTs) and bulk/ (JSONL shards) trigger ingest.
BUCKET = os.environ.get("BUCKET", "")
