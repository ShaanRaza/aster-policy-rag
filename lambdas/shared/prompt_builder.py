"""Prompt construction for grounded answer generation.

The "grounded prompt" is the single biggest lever in a RAG system. It
controls:

- Whether the model uses retrieved context at all (vs. hallucinating).
- How the model cites its sources.
- What it says when the context does not contain the answer.

We intentionally keep this prompt strict and short. Long preamble eats
token budget that would otherwise be used for context.
"""

from __future__ import annotations

from typing import Dict, List


def build_grounded_prompt(question: str, retrieved_chunks: List[Dict], max_context_chars: int) -> str:
    """Build the final LLM prompt from retrieved chunks.

    The prompt is intentionally strict: answer only from context, cite
    sources, and admit when the retrieved documents do not contain the
    answer.

    `max_context_chars` caps how many characters of retrieved context we
    fit into the prompt. Anything past that is dropped. This protects
    against runaway prompt sizes when many chunks come back from
    OpenSearch.
    """
    # Build "[N] document.pdf page X\n<chunk text>" blocks. The bracket
    # number is what the LLM is asked to use when citing a source. The
    # ordering here MUST match the citation list returned by the pipeline
    # to the UI — RagPipeline does the same `enumerate(..., start=1)`.
    context_blocks = []
    used_chars = 0
    for index, chunk in enumerate(retrieved_chunks, start=1):
        citation = f"[{index}] {chunk.get('document_name')} page {chunk.get('page_number')}"
        text = chunk.get("text", "").strip()
        block = f"{citation}\n{text}"

        # Enforce the context budget. We stop adding blocks once the
        # cumulative size would exceed the limit, rather than truncating
        # mid-chunk (which can produce awkward fragments).
        if used_chars + len(block) > max_context_chars:
            break

        context_blocks.append(block)
        used_chars += len(block)

    # Join with blank lines so the model can tell where one source ends
    # and the next one begins.
    context = "\n\n".join(context_blocks)

    # The actual prompt. Notes:
    # - "internal policy assistant" sets the role.
    # - The "Rules" section gives the model explicit constraints. Phrasing
    #   them as imperative rules is more effective than soft suggestions.
    # - Trailing "Answer:" signals to the model where its turn begins.
    return f"""You are an internal policy assistant. Answer the user's question using only the provided context.

Rules:
- If the answer is not in the context, say that the policy documents do not provide enough information.
- Cite sources inline using bracket numbers like [1] and [2].
- Be concise, practical, and specific.
- Do not invent policy details.

Context:
{context}

Question:
{question}

Answer:"""
