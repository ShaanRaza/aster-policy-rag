"""Query-time RAG pipeline.

This module implements the core user question flow:

1. Embed the user question with the SAME embedding model used at ingest
   time. Using the same model is what makes vector similarity meaningful
   — different models live in different vector spaces.
2. Retrieve the top-k semantically similar chunks from OpenSearch.
3. Build a grounded prompt that includes those chunks as context.
4. Ask Bedrock (Nova / Anthropic / Titan) to generate the answer.
5. Return the answer plus citation metadata that the UI uses to show
   "see policy.pdf page 4" links next to the answer.

Like the ingestion pipeline, this class has its dependencies injected
via the constructor so testing with fakes is easy.
"""

from __future__ import annotations

from typing import Dict, List

from .bedrock_client import BedrockClient
from .config import Settings
from .opensearch_client import OpenSearchVectorClient
from .prompt_builder import build_grounded_prompt


class RagPipeline:
    """Coordinates retrieval and generation for one user question."""

    def __init__(
        self,
        settings: Settings,
        bedrock_client: BedrockClient,
        opensearch_client: OpenSearchVectorClient,
    ):
        """Receive configured service clients from the Lambda handler."""
        self.settings = settings
        self.bedrock_client = bedrock_client
        self.opensearch_client = opensearch_client

    def answer_question(self, question: str, top_k: int | None = None) -> Dict:
        """Answer a natural-language question using retrieved document chunks.

        `top_k=None` falls back to the default in `Settings`, but the
        query Lambda may pass a per-request override (already clamped to
        a safe range) so the UI can tune retrieval depth.

        The return value matches what `query_handler/app.py` sends back
        to the frontend:

            {
              "answer":    str,
              "citations": [ { citation_id, document_name, page_number,
                               source_uri, score, chunk_id, preview }, ... ]
            }
        """
        # Honour the per-request override if present.
        selected_top_k = top_k or self.settings.top_k

        # The query must be embedded with the same model used for document
        # chunks; mismatched models produce meaningless similarities.
        query_embedding = self.bedrock_client.embed_text(question)

        # Retrieve the top-k chunks closest to the query in vector space.
        chunks = self.opensearch_client.vector_search(query_embedding, selected_top_k)

        # Build the grounded prompt that contains the retrieved context
        # plus instructions to cite sources by bracket number.
        prompt = build_grounded_prompt(question, chunks, self.settings.max_context_chars)

        # Ask the LLM for an answer.
        answer = self.bedrock_client.generate_answer(prompt)

        # Build citation metadata in the SAME ORDER used in the prompt so
        # the bracket numbers the model emits (`[1]`, `[2]`, ...) line up
        # with the citations the UI renders.
        citations: List[Dict] = []
        for index, chunk in enumerate(chunks, start=1):
            citations.append(
                {
                    "citation_id": index,
                    "document_name": chunk.get("document_name"),
                    "page_number": chunk.get("page_number"),
                    "source_uri": chunk.get("source_uri"),
                    "score": chunk.get("score"),
                    "chunk_id": chunk.get("chunk_id"),
                    # `preview` is a short text excerpt so the UI can show
                    # a hint of the source chunk without dumping the whole
                    # thing onto the page.
                    "preview": chunk.get("text", "")[:420],
                }
            )
        return {"answer": answer, "citations": citations}
