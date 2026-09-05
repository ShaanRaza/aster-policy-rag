"""Small wrapper around Amazon Bedrock Runtime calls used by the RAG pipeline.

The project uses Bedrock for two different jobs:

1. Embeddings — convert text chunks and user questions into vectors that
   can be compared with cosine similarity inside OpenSearch.
2. Generation — ask an LLM to answer using the retrieved context.

Keeping both operations behind this class hides the AWS-specific payload
shapes from the rest of the pipeline. That makes the high-level RAG code
much easier to read for workshop attendees.

The class also handles the fact that different Bedrock models use
different invocation patterns:

- Nova models use the `Converse` API (chat-style messages).
- Anthropic models use `InvokeModel` with a Messages API JSON body.
- Titan text models use `InvokeModel` with `inputText` + `textGenerationConfig`.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import boto3


class BedrockClient:
    """Client for Bedrock embedding and text-generation models."""

    def __init__(self, region_name: str, embed_model_id: str, llm_model_id: str):
        """Create a Bedrock Runtime client for the configured AWS region.

        Storing the model ids on the instance keeps call sites short
        (`client.embed_text(text)` rather than `client.embed_text(text, model)`).
        """
        # `bedrock-runtime` is the data-plane service used for invocations.
        # (The control-plane service `bedrock` is for managing model access.)
        self._runtime = boto3.client("bedrock-runtime", region_name=region_name)
        self.embed_model_id = embed_model_id
        self.llm_model_id = llm_model_id

    def embed_text(self, text: str) -> List[float]:
        """Return a vector embedding for a single text string.

        Titan Embeddings v2 expects `{"inputText": "..."}` and returns
        `{"embedding": [float, float, ...]}`. The same vector representation
        is used for both document chunks (at ingest time) and user questions
        (at query time) — that symmetry is what makes vector search work.
        """
        body = json.dumps({"inputText": text})
        response = self._runtime.invoke_model(
            modelId=self.embed_model_id,
            body=body,
            accept="application/json",
            contentType="application/json",
        )
        # Bedrock returns a streaming body; we read it fully and decode JSON.
        payload = json.loads(response["body"].read())
        # Guard against unexpected response shapes so misconfigured models
        # fail with a clear error rather than a confusing IndexError later.
        if "embedding" not in payload:
            raise ValueError(f"Embedding response did not include 'embedding': {payload.keys()}")
        return payload["embedding"]

    def generate_answer(self, prompt: str, max_tokens: int = 900) -> str:
        """Generate an answer from the final grounded RAG prompt.

        Dispatches to the correct Bedrock API based on the model id:
        - Nova models -> Converse API.
        - Everything else -> InvokeModel with a model-specific payload.
        """
        # Branch 1: Nova models require the chat-shaped Converse API.
        if self._uses_converse_api():
            return self._generate_answer_with_converse(prompt, max_tokens=max_tokens)

        # Branch 2: Build a model-specific InvokeModel payload.
        body = self._build_generation_payload(prompt, max_tokens=max_tokens)
        response = self._runtime.invoke_model(
            modelId=self.llm_model_id,
            body=json.dumps(body),
            accept="application/json",
            contentType="application/json",
        )
        payload = json.loads(response["body"].read())
        return self._parse_generation_response(payload)

    def _uses_converse_api(self) -> bool:
        """Amazon Nova chat models are invoked with Bedrock's Converse API.

        Inference-profile ids (`us.amazon.nova-...`) are also Nova, hence
        the prefix tuple check.
        """
        return self.llm_model_id.startswith(("amazon.nova-", "us.amazon.nova-"))

    def _generate_answer_with_converse(self, prompt: str, max_tokens: int) -> str:
        """Call Bedrock Converse for Amazon Nova generation.

        The model id in this workshop is an inference profile:
        `us.amazon.nova-lite-v1:0`. Converse expects messages in a
        chat-style structure with explicit `role` and `content` parts.

        `temperature=0` keeps generations deterministic for the workshop
        demo. `topP=0.9` is Bedrock's recommended default for Nova.
        """
        response = self._runtime.converse(
            modelId=self.llm_model_id,
            messages=[
                {
                    "role": "user",
                    "content": [{"text": prompt}],
                }
            ],
            inferenceConfig={
                "maxTokens": max_tokens,
                "temperature": 0,
                "topP": 0.9,
            },
        )
        # The response is shaped like:
        #   { "output": { "message": { "content": [ {"text": "..."} ] } } }
        # We extract every text part and join them with newlines.
        message = response.get("output", {}).get("message", {})
        content = message.get("content", [])
        text_parts = [item.get("text", "") for item in content if "text" in item]
        return "\n".join(part.strip() for part in text_parts if part.strip())

    def _build_generation_payload(self, prompt: str, max_tokens: int) -> Dict[str, Any]:
        """Build an InvokeModel payload for non-Nova models.

        This fallback lets learners swap in other Bedrock models later
        without having to change the pipeline structure. We support:

        - Anthropic Messages API (Claude on Bedrock).
        - Amazon Titan text generation (legacy InvokeModel shape).
        """
        # Anthropic models on Bedrock use the Messages API JSON body.
        if self.llm_model_id.startswith("anthropic.") or ".anthropic." in self.llm_model_id:
            return {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "temperature": 0,
                "messages": [{"role": "user", "content": prompt}],
            }
        # Default to Titan's text generation payload.
        return {
            "inputText": prompt,
            "textGenerationConfig": {
                "maxTokenCount": max_tokens,
                "temperature": 0,
                "topP": 0.9,
            },
        }

    def _parse_generation_response(self, payload: Dict[str, Any]) -> str:
        """Extract generated text from common Bedrock response shapes.

        Different model families return text in different fields:

        - Anthropic Messages: `{"content": [{"text": "..."}]}`
        - Titan text: `{"results": [{"outputText": "..."}]}`
        - Generic / legacy: `{"output": "..."}`
        """
        # Anthropic shape.
        if "content" in payload and payload["content"]:
            first = payload["content"][0]
            if isinstance(first, dict) and "text" in first:
                return first["text"].strip()
        # Titan shape.
        if "results" in payload and payload["results"]:
            return payload["results"][0].get("outputText", "").strip()
        # Generic fallback.
        if "output" in payload:
            return str(payload["output"]).strip()
        # As a last resort, return the entire payload as a JSON string so
        # debugging can see what came back.
        return json.dumps(payload)
