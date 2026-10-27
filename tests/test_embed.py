import io
import json

import pytest

from engine import embed


class FakeBedrock:
    """Answers like Cohere Embed V4, one [len(text)] vector per text; records request bodies."""

    def __init__(self):
        self.bodies: list[dict] = []

    def invoke_model(self, modelId, body):
        request = json.loads(body)
        self.bodies.append(request)
        vectors = [[float(len(text))] for text in request["texts"]]
        return {"body": io.BytesIO(json.dumps({"embeddings": {"float": vectors}}).encode())}


@pytest.fixture
def fake(monkeypatch):
    client = FakeBedrock()
    monkeypatch.setattr(embed, "_bedrock", client)
    monkeypatch.setattr(embed, "_query_bedrock", client)
    embed.embed_query.cache_clear()  # a vector cached by another test would skip the request
    return client


def test_documents_go_in_batches_of_96_in_order(fake):
    texts = ["x" * n for n in range(1, 98)]  # 97 texts, each vector is its length
    vectors = embed.embed_documents(texts)
    assert [len(body["texts"]) for body in fake.bodies] == [96, 1]
    assert vectors == [[float(n)] for n in range(1, 98)]
    for body in fake.bodies:
        assert body["input_type"] == "search_document"
        assert body["output_dimension"] == embed.DIMENSIONS == 1024
        assert body["embedding_types"] == ["float"]


def test_no_texts_no_request(fake):
    assert embed.embed_documents([]) == []
    assert fake.bodies == []


def test_query_uses_search_query(fake):
    assert embed.embed_query("who founded acme") == [16.0]
    assert fake.bodies == [
        {
            "texts": ["who founded acme"],
            "input_type": "search_query",
            "embedding_types": ["float"],
            "output_dimension": 1024,
            "truncate": "RIGHT",
        }
    ]


def test_query_can_ask_for_fewer_dimensions(fake):
    embed.embed_query("q", 512)
    assert fake.bodies[0]["output_dimension"] == 512


def test_query_is_embedded_once_per_text(fake):
    first = embed.embed_query("who founded acme")
    assert embed.embed_query("who founded acme") is first
    assert len(fake.bodies) == 1
    embed.embed_query("another question")
    assert len(fake.bodies) == 2


def test_queries_use_the_bounded_client(monkeypatch):
    bulk, query = FakeBedrock(), FakeBedrock()
    monkeypatch.setattr(embed, "_bedrock", bulk)
    monkeypatch.setattr(embed, "_query_bedrock", query)
    embed.embed_query.cache_clear()
    embed.embed_query("q")
    embed.embed_documents(["d"])
    assert [b["input_type"] for b in query.bodies] == ["search_query"]
    assert [b["input_type"] for b in bulk.bodies] == ["search_document"]
