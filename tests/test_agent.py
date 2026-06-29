"""
Tests for agent.py — the LLM is mocked, so the graph builds without an API key.
"""

from unittest.mock import MagicMock, patch

from app import agent


class TestBuildAgent:
    def test_graph_has_think_and_tools_nodes(self):
        with patch("app.agent.ChatAnthropic") as mock_llm:
            mock_llm.return_value.bind_tools.return_value = MagicMock()
            compiled = agent.build_agent()
        nodes = compiled.get_graph().nodes
        assert "think" in nodes
        assert "tools" in nodes

    def test_tools_are_bound_to_the_llm(self):
        with patch("app.agent.ChatAnthropic") as mock_llm:
            mock_llm.return_value.bind_tools.return_value = MagicMock()
            agent.build_agent()
        # the agent must bind exactly our three tools
        bound = mock_llm.return_value.bind_tools.call_args[0][0]
        assert len(bound) == 3
