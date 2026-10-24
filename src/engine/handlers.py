"""Lambda entry points. `api` serves the Function URL; routes are added as streams land."""

import json


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
