"""API Gateway entrypoint for user questions.

WHAT THIS LAMBDA DOES
---------------------
A browser-side UI sends a `POST /query` request with JSON like:

    { "question": "What is the meal per diem?", "top_k": 5 }

API Gateway routes that HTTP request to this Lambda. The handler:

1. Performs CORS pre-flight handling for OPTIONS requests.
2. Validates the JSON body and clamps `top_k` to a safe range.
3. Loads configuration from environment variables.
4. Builds the Bedrock and OpenSearch clients.
5. Runs the RAG pipeline (embed -> retrieve -> prompt -> generate).
6. Returns an `answer` plus `citations` to the UI.

The structure intentionally mirrors `ingest_handler/app.py`: thin handler,
fat pipeline. This keeps both Lambdas easy to read side by side.
"""

import json
from typing import Any, Dict

# Same shared modules used by the ingest handler. Both Lambdas share code via
# the `shared/` package that gets copied into each deployment zip.
from shared.bedrock_client import BedrockClient
from shared.config import load_settings, validate_runtime_settings
from shared.logger import get_logger
from shared.opensearch_client import OpenSearchVectorClient
from shared.rag_pipeline import RagPipeline

logger = get_logger(__name__)


def _response(status_code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Build an API Gateway-compatible JSON response with CORS headers.

    API Gateway expects every response to be a dict with `statusCode`,
    `headers`, and `body` (the body MUST be a string, not a dict — that is
    why we json.dumps it here).

    The `Access-Control-Allow-*` headers let the frontend bucket (hosted on
    a different origin than the API Gateway URL) call this Lambda from the
    browser without being blocked by CORS.
    """
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            # `*` is fine for a public workshop demo. For production, set the
            # specific origin (e.g., your CloudFront URL).
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Content-Type,Authorization",
            "Access-Control-Allow-Methods": "OPTIONS,POST",
        },
        "body": json.dumps(body),
    }


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """Handle POST /query requests from API Gateway."""
    # API Gateway HTTP APIs put the verb under `requestContext.http.method`.
    # REST APIs use `httpMethod`. The expression below supports both so the
    # same Lambda code works regardless of API Gateway flavour.
    method = event.get("requestContext", {}).get("http", {}).get("method") or event.get("httpMethod")

    # Browsers send an OPTIONS pre-flight request before any cross-origin
    # POST that uses a JSON content-type. We must respond 200 with CORS
    # headers or the browser will refuse to send the real POST.
    if method == "OPTIONS":
        return _response(200, {"ok": True})

    try:
        # Pull the raw HTTP body. Default to `{}` so the JSON parser does
        # not blow up on an empty payload — we will catch a missing
        # `question` field below.
        body = event.get("body") or "{}"
        if event.get("isBase64Encoded"):
            # Frontend sends JSON, not base64. If base64 ever shows up it
            # likely means the API Gateway integration is misconfigured.
            raise ValueError("Base64 encoded request bodies are not supported.")

        # Parse the JSON body into a dict.
        payload = json.loads(body)
        # Strip whitespace so " " is treated as missing.
        question = (payload.get("question") or "").strip()
        # `top_k` is optional; the pipeline has a default.
        top_k = payload.get("top_k")

        # Validate the required field. 400 = bad request.
        if not question:
            return _response(400, {"error": "question is required"})

        # Clamp top_k to [1, 10] so one UI request cannot demand a huge
        # context and blow past Bedrock's token budget.
        if top_k is not None:
            top_k = max(1, min(int(top_k), 10))

        # Load and validate runtime configuration.
        settings = load_settings()
        validate_runtime_settings(settings)

        # Build the AWS service clients inside the handler so any change to
        # Lambda environment variables takes effect on cold start.
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

        # Run the RAG pipeline. `answer_question` returns
        # `{"answer": ..., "citations": [...]}` which is exactly what the UI
        # consumes.
        pipeline = RagPipeline(settings, bedrock_client, opensearch_client)
        result = pipeline.answer_question(question, top_k=top_k)

        return _response(200, result)

    except Exception as exc:
        # Log the full traceback for CloudWatch.
        logger.exception("Query request failed")
        # Return the exception message to the client. For a workshop demo
        # this is intentional (it helps attendees debug their own setups).
        # In production you would typically return a generic message.
        return _response(500, {"error": str(exc)})
