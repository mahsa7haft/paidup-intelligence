"""
Embed query strings for semantic search.

The ingestion scripts embed *documents* at write time; this embeds the *question*
at read time, using the same model so the vectors live in the same space.
"""

import os

from openai import OpenAI

from app.config import EMBED_MODEL

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Lazily create one OpenAI client and reuse it across calls."""
    global _client
    if _client is None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY not set")
        _client = OpenAI()
    return _client


def embed_query(text: str) -> list[float]:
    """Turn a query string into a 1536-dim embedding vector."""
    text = (text or "").strip()
    if not text:
        raise ValueError("Cannot embed an empty query")
    response = _get_client().embeddings.create(model=EMBED_MODEL, input=[text])
    return response.data[0].embedding
