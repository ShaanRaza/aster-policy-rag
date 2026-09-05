"""Runtime configuration loader.

Lambda functions receive configuration through environment variables. This
module reads those variables once per invocation and exposes them as a typed
`Settings` object used by the rest of the pipeline.

Centralising configuration here keeps environment variable names out of the
business logic. If a variable is renamed in the deployment template, only
this file needs to change.
"""

import os
from dataclasses import dataclass


def _int_env(name: str, default: int) -> int:
    """Read an integer environment variable with a fallback default.

    Environment variables are always strings, so anything that should be
    an integer (top_k, chunk_size, ...) goes through this helper. Empty or
    missing values fall back to the default, which keeps the script usable
    on a fresh laptop with no exports set.
    """
    raw_value = os.environ.get(name)
    if raw_value is None or raw_value == "":
        return default
    # `int()` raises a clear ValueError if the env var is set to garbage,
    # which is exactly what we want — fail fast at boot, not deep in the
    # pipeline.
    return int(raw_value)


@dataclass(frozen=True)
class Settings:
    """All runtime values required by ingestion and query pipelines.

    Using a frozen dataclass means a) the values cannot be mutated by
    accident after load_settings(), and b) IDEs and type checkers know
    the exact field types.
    """

    # AWS region for ALL service clients (Bedrock, OpenSearch, S3).
    aws_region: str
    # S3 bucket that holds the source PDFs (used by backfill / scripts).
    source_bucket_name: str
    # Prefix under which PDFs live in the bucket — also the S3 event filter.
    source_prefix: str
    # OpenSearch Serverless collection endpoint (https://....aoss.amazonaws.com).
    opensearch_endpoint: str
    # Name of the k-NN index inside the collection.
    opensearch_index: str
    # Dimension of the embedding vectors. Must match the embedding model.
    vector_dimension: int
    # Bedrock model id used to embed text (e.g., Titan Text Embeddings v2).
    embed_model_id: str
    # Bedrock model id used to generate the final answer (e.g., Nova Lite).
    llm_model_id: str
    # Default number of retrieved chunks per query (overridable per request).
    top_k: int
    # Maximum number of characters per text chunk before splitting.
    chunk_size: int
    # How many characters consecutive chunks overlap to preserve context.
    chunk_overlap: int
    # Hard upper bound on the total context length the prompt can include.
    max_context_chars: int


def load_settings() -> Settings:
    """Load settings from Lambda environment variables.

    The defaults match the instructor workshop account so local scripts
    and simple tests have sensible values even before Lambda environment
    variables exist. In a real deployment, every value below is overridden
    by the Lambda function's environment configuration.
    """
    return Settings(
        # AWS_REGION is automatically set by Lambda; default to us-east-1
        # so local runs work without manually exporting it.
        aws_region=os.environ.get("AWS_REGION", "us-east-1"),
        # The default bucket name is the instructor-provisioned one.
        source_bucket_name=os.environ.get("SOURCE_BUCKET_NAME", "aster-policy-rag-source-pdfs-851725469799-us-east-1"),
        # Trailing slash matters: it scopes S3 event notifications and
        # list_objects_v2 prefix filtering to a folder-like layout.
        source_prefix=os.environ.get("SOURCE_PREFIX", "raw-pdfs/"),
        # `rstrip("/")` defends against attendees pasting URLs with or
        # without trailing slashes when configuring the Lambda.
        opensearch_endpoint=os.environ.get(
            "OPENSEARCH_ENDPOINT",
            "https://3o35kp5w5p9kc8gtzhpa.us-east-1.aoss.amazonaws.com",
        ).rstrip("/"),
        opensearch_index=os.environ.get("OPENSEARCH_INDEX", "aster-policy-rag-index"),
        # 1024 matches Titan Text Embeddings v2 output size.
        vector_dimension=_int_env("VECTOR_DIMENSION", 1024),
        embed_model_id=os.environ.get("BEDROCK_EMBED_MODEL_ID", "amazon.titan-embed-text-v2:0"),
        # `us.amazon.nova-lite-v1:0` is an inference profile id; the Bedrock
        # Converse API requires it for Nova models.
        llm_model_id=os.environ.get("BEDROCK_LLM_MODEL_ID", "us.amazon.nova-lite-v1:0"),
        top_k=_int_env("TOP_K", 5),
        chunk_size=_int_env("CHUNK_SIZE", 1200),
        chunk_overlap=_int_env("CHUNK_OVERLAP", 180),
        max_context_chars=_int_env("MAX_CONTEXT_CHARS", 12000),
    )


def validate_runtime_settings(settings: Settings, require_source_bucket: bool = False) -> None:
    """Fail fast when required deployment values are missing.

    `require_source_bucket=True` is used by scripts that scan S3 directly
    (where SOURCE_BUCKET_NAME must be set). The ingestion Lambda passes
    `False` because the bucket comes from the S3 event itself.
    """
    # Collect every missing variable so we can report them all in one shot
    # instead of failing on the first and forcing the operator to retry.
    missing = []
    if require_source_bucket and not settings.source_bucket_name:
        missing.append("SOURCE_BUCKET_NAME")
    if not settings.opensearch_endpoint:
        missing.append("OPENSEARCH_ENDPOINT")
    if not settings.opensearch_index:
        missing.append("OPENSEARCH_INDEX")
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
