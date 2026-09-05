"""Thin wrapper around Amazon S3 operations used in the workshop.

We wrap boto3's S3 client for two reasons:

1. The wrapper exposes only the operations we actually use (read bytes,
   list PDFs), which makes the rest of the codebase easier to read.
2. Tests and local scripts can substitute a fake `S3Client` instead of
   mocking individual boto3 calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

# boto3 is the AWS SDK for Python. It auto-discovers credentials from the
# environment, the AWS_PROFILE, or the IAM role attached to the Lambda.
import boto3


@dataclass(frozen=True)
class S3ObjectRef:
    """Reference to an object stored in S3.

    Using a small dataclass instead of passing `(bucket, key)` tuples
    around makes call sites self-documenting and lets us derive the
    pretty S3 URI in one place.
    """

    bucket: str
    key: str

    @property
    def uri(self) -> str:
        """Return a human-readable S3 URI used in citations and logs."""
        # `s3://<bucket>/<key>` is the canonical S3 URI format. The UI shows
        # this string to the user as the source of a retrieved chunk.
        return f"s3://{self.bucket}/{self.key}"


class S3Client:
    """Small S3 client wrapper for reading and listing PDF objects."""

    def __init__(self, region_name: str):
        """Create a boto3 S3 client in the selected AWS region.

        The Lambda environment variable AWS_REGION normally feeds this
        value via `Settings.aws_region`. Pinning the region prevents the
        SDK from defaulting to whatever is in `~/.aws/config` during
        local development.
        """
        self._client = boto3.client("s3", region_name=region_name)

    def read_bytes(self, bucket: str, key: str) -> bytes:
        """Download an S3 object and return its raw bytes.

        `get_object` returns a streaming body. We read it fully into memory
        because PDFs in this workshop are small (kilobytes). For huge files
        you would stream chunks instead.
        """
        response = self._client.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    def list_pdf_objects(self, bucket: str, prefix: str) -> Iterable[S3ObjectRef]:
        """Yield all PDF objects under an S3 prefix.

        The paginator transparently handles the "next continuation token"
        protocol so buckets with more than 1000 objects still iterate
        correctly. The function is a generator (note `yield`) so the
        caller can start processing the first PDF without waiting for
        the entire bucket listing.
        """
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            # An empty bucket page may not include `Contents` at all.
            for item in page.get("Contents", []):
                key = item["Key"]
                # Filter out non-PDF entries (logs, manifests, folder
                # markers) so we never try to extract text from them.
                if key.lower().endswith(".pdf"):
                    yield S3ObjectRef(bucket=bucket, key=key)
