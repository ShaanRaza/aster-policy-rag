"""S3 event entrypoint for PDF ingestion.

WHAT THIS LAMBDA DOES
---------------------
When a PDF is uploaded to the source S3 bucket, S3 fires an
`s3:ObjectCreated:*` event notification. AWS Lambda receives the event and
invokes `lambda_handler` below. This handler is intentionally thin: it
extracts the `(bucket, key)` references from the event and delegates the
real RAG ingestion work (download -> extract text -> chunk -> embed ->
index) to `IngestionPipeline`.

WHY THE HANDLER IS THIN
-----------------------
Keeping the handler small makes it easy to:

- Unit-test the pipeline locally without invoking AWS Lambda.
- Reuse the same pipeline from the `backfill_ingestion.py` script.
- Swap dependencies (e.g., a different embeddings provider) in one place.
"""

# Standard library imports first.
import json
from typing import Any, Dict, List, Tuple
# `unquote_plus` decodes URL-encoded keys from S3 events.
# A key like `raw-pdfs/Policy%20A.pdf` must become `raw-pdfs/Policy A.pdf`
# before we hand it to S3 GetObject.
from urllib.parse import unquote_plus

# All shared modules live in the `shared/` package vendored into the Lambda zip.
from shared.bedrock_client import BedrockClient
from shared.config import load_settings, validate_runtime_settings
from shared.ingestion_pipeline import IngestionPipeline
from shared.logger import get_logger
from shared.opensearch_client import OpenSearchVectorClient
from shared.s3_client import S3Client

# One logger per module. The `get_logger` helper respects the LOG_LEVEL env var.
logger = get_logger(__name__)


def _records_from_event(event: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Extract `(bucket, key)` pairs from S3 events or manual test payloads.

    This handler accepts two event shapes:

    1. The standard S3 event:
       `{"Records": [{"s3": {"bucket": {"name": ...}, "object": {"key": ...}}}]}`
    2. A simplified manual-test payload:
       `{"bucket": "...", "key": "..."}`
       used by `backfill_ingestion.py` and from the AWS console "Test" button.
    """
    records = []

    # Shape 1: normal S3 trigger.
    if "Records" in event:
        for record in event["Records"]:
            # Each Record may or may not have an `s3` block — defensive `.get`
            # avoids KeyError on unusual event variants (e.g., test events).
            s3_info = record.get("s3", {})
            bucket = s3_info.get("bucket", {}).get("name")
            key = s3_info.get("object", {}).get("key")
            if bucket and key:
                # S3 URL-encodes the key inside the event. Decode it before
                # using it for GetObject or it will 404 on names with spaces.
                records.append((bucket, unquote_plus(key)))

    # Shape 2: manual / backfill payload.
    elif event.get("bucket") and event.get("key"):
        records.append((event["bucket"], event["key"]))

    return records


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Run ingestion for every PDF object included in the event.

    `event`  — the raw payload from S3 (or a manual invocation).
    `context` — Lambda context object; not used here, but required by the
                Lambda runtime signature.
    """
    # Log a truncated copy of the event for traceability. We cap to 2000 chars
    # to keep CloudWatch costs predictable when payloads are large.
    logger.info("Received ingestion event: %s", json.dumps(event)[:2000])

    try:
        # 1) Load configuration from environment variables, then make sure
        #    the required fields are populated. For ingestion we do NOT
        #    require SOURCE_BUCKET_NAME because the bucket comes from the
        #    event itself.
        settings = load_settings()
        validate_runtime_settings(settings, require_source_bucket=False)

        # 2) Build the AWS-facing clients once per invocation. Lambda may
        #    reuse the container for subsequent invocations, but creating
        #    the clients inside the handler keeps the code straightforward
        #    and lets environment-variable changes take effect on each cold
        #    start.
        s3_client = S3Client(region_name=settings.aws_region)
        bedrock_client = BedrockClient(
            region_name=settings.aws_region,
            embed_model_id=settings.embed_model_id,
            llm_model_id=settings.llm_model_id,
        )
        opensearch_client = OpenSearchVectorClient(
            endpoint=settings.opensearch_endpoint,
            region_name=settings.aws_region,
            index_name=settings.opensearch_index,
        )

        # 3) Compose the ingestion pipeline with explicit dependencies. This
        #    pattern (constructor injection) makes the pipeline trivial to
        #    test with fake clients.
        pipeline = IngestionPipeline(settings, s3_client, bedrock_client, opensearch_client)

        # 4) Parse the event into a list of (bucket, key) tuples to ingest.
        records = _records_from_event(event)
        logger.info("Parsed %s S3 record(s): %s", len(records), records)
        if not records:
            # Failing here makes misconfigured S3 notifications obvious.
            raise ValueError("No S3 PDF records found in event.")

        # 5) Ingest each PDF and collect the per-PDF result objects so the
        #    Lambda response is useful when invoked synchronously.
        results = []
        for bucket, key in records:
            results.append(pipeline.ingest_s3_pdf(bucket, key))
        logger.info("Ingestion completed: %s", json.dumps(results))

        # 6) Return an HTTP-ish payload. S3 itself ignores this response —
        #    it is only seen when the Lambda is invoked manually or via
        #    `backfill_ingestion.py`.
        return {"statusCode": 200, "body": json.dumps({"results": results})}

    except Exception as exc:
        # Log full traceback into CloudWatch.
        logger.exception("Ingestion failed")
        # Re-raise so the Lambda invocation is reported as a failure to AWS.
        # This makes CloudWatch metrics, alarms, and retry semantics behave
        # correctly during workshop debugging.
        raise
