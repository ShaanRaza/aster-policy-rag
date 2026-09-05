#!/usr/bin/env python3
"""Create the OpenSearch Serverless vector index used by the RAG pipeline.

This script is a one-time setup step run by workshop attendees (or instructors)
BEFORE any PDF ingestion can happen. The RAG pipeline stores chunk embeddings
inside an OpenSearch Serverless k-NN index, and that index has to exist with
the correct field mappings (vector dimension, HNSW parameters, metadata fields)
before the ingestion Lambda can write to it.

Run it from the project root, for example:

    python scripts/create_opensearch_index.py \\
        --endpoint https://xxxx.us-east-1.aoss.amazonaws.com \\
        --index aster-policy-rag-index \\
        --dimension 1024 \\
        --region us-east-1
"""

# `from __future__ import annotations` makes type hints (like `Path`) be treated
# as strings at runtime. This keeps the script compatible with older Python
# versions and avoids any import-order issues with forward references.
from __future__ import annotations

# `argparse` parses the CLI flags the script accepts (e.g., --endpoint).
import argparse
# `sys` is used to manipulate `sys.path` so we can import the shared Lambda code.
import sys
# `pathlib.Path` is the modern way to handle filesystem paths in Python.
from pathlib import Path

# The shared Lambda helpers live under `lambdas/shared`, which is not on the
# default Python path when running scripts. The line below prepends the
# `lambdas/` directory to `sys.path` so `from shared.opensearch_client import ...`
# works exactly the same way it works inside the Lambda packages. This keeps the
# script and the Lambda using the SAME OpenSearch client code with no drift.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambdas"))

# Import the wrapper that knows how to talk to OpenSearch Serverless using
# SigV4-signed HTTP requests. The same class is used by the ingestion Lambda.
from shared.opensearch_client import OpenSearchVectorClient


def main() -> None:
    """Create the index unless it already exists.

    The script is idempotent on purpose: if you run it twice it will simply
    report that the index already exists instead of failing or wiping data.
    """
    # Define and parse CLI arguments. `required=True` means the user must pass
    # the flag; the other flags have sensible workshop defaults.
    parser = argparse.ArgumentParser(description="Create the OpenSearch Serverless vector index.")
    parser.add_argument("--endpoint", required=True, help="OpenSearch Serverless collection endpoint.")
    parser.add_argument("--index", default="aster-policy-rag-index", help="Index name.")
    # `--dimension` MUST match the embedding model's output size. Amazon Titan
    # Text Embeddings v2 produces 1024-dimensional vectors, hence the default.
    parser.add_argument("--dimension", type=int, default=1024, help="Embedding vector dimension.")
    parser.add_argument("--region", default="us-east-1", help="AWS region.")
    args = parser.parse_args()

    # Build the client. SigV4 credentials are picked up from the environment
    # (AWS_PROFILE, instance role, etc.) by boto3 inside the client.
    client = OpenSearchVectorClient(args.endpoint, args.region, args.index)

    # Early-exit when the index already exists so re-runs are safe.
    if client.index_exists():
        print(f"Index already exists: {args.index}")
        return

    # Create the index with the configured vector dimension and print the
    # OpenSearch response so the user can see the acknowledgement.
    response = client.create_index(args.dimension)
    print(response)


# Standard Python idiom: only call `main()` when this file is executed
# directly, not when it is imported as a module.
if __name__ == "__main__":
    main()
