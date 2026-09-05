#!/usr/bin/env python3
"""Delete the workshop OpenSearch Serverless vector index.

Useful for two cases:

1. Resetting the workshop between runs (wipe vectors so re-ingestion starts
   from a clean slate).
2. Reclaiming OpenSearch storage when the demo is over.

This script is destructive: it permanently deletes the index and every
indexed chunk. Run it deliberately.

Example:

    python scripts/delete_opensearch_index.py \\
        --endpoint https://xxxx.us-east-1.aoss.amazonaws.com \\
        --index aster-policy-rag-index \\
        --region us-east-1
"""

# `from __future__ import annotations` defers evaluation of type hints. Not
# strictly necessary here, but it keeps style consistent across all scripts.
from __future__ import annotations

# CLI parsing, path setup, and the shared OpenSearch helper — same pattern as
# `create_opensearch_index.py`.
import argparse
import sys
from pathlib import Path

# Reuse the OpenSearch helper from the Lambda shared package by adding
# `lambdas/` to the module search path. This guarantees the script talks to
# OpenSearch the exact same way the Lambda code does.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambdas"))

from shared.opensearch_client import OpenSearchVectorClient


def main() -> None:
    """Delete the configured vector index if it exists.

    Like `create_opensearch_index.py`, this is idempotent: it does nothing
    if the index is already absent, instead of returning a 404 error.
    """
    parser = argparse.ArgumentParser(description="Delete the OpenSearch Serverless vector index.")
    parser.add_argument("--endpoint", required=True, help="OpenSearch Serverless collection endpoint.")
    parser.add_argument("--index", default="aster-policy-rag-index", help="Index name.")
    parser.add_argument("--region", default="us-east-1", help="AWS region.")
    args = parser.parse_args()

    # Build the SigV4-signed OpenSearch client.
    client = OpenSearchVectorClient(args.endpoint, args.region, args.index)

    # Guard the delete so a missing index produces a clean message instead of
    # a confusing HTTP error.
    if not client.index_exists():
        print(f"Index does not exist: {args.index}")
        return

    # Perform the deletion and print the OpenSearch acknowledgement so the
    # operator can confirm it succeeded.
    response = client.delete_index()
    print(response)


# Only run `main()` if this script is the entry point.
if __name__ == "__main__":
    main()
