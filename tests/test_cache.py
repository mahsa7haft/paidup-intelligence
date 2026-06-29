"""
Tests for cache.py — Redis, Postgres, and embeddings are mocked.
"""

from unittest.mock import MagicMock, patch

import pytest

from app import cache


@pytest.fixture(autouse=True)
def reset_state():
    cache._redis = None
    cache._table_ready = True   # skip the CREATE TABLE DDL in unit tests
    yield
    cache._redis = None
    cache._table_ready = False


def _mock_pg(fetchone_row):
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_row
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = lambda s: cur
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn, cur


class TestNormalisation:
    def test_collapses_whitespace_and_lowercases(self):
        assert cache._normalise("  Who   Funds  X? ") == "who funds x?"

    def test_key_is_stable_across_formatting(self):
        assert cache._l1_key("A  b") == cache._l1_key("a b")


class TestLookup:
    def test_l1_exact_hit(self):
        r = MagicMock()
        r.get.return_value = "cached answer"
        with patch("app.cache._get_redis", return_value=r):
            answer, layer = cache.lookup("who funds X?")
        assert (answer, layer) == ("cached answer", "L1")

    def test_l2_semantic_hit_when_above_threshold(self):
        conn, _ = _mock_pg(("semantic answer", 0.97))
        with patch("app.cache._get_redis", return_value=None), \
             patch("app.cache.embed_query", return_value=[0.1, 0.2]), \
             patch("app.cache._pg_connect", return_value=conn):
            answer, layer = cache.lookup("who funds X?")
        assert (answer, layer) == ("semantic answer", "L2")

    def test_l2_miss_when_below_threshold(self):
        conn, _ = _mock_pg(("too far", 0.80))   # below 0.95
        with patch("app.cache._get_redis", return_value=None), \
             patch("app.cache.embed_query", return_value=[0.1]), \
             patch("app.cache._pg_connect", return_value=conn):
            answer, layer = cache.lookup("unrelated")
        assert (answer, layer) == (None, None)

    def test_total_miss_returns_none(self):
        conn, _ = _mock_pg(None)
        with patch("app.cache._get_redis", return_value=None), \
             patch("app.cache.embed_query", return_value=[0.1]), \
             patch("app.cache._pg_connect", return_value=conn):
            assert cache.lookup("nothing") == (None, None)

    def test_lookup_never_raises_on_failure(self):
        # Redis throws, embedding throws — lookup must still return cleanly.
        with patch("app.cache._get_redis", side_effect=Exception("redis boom")), \
             patch("app.cache.embed_query", side_effect=Exception("embed boom")):
            assert cache.lookup("q") == (None, None)


class TestStore:
    def test_writes_to_l1_and_l2(self):
        r = MagicMock()
        conn, cur = _mock_pg(None)
        with patch("app.cache._get_redis", return_value=r), \
             patch("app.cache.embed_query", return_value=[0.1, 0.2]), \
             patch("app.cache._pg_connect", return_value=conn):
            cache.store("who funds X?", "the answer")
        r.setex.assert_called_once()            # L1 written with TTL
        assert cur.execute.call_args[0][0].strip().startswith("INSERT INTO query_cache")

    def test_store_never_raises_on_failure(self):
        with patch("app.cache._get_redis", return_value=None), \
             patch("app.cache.embed_query", side_effect=Exception("embed boom")):
            cache.store("q", "a")   # must not raise
