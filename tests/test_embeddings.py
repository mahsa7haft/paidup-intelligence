"""
Tests for embeddings.py — the OpenAI client is mocked, so no API calls are made.
"""

from unittest.mock import MagicMock, patch

import pytest

from app import embeddings


@pytest.fixture(autouse=True)
def reset_client():
    """Clear the cached client between tests so patches take effect."""
    embeddings._client = None
    yield
    embeddings._client = None


def _mock_openai(vector):
    """Mock OpenAI client whose embeddings.create returns one embedding."""
    item = MagicMock()
    item.embedding = vector
    response = MagicMock()
    response.data = [item]
    client = MagicMock()
    client.embeddings.create.return_value = response
    return client


class TestEmbedQuery:
    def test_returns_vector(self):
        client = _mock_openai([0.1, 0.2, 0.3])
        with patch("app.embeddings._get_client", return_value=client):
            result = embeddings.embed_query("renewable energy")
        assert result == [0.1, 0.2, 0.3]

    def test_uses_configured_model(self):
        client = _mock_openai([0.0])
        with patch("app.embeddings._get_client", return_value=client):
            embeddings.embed_query("hello")
        kwargs = client.embeddings.create.call_args.kwargs
        assert kwargs["model"] == embeddings.EMBED_MODEL
        assert kwargs["input"] == ["hello"]

    def test_empty_query_raises(self):
        with pytest.raises(ValueError, match="empty"):
            embeddings.embed_query("")

    def test_whitespace_only_query_raises(self):
        with pytest.raises(ValueError, match="empty"):
            embeddings.embed_query("   ")

    def test_strips_whitespace(self):
        client = _mock_openai([0.5])
        with patch("app.embeddings._get_client", return_value=client):
            embeddings.embed_query("  hello  ")
        assert client.embeddings.create.call_args.kwargs["input"] == ["hello"]


class TestGetClient:
    def test_raises_without_api_key(self, monkeypatch):
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
            embeddings._get_client()
