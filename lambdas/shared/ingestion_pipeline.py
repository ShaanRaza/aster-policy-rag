"""End-to-end ingestion pipeline for one PDF object in S3.

The ingestion Lambda calls this pipeline after an S3 upload event. The
pipeline downloads the PDF, extracts text, chunks it, embeds each chunk,
and writes the resulting records into OpenSearch Serverless.

FLOW DIAGRAM
------------
       S3 PDF
         |
         v
     read_bytes  -> raw PDF bytes
         |
         v
  extract_pdf_pages  -> list[PdfPage] (page_number + text)
         |
         v
     build_chunks  -> list[DocumentChunk] (text + metadata)
         |
         v
    embed_text     -> list[float]  (per chunk)
         |
         v
     bulk_index    -> vectors + metadata stored in OpenSearch
"""

from __future__ import annotations

import os
from typing import Dict, List

# Relative imports so the package stays portable regardless of how the
# Lambda zip is mounted.
from .bedrock_client import BedrockClient
from .chunker import build_chunks
from .config import Settings
from .logger import get_logger
from .opensearch_client import OpenSearchVectorClient
from .pdf_loader import extract_pdf_pages
from .s3_client import S3Client

logger = get_logger(__name__)


class IngestionPipeline:
    """Coordinates PDF ingestion dependencies and workflow steps.

    Dependencies are injected via the constructor. This makes it trivial to
    swap any client for a fake during tests (e.g., a stub `BedrockClient`
    that returns canned vectors).
    """

    def __init__(
        self,
        settings: Settings,
        s3_client: S3Client,
        bedrock_client: BedrockClient,
        opensearch_client: OpenSearchVectorClient,
    ):
        """Receive already-configured AWS clients from the Lambda handler."""
        self.settings = settings
        self.s3_client = s3_client
        self.bedrock_client = bedrock_client
        self.opensearch_client = opensearch_client

    def ingest_s3_pdf(self, bucket: str, key: str) -> Dict:
        """Ingest one PDF from S3 into the vector index.

        Returns a dict suitable for serialising into the Lambda response.
        Raises on hard failures so the Lambda invocation is marked failed
        in CloudWatch (allowing alerting and DLQ behaviour to work).
        """
        # Skip non-PDFs early. The S3 event filter normally prevents this,
        # but the manual / backfill path can still pass any key in.
        if not key.lower().endswith(".pdf"):
            logger.info("Skipping non-PDF object: s3://%s/%s", bucket, key)
            return {"skipped": True, "reason": "not_pdf", "bucket": bucket, "key": key}

        # ---- 1) Download ----
        logger.info("Reading PDF from s3://%s/%s", bucket, key)
        pdf_bytes = self.s3_client.read_bytes(bucket, key)
        logger.info("Downloaded %s bytes from s3://%s/%s", len(pdf_bytes), bucket, key)

        # ---- 2) Extract text per page ----
        pages = extract_pdf_pages(pdf_bytes)
        logger.info("Extracted %s text page(s) from s3://%s/%s", len(pages), bucket, key)

        # Friendly names for citations. `document_name` is the filename only
        # (no S3 prefix), while `source_uri` is the full S3 URI for deep
        # linking from the UI.
        document_name = os.path.basename(key)
        source_uri = f"s3://{bucket}/{key}"

        # ---- 3) Chunk ----
        # Chunking is page-aware so citations can point back to PDF pages.
        chunks = build_chunks(
            pages,
            document_name=document_name,
            source_uri=source_uri,
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
        )
        logger.info("Built %s chunk(s) for %s", len(chunks), source_uri)

        # Hard validation: a PDF with no extractable text means OCR is needed
        # or the PDF is image-only. Either way ingesting it would be pointless.
        if not pages:
            raise ValueError(f"No extractable text pages found in {source_uri}")
        if not chunks:
            raise ValueError(f"No chunks created for {source_uri}")

        # ---- 4) Embed each chunk ----
        documents: List[Dict] = []
        for index, chunk in enumerate(chunks, start=1):
            # Log every chunk so attendees can watch progress in CloudWatch.
            logger.info("Embedding chunk %s/%s: %s", index, len(chunks), chunk.chunk_id)
            embedding = self.bedrock_client.embed_text(chunk.text)
            # The document stored in OpenSearch contains both the vector
            # (for retrieval) and the metadata (for citations + display).
            documents.append(
                {
                    "chunk_id": chunk.chunk_id,
                    "text": chunk.text,
                    "embedding": embedding,
                    "document_name": chunk.metadata["document_name"],
                    "page_number": chunk.metadata["page_number"],
                    "source_uri": chunk.metadata["source_uri"],
                }
            )

        # ---- 5) Bulk index ----
        logger.info("Indexing %s chunks for %s", len(documents), source_uri)
        bulk_response = self.opensearch_client.bulk_index(documents)
        # The OpenSearch bulk API reports per-item failures via `errors: true`.
        # We treat any partial failure as a hard error to keep the demo
        # behaviour deterministic.
        errors = bulk_response.get("errors", False)
        if errors:
            raise RuntimeError(f"OpenSearch bulk indexing reported errors: {str(bulk_response)[:2000]}")
        logger.info("OpenSearch bulk indexing succeeded for %s", source_uri)

        # Return a small summary used by the Lambda response body and logs.
        return {
            "bucket": bucket,
            "key": key,
            "page_count": len(pages),
            "chunk_count": len(chunks),
            "bulk_errors": errors,
        }
