#!/usr/bin/env python3
"""Invoke ingestion Lambda for PDFs that already exist in S3.

WHY THIS SCRIPT EXISTS
----------------------
The ingestion Lambda is normally triggered by an S3 `s3:ObjectCreated:*` event
notification. That notification only fires for objects uploaded AFTER the
notification was configured. Any PDFs that were already in the bucket before
the integration was set up will never receive an event, so they would never
be ingested into the vector index.

This script walks the S3 bucket, finds every existing PDF under a given
prefix, and asynchronously invokes the Lambda with a synthetic payload that
mimics what S3 would have sent. The Lambda treats this payload identically
to a real S3 event, so the result is the same: PDF -> chunks -> embeddings ->
OpenSearch.

INVOCATION TYPE
---------------
We use `InvocationType="Event"`, which is fire-and-forget (async). The script
finishes quickly even when there are many PDFs, and Lambda handles
parallelism on the backend. The trade-off is that you have to check
CloudWatch Logs to see ingestion results — they are not returned to this CLI.
"""

from __future__ import annotations

# CLI parsing for the bucket/prefix/function name arguments.
import argparse
# `json` is used to encode the Lambda payload as bytes.
import json

# `boto3` is the AWS SDK for Python. It handles credentials, signing, retries.
import boto3


def main() -> None:
    """Parse CLI arguments, list PDF objects, and invoke Lambda for each one."""
    parser = argparse.ArgumentParser(description="Invoke the ingestion Lambda for existing PDFs in S3.")
    # The bucket containing the PDFs to backfill.
    parser.add_argument("--bucket", required=True)
    # Only objects under this prefix are considered; trailing slash matters
    # for prefix matching to behave like a folder filter.
    parser.add_argument("--prefix", default="raw-pdfs/")
    # The deployed Lambda function name (or full ARN) of the ingestion Lambda.
    parser.add_argument("--function-name", required=True)
    # AWS region where both the bucket and the Lambda live.
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    # Two boto3 clients: one to list S3 objects, one to invoke the Lambda.
    s3 = boto3.client("s3", region_name=args.region)
    lambda_client = boto3.client("lambda", region_name=args.region)

    # `ListObjectsV2` returns up to 1000 keys per call. The paginator hides
    # the pagination loop so very large buckets still work without manual
    # `ContinuationToken` handling.
    paginator = s3.get_paginator("list_objects_v2")

    # Track how many invocations we triggered, purely for a final log line.
    invoked = 0

    # Iterate page by page over the bucket contents.
    for page in paginator.paginate(Bucket=args.bucket, Prefix=args.prefix):
        # `Contents` is missing entirely on empty pages, hence the `.get` default.
        for item in page.get("Contents", []):
            key = item["Key"]
            # Skip anything that is not a PDF — the bucket might contain other
            # artifacts (e.g., logs, manifests) we do not want to ingest.
            if not key.lower().endswith(".pdf"):
                continue

            # This payload matches the manual-test path in ingest_handler/app.py.
            # The Lambda checks for `event["bucket"]` and `event["key"]` as a
            # fall-back when there is no `Records` list, which is the case here.
            payload = {"bucket": args.bucket, "key": key}

            # `InvocationType="Event"` makes this async. Lambda enqueues the
            # invocation and we move on to the next PDF without waiting.
            lambda_client.invoke(
                FunctionName=args.function_name,
                InvocationType="Event",
                Payload=json.dumps(payload).encode("utf-8"),
            )

            invoked += 1
            # Print one line per PDF so the operator can monitor progress.
            print(f"Invoked ingestion for s3://{args.bucket}/{key}")

    # Summary line so the operator can see the total at the end.
    print(f"Total async invocations: {invoked}")


if __name__ == "__main__":
    main()
