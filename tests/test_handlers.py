import json

from engine.handlers import api


def _event(method: str, path: str) -> dict:
    return {"requestContext": {"http": {"method": method}}, "rawPath": path}


def test_health():
    response = api(_event("GET", "/health"), None)
    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"status": "ok"}


def test_unknown_route():
    assert api(_event("GET", "/nope"), None)["statusCode"] == 404
