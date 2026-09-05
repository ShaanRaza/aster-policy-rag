#!/usr/bin/env python3
"""Upload static frontend files to the S3 website bucket.

The workshop's UI is a simple static site (HTML/CSS/JS) hosted from S3 with
public website hosting enabled. This script syncs the local `frontend/`
directory to the S3 bucket and, critically, sets the correct `Content-Type`
header on each object.

WHY CONTENT-TYPE MATTERS
------------------------
If a `.js` or `.css` file is served with `Content-Type: binary/octet-stream`
(the S3 default when none is provided), most browsers will refuse to execute
it or apply it. Setting the correct MIME type per file is what makes the
site actually load and work in the browser.
"""

from __future__ import annotations

# Argument parsing.
import argparse
# Standard library mapping from file extension to MIME type.
import mimetypes
# Path utilities for walking the frontend directory.
from pathlib import Path

# AWS SDK to perform the upload.
import boto3


def main() -> None:
    """Upload each file in `frontend/` with an appropriate content type."""
    parser = argparse.ArgumentParser(description="Upload static frontend files to an S3 website bucket.")
    # Destination bucket (must have static website hosting enabled separately).
    parser.add_argument("--bucket", required=True)
    # Default to the conventional folder location.
    parser.add_argument("--frontend-dir", default="frontend")
    # boto3 will resolve from the active AWS profile if omitted.
    parser.add_argument("--region", default=None)
    args = parser.parse_args()

    s3 = boto3.client("s3", region_name=args.region)

    # Resolve and iterate over the top-level files in `frontend/`. We do not
    # recurse — the workshop UI is intentionally flat (index.html, app.js,
    # styles.css, etc.).
    frontend_dir = Path(args.frontend_dir)
    for path in sorted(frontend_dir.iterdir()):
        # Skip directories: nothing to upload directly.
        if not path.is_file():
            continue

        # `mimetypes.guess_type` returns `(type, encoding)`. We only need the
        # MIME type. Fall back to `application/octet-stream` for unknown
        # extensions so the upload still succeeds for assets like fonts.
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

        # `ExtraArgs` is how boto3 passes per-object metadata such as headers
        # that the browser will see when fetching the object.
        s3.upload_file(
            str(path),
            args.bucket,
            path.name,
            ExtraArgs={"ContentType": content_type},
        )
        print(f"Uploaded {path.name} as {content_type}")


if __name__ == "__main__":
    main()
