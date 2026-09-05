"""Text chunking utilities for PDF pages.

WHY CHUNK?
----------
RAG systems rarely embed an entire document at once. Three reasons:

1. Embedding models have a hard input token limit.
2. Vector search returns the closest chunk — small chunks give finer
   "best match" granularity than embedding a whole document.
3. The final LLM prompt has limited context. Sending only the few
   relevant chunks is faster and cheaper than sending whole PDFs.

WHY OVERLAP?
------------
A relevant sentence can fall right on the boundary between two chunks.
If the previous chunk cuts off mid-sentence, neither chunk fully contains
the answer. A small overlap keeps boundary context intact at the cost of
slightly more storage.

THIS MODULE
-----------
Turns page-level PDF text into chunk objects that include:
- a stable `chunk_id` for traceability
- the chunk text itself
- metadata used for citations (document name, page number, etc.)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List

# Page model from `pdf_loader.py`. Relative import so the package is
# self-contained regardless of how it is mounted in the Lambda zip.
from .pdf_loader import PdfPage


@dataclass(frozen=True)
class DocumentChunk:
    """A retrievable piece of text plus citation metadata.

    The `metadata` dict is intentionally typed as `str | int` so it can hold
    a mix of strings (document_name, source_uri) and integers (page_number).
    """

    chunk_id: str
    text: str
    metadata: Dict[str, str | int]


def _clean_text(text: str) -> str:
    """Normalize whitespace before chunking.

    - Collapse runs of spaces/tabs into a single space so we do not waste
      chunk capacity on whitespace.
    - Collapse 3+ consecutive newlines into a paragraph break (\\n\\n)
      so paragraph detection by the splitter still works.
    """
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _split_text(text: str, chunk_size: int, chunk_overlap: int) -> Iterable[str]:
    """Split text into overlapping chunks.

    The splitter prefers paragraph or sentence boundaries when they are near
    the requested chunk size. Overlap keeps context at chunk boundaries from
    being lost during retrieval.

    Algorithm:
      1. If the whole text fits in one chunk, yield it as-is.
      2. Otherwise slide a window of `chunk_size` characters across the
         text. Within each window, try to back off to the nearest natural
         boundary (paragraph break, sentence end, semicolon) if it lies
         in the last ~45% of the window.
      3. Advance the window by `chunk_size - chunk_overlap` so consecutive
         chunks share `chunk_overlap` characters.
    """
    cleaned = _clean_text(text)
    # Short-circuit: no splitting needed.
    if len(cleaned) <= chunk_size:
        yield cleaned
        return

    start = 0
    while start < len(cleaned):
        # `end` is the proposed (exclusive) end of this chunk.
        end = min(start + chunk_size, len(cleaned))
        window = cleaned[start:end]

        if end < len(cleaned):
            # Try to back off to a natural boundary near the end of the
            # window. We check paragraph break first, then sentence end,
            # then semicolon. `rfind` returns -1 if not found.
            break_at = max(window.rfind("\n\n"), window.rfind(". "), window.rfind("; "))
            # Only use the boundary when it lies past ~55% of the window;
            # otherwise we would produce very small chunks.
            if break_at > chunk_size * 0.55:
                end = start + break_at + 1
                window = cleaned[start:end]

        # Emit the chunk, stripped of leading/trailing whitespace.
        yield window.strip()

        # Stop if we have consumed everything.
        if end >= len(cleaned):
            break
        # Advance with overlap. `max(..., start + 1)` is a safety guard so
        # we cannot get stuck in an infinite loop if overlap >= chunk_size.
        start = max(end - chunk_overlap, start + 1)


def build_chunks(
    pages: List[PdfPage],
    document_name: str,
    source_uri: str,
    chunk_size: int,
    chunk_overlap: int,
) -> List[DocumentChunk]:
    """Build all chunks for one document while preserving source metadata.

    We chunk page-by-page (not document-by-document) so the page number
    stays accurate in the resulting metadata. Citations like "see page 4"
    only work if the chunk knows which page it came from.
    """
    chunks: List[DocumentChunk] = []
    for page in pages:
        # `local_index` numbers chunks within a single page (1, 2, ...).
        # Combined with the document name and page number it forms a
        # globally unique chunk_id used for debugging and traceability.
        for local_index, text in enumerate(_split_text(page.text, chunk_size, chunk_overlap), start=1):
            chunk_id = f"{document_name}|page-{page.page_number}|chunk-{local_index}"
            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_id,
                    text=text,
                    metadata={
                        "document_name": document_name,
                        "page_number": page.page_number,
                        "source_uri": source_uri,
                        "chunk_local_index": local_index,
                    },
                )
            )
    return chunks
