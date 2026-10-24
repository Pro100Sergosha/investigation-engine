"""Lambda entry points. `api` serves the Function URL; `ingest` receives S3 object events."""

import json
from urllib.parse import unquote_plus


def ingest(event, context):
    """S3 ObjectCreated on uploads/ or bulk/. Stub: logs the keys; wave 2 indexes the objects."""
    # S3 event keys are URL-encoded ("my file.md" arrives as "my+file.md").
    keys = [unquote_plus(record["s3"]["object"]["key"]) for record in event.get("Records", [])]
    print(json.dumps({"handler": "ingest", "keys": keys}))
    return {"keys": keys}


def api(event, context):
    route = (event["requestContext"]["http"]["method"], event["rawPath"])
    if route == ("GET", "/health"):
        return _json(200, {"status": "ok"})
    return _json(404, {"error": "not found"})


def _json(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }
