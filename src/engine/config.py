"""Settings from environment variables: the only module that reads them.

In AWS the CDK stack sets them on the Lambdas and the jobs project. Defaults are empty so that
tests import the package without any AWS resources.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# The UI page: the image copies static/ next to the engine package (/var/task/static); in the
# repository it sits at the root, two levels above this file.
STATIC_DIR = Path(os.environ.get("LAMBDA_TASK_ROOT", Path(__file__).parents[2])) / "static"

# Lambda and CodeBuild set AWS_REGION; the default lets tests create boto3 clients at import.
REGION = os.environ.get("AWS_REGION", "eu-north-1")

# Cohere Embed V4 exists in this Region only through the eu.* cross-Region profile (ADR 0022).
EMBED_MODEL = os.environ.get("EMBED_MODEL", "eu.cohere.embed-v4:0")

# Aurora (express configuration): writer endpoint, database, and the login role. No password:
# engine.db signs an IAM auth token for DB_USER (ADR 0021).
DB_HOST = os.environ.get("DB_HOST", "")
DB_NAME = os.environ.get("DB_NAME", "")
DB_USER = os.environ.get("DB_USER", "app")

# Documents bucket: uploads/ (presigned browser PUTs) and bulk/ (JSONL shards) trigger ingest.
BUCKET = os.environ.get("BUCKET", "")

# Name (not value) of the SSM SecureString holding the admin token of the public API (ADR 0030).
# Empty: no admin access at all.
ADMIN_TOKEN_PARAM = os.environ.get("ADMIN_TOKEN_PARAM", "")
