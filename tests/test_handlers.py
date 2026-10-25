import json

from engine.handlers import api, ingest, schema


def _event(method: str, path: str) -> dict:
    return {"requestContext": {"http": {"method": method}}, "rawPath": path}


def test_health():
    response = api(_event("GET", "/health"), None)
    assert response["statusCode"] == 200
    assert json.loads(response["body"]) == {"status": "ok"}


def test_root_serves_the_ui_page():
    response = api(_event("GET", "/"), None)
    assert response["statusCode"] == 200
    assert response["headers"]["content-type"].startswith("text/html")
    assert "<title>Investigation Engine</title>" in response["body"]


def test_unknown_route():
    assert api(_event("GET", "/nope"), None)["statusCode"] == 404


def test_ingest_logs_decoded_keys(capsys):
    event = {"Records": [{"s3": {"object": {"key": "uploads/my+file.md"}}}]}
    assert ingest(event, None) == {"keys": ["uploads/my file.md"]}
    line = json.loads(capsys.readouterr().out)
    assert line == {"handler": "ingest", "keys": ["uploads/my file.md"]}


def test_schema_delete_keeps_the_data():
    # Delete makes no AWS call: without credentials it would fail if it tried.
    assert schema({"RequestType": "Delete"}, None) == {"PhysicalResourceId": "schema"}
