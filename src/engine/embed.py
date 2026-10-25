"""Embeddings: Bedrock Cohere Embed V4 through the eu.* profile, 96 texts per request (ADR 0022)."""

import json

import boto3
from botocore.config import Config

from engine import config

DIMENSIONS = 1024  # sql/schema.sql: embedding halfvec(1024)
BATCH = 96  # Cohere's maximum number of texts per request

# The eu.* pool allows 20 requests/min: the bulk load throttles by design. Adaptive retry backs
# off on ThrottlingException and slows the client down instead of failing.
_bedrock = boto3.client(
    "bedrock-runtime",
    region_name=config.REGION,
    config=Config(retries={"max_attempts": 10, "mode": "adaptive"}),
)


def embed_documents(texts: list[str]) -> list[list[float]]:
    """One vector per text, in input order, as `search_document`; one request per 96 texts.

    Cohere embeds documents and queries differently (asymmetric search): chunks go through here,
    questions through `embed_query`. An empty list makes no request.
    """
    vectors = []
    for start in range(0, len(texts), BATCH):
        vectors += _embed(texts[start : start + BATCH], "search_document")
    return vectors


def embed_query(text: str) -> list[float]:
    """The vector of a search query (`search_query`), comparable with `embed_documents`."""
    return _embed([text], "search_query")[0]


def _embed(texts: list[str], input_type: str) -> list[list[float]]:
    """1024 floats per text, unit length as returned by Cohere, so cosine is the dot product.

    `truncate: RIGHT` cuts an over-long input instead of failing the whole batch.
    """
    body = {
        "texts": texts,
        "input_type": input_type,
        "embedding_types": ["float"],
        "output_dimension": DIMENSIONS,
        "truncate": "RIGHT",
    }
    response = _bedrock.invoke_model(modelId=config.EMBED_MODEL, body=json.dumps(body))
    return json.loads(response["body"].read())["embeddings"]["float"]
