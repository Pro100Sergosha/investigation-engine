import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from redrive_ingest import original_event  # noqa: E402


def test_original_event_is_the_request_payload_of_a_failure_record():
    s3_event = {"Records": [{"s3": {"bucket": {"name": "b"}, "object": {"key": "uploads/a.md"}}}]}
    # The shape Lambda sends to an on-failure destination of an asynchronous invocation.
    record = {
        "version": "1.0",
        "timestamp": "2026-10-25T10:00:00.000Z",
        "requestContext": {
            "requestId": "r-1",
            "functionArn": "arn:aws:lambda:eu-north-1:988277499209:function:ingest:$LATEST",
            "condition": "RetriesExhausted",
            "approximateInvokeCount": 3,
        },
        "requestPayload": s3_event,
        "responseContext": {"statusCode": 200, "executedVersion": "$LATEST"},
        "responsePayload": {
            "errorMessage": "Too many requests",
            "errorType": "ThrottlingException",
        },
    }
    event, reason = original_event(json.dumps(record))
    assert event == s3_event
    assert reason == {
        "condition": "RetriesExhausted",
        "error": {"errorMessage": "Too many requests", "errorType": "ThrottlingException"},
    }
