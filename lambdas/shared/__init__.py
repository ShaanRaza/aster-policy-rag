"""Shared RAG modules used by the ingestion and query Lambda handlers.

This package contains every helper that is reused across both Lambdas:

- `config.py`              Environment-driven runtime settings.
- `logger.py`              Standard logger factory.
- `s3_client.py`           Thin wrapper around boto3 S3 calls.
- `pdf_loader.py`          PDF text extraction (page-by-page).
- `chunker.py`             Page-aware overlapping text chunker.
- `bedrock_client.py`      Bedrock embeddings + answer generation.
- `opensearch_client.py`   OpenSearch Serverless vector index helper.
- `ingestion_pipeline.py`  Orchestrates the ingest flow.
- `rag_pipeline.py`        Orchestrates the query flow.

The build step in `scripts/build_lambda_packages.py` copies this entire
directory into each Lambda zip so both handlers can `from shared.x import y`.
"""
