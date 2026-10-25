"""Embeddings: Bedrock Titan Text Embeddings V2, one text per request (ADR 0016)."""

import json

import boto3
from botocore.config import Config

from engine import config

DIMENSIONS = 1024  # sql/schema.sql: embedding halfvec(1024)

# Titan's quota is not listed in Service Quotas, so the bulk load must expect throttling:
# adaptive retry backs off on ThrottlingException and slows the client down instead of failing.
_bedrock = boto3.client(
    "bedrock-runtime",
    region_name=config.REGION,
    config=Config(retries={"max_attempts": 10, "mode": "adaptive"}),
)


def embed(text: str) -> list[float]:
    """1024 floats of unit length (`normalize`), so cosine similarity is the dot product.

    Titan V2 has no separate query and document modes: chunks and questions use the same call.
    """
    response = _bedrock.invoke_model(
        modelId=config.EMBED_MODEL,
        body=json.dumps({"inputText": text, "dimensions": DIMENSIONS, "normalize": True}),
    )
    return json.loads(response["body"].read())["embedding"]
