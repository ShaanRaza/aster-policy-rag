#!/usr/bin/env python3
"""Upload generated PDF source documents to the S3 ingestion bucket.

The workshop ships with a `generate_policy_pdfs.py` helper that produces a
set of synthetic policy PDFs in `data/generated_pdfs/`. Those PDFs must
land in the S3 source bucket so the ingestion Lambda can pick them up and
push them through the RAG indexing pipeline.

This script copies every local PDF into the bucket under a configurable
prefix (defaults to `raw-pdfs/`, which matches the S3 event filter in the
project's CDK/Terraform configuration).
"""

from __future__ import annotations

# Argument parsing for bucket name, prefix, etc.
import argparse
# Path handling for the local PDF directory.
from pathlib import Path

# AWS SDK for the S3 `upload_file` call.
import boto3


def main() -> None:
    """Upload every local PDF under the selected S3 prefix."""
    parser = argparse.ArgumentParser(description="Upload generated workshop PDFs to S3.")
    # The destination bucket. Required because there is no safe default.
    parser.add_argument("--bucket", required=True, help="Target S3 bucket name.")
    # `raw-pdfs/` matches the prefix the ingestion Lambda is subscribed to.
    parser.add_argument("--prefix", default="raw-pdfs/", help="S3 prefix for PDF objects.")
    # Default to the same directory `generate_policy_pdfs.py` writes into so
    # the two scripts dovetail.
    parser.add_argument("--pdf-dir", default="data/generated_pdfs", help="Local PDF directory.")
    # boto3 will resolve the region from the AWS profile if not provided.
    parser.add_argument("--region", default=None, help="AWS region.")
    args = parser.parse_args()

    # `upload_file` handles multipart uploads transparently for large files.
    s3 = boto3.client("s3", region_name=args.region)

    # Resolve the local directory and walk it for PDFs. `sorted()` keeps the
    # upload order deterministic, which makes log output easier to scan.
    pdf_dir = Path(args.pdf_dir)
    for path in sorted(pdf_dir.glob("*.pdf")):
        # The prefix keeps source documents organized under raw-pdfs/.
        # `rstrip("/")` defends against the user passing `raw-pdfs` with or
        # without a trailing slash — we always end up with exactly one.
        key = f"{args.prefix.rstrip('/')}/{path.name}"
        s3.upload_file(str(path), args.bucket, key)
        print(f"Uploaded {path} to s3://{args.bucket}/{key}")


if __name__ == "__main__":
    main()
