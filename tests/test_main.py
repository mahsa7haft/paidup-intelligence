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


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Clear per-IP hit counts before each test so limits don't bleed across tests."""
    main._hits.clear()
    yield
    main._hits.clear()


@pytest.fixture(autouse=True)
def isolate_cache():
    """Never touch the real Redis in tests — every lookup misses, every store no-ops."""
    with patch("app.main.cache.lookup", return_value=(None, None)), \
         patch("app.main.cache.store"):
        yield


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


class TestRateLimit:
    def _ask(self, client, ip):
        return client.post("/ask", json={"question": "q"}, headers={"X-Forwarded-For": ip})

    def test_blocks_after_limit(self, client, monkeypatch):
        monkeypatch.setattr(main, "RATE_LIMIT_PER_HOUR", 2)
        with patch("app.main.get_agent", return_value=_mock_agent()):
            assert self._ask(client, "1.1.1.1").status_code == 200
            assert self._ask(client, "1.1.1.1").status_code == 200
            blocked = self._ask(client, "1.1.1.1")
        assert blocked.status_code == 429
        assert "Rate limit" in blocked.get_json()["error"]

    def test_different_ips_independent(self, client, monkeypatch):
        monkeypatch.setattr(main, "RATE_LIMIT_PER_HOUR", 1)
        with patch("app.main.get_agent", return_value=_mock_agent()):
            assert self._ask(client, "1.1.1.1").status_code == 200
            assert self._ask(client, "1.1.1.1").status_code == 429   # same IP, over limit
            assert self._ask(client, "2.2.2.2").status_code == 200   # different IP, fine

    def test_disabled_when_zero(self, client, monkeypatch):
        monkeypatch.setattr(main, "RATE_LIMIT_PER_HOUR", 0)
        with patch("app.main.get_agent", return_value=_mock_agent()):
            for _ in range(5):
                assert self._ask(client, "9.9.9.9").status_code == 200
