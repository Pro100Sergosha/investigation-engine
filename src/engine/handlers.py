"""Lambda entry points. `api` serves the Function URL; `ingest` receives S3 object events;
`schema` applies sql/schema.sql for the deploy's custom resource."""

import json
from urllib.parse import unquote_plus

from engine import db

# The cluster's master user (IAM auth only, created by express configuration). Only `schema`
# connects as it: it owns the tables and creates the `app` role everything else uses.
SCHEMA_USER = "postgres"


def ingest(event, context):
    """S3 ObjectCreated on uploads/ or bulk/. Stub: logs the keys; wave 2 indexes the objects."""
    # S3 event keys are URL-encoded ("my file.md" arrives as "my+file.md").
    keys = [unquote_plus(record["s3"]["object"]["key"]) for record in event.get("Records", [])]
    print(json.dumps({"handler": "ingest", "keys": keys}))
    return {"keys": keys}


def schema(event, context):
    """CDK Provider on_event: Create and Update apply the schema, Delete keeps the data.

    The SQL text is a property of the custom resource, so a deploy that changes the file sends
    Update. Without parameters pg8000 uses the simple query protocol: the whole file runs in one
    call, as one implicit transaction, so a broken statement applies nothing.
    """
    if event["RequestType"] != "Delete":
        db.connect(SCHEMA_USER).run(event["ResourceProperties"]["Sql"])
    return {"PhysicalResourceId": "schema"}


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
