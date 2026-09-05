"""PDF text extraction helpers.

The ingestion Lambda receives raw PDF bytes from S3. This module extracts
text page by page so downstream chunks can keep page numbers for citations.

We use `pypdf` (pure-Python, MIT licensed) because it bundles cleanly into
a Lambda zip without needing native binaries the way `pdfminer.six` or
poppler-based tools would.
"""

from __future__ import annotations

from dataclasses import dataclass
# `BytesIO` lets us pass raw bytes to pypdf without writing them to disk.
from io import BytesIO
from typing import List

from pypdf import PdfReader


@dataclass(frozen=True)
class PdfPage:
    """Text extracted from one PDF page.

    Keeping `page_number` next to the extracted text is what lets the RAG
    pipeline cite "see Page 3 of policy.pdf" in its answers.
    """

    page_number: int
    text: str


def extract_pdf_pages(pdf_bytes: bytes) -> List[PdfPage]:
    """Extract normalized text from all readable pages in a PDF.

    Steps:
    1. Wrap the bytes in `BytesIO` so pypdf can read them as a stream.
    2. Iterate over every page; pypdf is 0-indexed internally so we use
       `enumerate(..., start=1)` to produce human-readable page numbers.
    3. Normalize whitespace: strip blank lines and trailing spaces so the
       chunker downstream has cleaner input.
    4. Skip pages with no extractable text (image-only pages, OCR not run).
    """
    reader = PdfReader(BytesIO(pdf_bytes))
    pages: List[PdfPage] = []
    for index, page in enumerate(reader.pages, start=1):
        # pypdf returns `None` for pages with no extractable text — use
        # `or ""` so the splitline call below cannot blow up.
        text = page.extract_text() or ""
        # Per-line strip removes trailing whitespace; the comprehension
        # filter drops blank lines so 5 consecutive blanks do not waste
        # chunk capacity.
        normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if normalized:
            pages.append(PdfPage(page_number=index, text=normalized))
    return pages
