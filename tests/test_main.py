"""
Tests for main.py Flask routes — the agent is mocked, so no API key or DB is needed.
"""

from unittest.mock import MagicMock, patch

import pytest

from app import main


@pytest.fixture
def client():
    main.app.config.update(TESTING=True)
    return main.app.test_client()


def _mock_agent(answer="the answer"):
    """Agent whose invoke returns a final message with `answer` content."""
    msg = MagicMock()
    msg.content = answer
    agent = MagicMock()
    agent.invoke.return_value = {"messages": [msg]}
    return agent


class TestHealth:
    def test_health_ok(self, client):
        res = client.get("/health")
        assert res.status_code == 200
        assert res.get_json() == {"status": "ok"}


class TestIndex:
    def test_serves_page(self, client):
        res = client.get("/")
        assert res.status_code == 200
        assert b"Paid" in res.data  # the PaidUp wordmark


class TestAsk:
    def test_missing_question_returns_400(self, client):
        res = client.post("/ask", json={})
        assert res.status_code == 400
        assert "error" in res.get_json()

    def test_blank_question_returns_400(self, client):
        res = client.post("/ask", json={"question": "   "})
        assert res.status_code == 400

    def test_returns_answer_and_thread_id(self, client):
        with patch("app.main.get_agent", return_value=_mock_agent("Funded by X")):
            res = client.post("/ask", json={"question": "who funds X?"})
        body = res.get_json()
        assert res.status_code == 200
        assert body["answer"] == "Funded by X"
        assert body["thread_id"]  # a thread_id is generated when none is given

    def test_reuses_supplied_thread_id(self, client):
        with patch("app.main.get_agent", return_value=_mock_agent()):
            res = client.post("/ask", json={"question": "follow up", "thread_id": "abc-123"})
        assert res.get_json()["thread_id"] == "abc-123"

    def test_thread_id_passed_to_agent_config(self, client):
        agent = _mock_agent()
        with patch("app.main.get_agent", return_value=agent):
            client.post("/ask", json={"question": "q", "thread_id": "t-9"})
        config = agent.invoke.call_args.kwargs["config"]
        assert config["configurable"]["thread_id"] == "t-9"

    def test_agent_error_returns_500(self, client):
        agent = MagicMock()
        agent.invoke.side_effect = RuntimeError("boom")
        with patch("app.main.get_agent", return_value=agent):
            res = client.post("/ask", json={"question": "q"})
        assert res.status_code == 500
        assert "error" in res.get_json()
