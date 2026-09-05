"""OpenSearch Serverless vector index helper.

OpenSearch Serverless (AOSS) uses SigV4-signed HTTPS requests rather than
the username/password auth most OpenSearch tutorials show. This module
hides the request signing and JSON request bodies so the ingestion and
query pipelines can focus on RAG logic rather than OpenSearch API details.

OPERATIONS SUPPORTED
--------------------
- `create_index`  build the k-NN index with the correct mapping
- `delete_index`  reset the workshop
- `index_exists`  idempotency check used by setup scripts
- `bulk_index`    write many chunk documents efficiently
- `vector_search` retrieve the top-k closest chunks for a query
"""

from __future__ import annotations

import json
from typing import Any, Dict, List
# `quote` URL-encodes path components like the index name.
from urllib.parse import quote

import boto3
# The `requests` library is used directly because it integrates cleanly
# with `requests_aws4auth` for SigV4 signing.
import requests
from requests_aws4auth import AWS4Auth


class OpenSearchVectorClient:
    """Create, write to, and search an OpenSearch Serverless vector index."""

    def __init__(self, endpoint: str, region_name: str, index_name: str):
        """Prepare SigV4 authentication for OpenSearch Serverless.

        The service name for OpenSearch Serverless data-plane requests is
        `aoss`, which is why AWS4Auth uses that value below. Sending the
        wrong service name produces an "InvalidSignatureException".
        """
        # Normalize the endpoint by stripping any trailing slash so we can
        # safely concatenate paths with leading slashes elsewhere.
        self.endpoint = endpoint.rstrip("/")
        self.index_name = index_name

        # Resolve credentials from the standard boto3 chain (env vars,
        # AWS_PROFILE, IAM role). Lambda execution roles flow through here.
        credentials = boto3.Session().get_credentials()
        if credentials is None:
            raise RuntimeError("Unable to resolve AWS credentials for OpenSearch signing.")

        # `get_frozen_credentials()` snapshots the access/secret/session
        # token so AWS4Auth has stable values even if the underlying
        # credentials object refreshes (e.g., role assumption).
        frozen = credentials.get_frozen_credentials()
        self.auth = AWS4Auth(
            frozen.access_key,
            frozen.secret_key,
            region_name,
            "aoss",                         # <-- service name for OpenSearch Serverless
            session_token=frozen.token,
        )

    def create_index(self, dimension: int) -> Dict[str, Any]:
        """Create the vector index and mapping used by the workshop.

        `embedding` is the vector field. The other fields are metadata used
        for citations and source display in the UI.

        Index settings:
        - `knn: true` enables k-Nearest-Neighbour search on the index.
        - `ef_search: 100` is the HNSW search-time parameter; higher values
          improve recall at the cost of latency.

        Embedding field:
        - `type: knn_vector` with `dimension` MUST match the embedding model.
        - HNSW + FAISS + cosine similarity is the standard combination for
          dense retrieval.
        """
        mapping = {
            "settings": {"index": {"knn": True, "knn.algo_param.ef_search": 100}},
            "mappings": {
                "properties": {
                    "embedding": {
                        "type": "knn_vector",
                        "dimension": dimension,
                        "method": {
                            "name": "hnsw",
                            "engine": "nmslib",
                            "space_type": "cosinesimil",
                            # ef_construction controls build-time graph
                            # quality; m is the HNSW node fan-out.
                            "parameters": {"ef_construction": 512, "m": 16},
                        },
                    },
                    # `text` is full-text searchable and tokenized.
                    "text": {"type": "text"},
                    # `keyword` fields are exact-match (no tokenization),
                    # which is what we want for filename and uri filters.
                    "document_name": {"type": "keyword"},
                    "page_number": {"type": "integer"},
                    "source_uri": {"type": "keyword"},
                    "chunk_id": {"type": "keyword"},
                }
            },
        }
        # PUT /<index-name> with the mapping JSON creates the index.
        return self._request("PUT", f"/{quote(self.index_name)}", body=mapping)

    def delete_index(self) -> Dict[str, Any]:
        """Delete the configured index. Useful when resetting the workshop."""
        return self._request("DELETE", f"/{quote(self.index_name)}")

    def index_exists(self) -> bool:
        """Return True when the configured index already exists.

        OpenSearch responds to HEAD with 200 (exists) or 404 (not found).
        We translate that into a clean boolean instead of letting the
        caller deal with HTTP status codes.
        """
        response = requests.head(
            f"{self.endpoint}/{quote(self.index_name)}",
            auth=self.auth,
            timeout=30,
        )
        if response.status_code == 404:
            return False
        # Any other non-2xx is unexpected — raise so the caller notices.
        response.raise_for_status()
        return True

    def bulk_index(self, documents: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Write many chunk documents to OpenSearch in one bulk request.

        The `_bulk` endpoint expects newline-delimited JSON ("NDJSON"):

            { "index": { "_index": "<name>" } }
            { ...doc 1... }
            { "index": { "_index": "<name>" } }
            { ...doc 2... }

        OpenSearch Serverless rejects custom `_id` values in this path, so
        `chunk_id` is stored as a normal metadata field and OpenSearch
        generates the internal document id automatically.
        """
        # Nothing to do for an empty batch — avoid sending a malformed
        # request to OpenSearch.
        if not documents:
            return {"items": []}

        # Build the NDJSON body line by line.
        lines = []
        for document in documents:
            # Action line: tell OpenSearch which index to write to.
            lines.append(json.dumps({"index": {"_index": self.index_name}}))
            # Source line: the actual document.
            lines.append(json.dumps(document))
        # The body MUST end with a trailing newline.
        payload = "\n".join(lines) + "\n"

        # NDJSON content type is mandatory for the `_bulk` endpoint.
        return self._request(
            "POST",
            "/_bulk",
            raw_body=payload,
            headers={"Content-Type": "application/x-ndjson"},
        )

    def vector_search(self, query_embedding: List[float], top_k: int) -> List[Dict[str, Any]]:
        """Find the top-k chunks closest to the query embedding.

        The body uses OpenSearch's k-NN query DSL. `_source` is restricted
        to the fields we need for citations, which keeps response payloads
        small.
        """
        body = {
            "size": top_k,
            "query": {
                "knn": {
                    "embedding": {
                        "vector": query_embedding,
                        "k": top_k,
                    }
                }
            },
            "_source": ["text", "document_name", "page_number", "source_uri", "chunk_id"],
        }
        response = self._request("POST", f"/{quote(self.index_name)}/_search", body=body)
        # The OpenSearch response wraps results under `hits.hits`. Each hit
        # has `_source` (our stored fields) and `_score` (the similarity).
        hits = response.get("hits", {}).get("hits", [])
        results = []
        for hit in hits:
            source = hit.get("_source", {})
            # Promote the score so callers see it alongside metadata.
            source["score"] = hit.get("_score")
            results.append(source)
        return results

    def _request(
        self,
        method: str,
        path: str,
        body: Dict[str, Any] | None = None,
        raw_body: str | None = None,
        headers: Dict[str, str] | None = None,
    ) -> Dict[str, Any]:
        """Send a signed HTTP request to OpenSearch Serverless.

        - `body` is JSON-serialized automatically.
        - `raw_body` is passed through as-is (used for NDJSON bulk uploads).
        - SigV4 signing is applied by the `requests_aws4auth` auth handler.
        """
        # Default content type for normal JSON requests.
        final_headers = {"Content-Type": "application/json"}
        if headers:
            final_headers.update(headers)

        # Decide which body representation to send.
        data = raw_body if raw_body is not None else json.dumps(body or {})

        response = requests.request(
            method,
            f"{self.endpoint}{path}",
            auth=self.auth,
            data=data,
            headers=final_headers,
            timeout=60,
        )

        # HEAD returns no body, even on 404. Special-case the 404 so we can
        # express "does not exist" as `{}` rather than raising.
        if response.status_code == 404 and method == "HEAD":
            return {}

        # Any other non-2xx is an unexpected error: raise to bubble up.
        response.raise_for_status()

        # Some operations (e.g., DELETE) return an empty body on success.
        if not response.text:
            return {}
        return response.json()
