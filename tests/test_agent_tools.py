"""
Tests for agent_tools.py — embed + search are mocked, so no DB or API key needed.
"""

from unittest.mock import patch

from app import agent_tools


def _patched():
    return (
        patch("app.agent_tools.embed_query", return_value=[0.1, 0.2]),
        patch("app.agent_tools.similarity_search", return_value=[{"source_id": "x"}]),
    )


class TestTools:
    def test_search_interests_targets_interests_table(self):
        p_embed, p_search = _patched()
        with p_embed, p_search as mock_search:
            result = agent_tools.search_interests.invoke({"query": "oil", "k": 3})
        mock_search.assert_called_once_with("interests_vectors", [0.1, 0.2], 3)
        assert result == [{"source_id": "x"}]

    def test_search_party_donations_targets_donations_table(self):
        p_embed, p_search = _patched()
        with p_embed, p_search as mock_search:
            agent_tools.search_party_donations.invoke({"query": "oil", "k": 2})
        mock_search.assert_called_once_with("party_donations_vectors", [0.1, 0.2], 2)

    def test_search_votes_targets_votes_table(self):
        p_embed, p_search = _patched()
        with p_embed, p_search as mock_search:
            agent_tools.search_votes.invoke({"query": "energy", "k": 5})
        mock_search.assert_called_once_with("votes_vectors", [0.1, 0.2], 5)


class TestToolMetadata:
    def test_three_tools_registered(self):
        assert len(agent_tools.TOOLS) == 3

    def test_tools_have_names_and_descriptions(self):
        for t in agent_tools.TOOLS:
            assert t.name
            assert t.description   # Claude reads these to choose a tool
