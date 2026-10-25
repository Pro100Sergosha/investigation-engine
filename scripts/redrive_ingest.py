"""Rerun the ingest events Lambda gave up on: IngestFailures queue -> async invoke of ingest."""

import argparse
import json

import boto3

from engine import config


def original_event(body: str) -> tuple[dict, dict]:
    """(the S3 event, why it failed) from the body of a Lambda on-failure record.

    The record wraps the event as `requestPayload`; `requestContext.condition` is
    RetriesExhausted or EventAgeExceeded, `responsePayload` the function's error.
    """
    record = json.loads(body)
    reason = {
        "condition": record["requestContext"]["condition"],
        "error": record.get("responsePayload"),
    }
    return record["requestPayload"], reason


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue-url", required=True)
    parser.add_argument("--function", required=True)
    args = parser.parse_args()
    sqs = boto3.client("sqs", region_name=config.REGION)
    lambda_ = boto3.client("lambda", region_name=config.REGION)
    # ponytail: stops at the first empty receive. An event that fails again comes back after
    # its retries (minutes), so it waits for the next run instead of looping here.
    redriven = 0
    while messages := sqs.receive_message(
        QueueUrl=args.queue_url, MaxNumberOfMessages=10, WaitTimeSeconds=1
    ).get("Messages", []):
        for message in messages:
            event, reason = original_event(message["Body"])
            print(json.dumps(reason))
            lambda_.invoke(
                FunctionName=args.function, InvocationType="Event", Payload=json.dumps(event)
            )
            # Deleted only after the invoke was accepted: a crash here redrives it twice,
            # which ingest absorbs (a rerun is "unchanged").
            sqs.delete_message(QueueUrl=args.queue_url, ReceiptHandle=message["ReceiptHandle"])
            redriven += 1
    print(json.dumps({"redriven": redriven}))


if __name__ == "__main__":
    main()
