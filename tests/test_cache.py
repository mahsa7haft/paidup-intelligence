"""
Tests for cache.py — Redis is mocked, so these run without a running Redis.
"""

from unittest.mock import MagicMock, patch

import pytest

from app import cache


@pytest.fixture(autouse=True)
def reset_state():
    cache._redis = None
    yield
    cache._redis = None


class TestNormalisation:
    def test_collapses_whitespace_and_lowercases(self):
        assert cache._normalise("  Who   Funds  X? ") == "who funds x?"

    def test_key_is_stable_across_formatting(self):
        assert cache._key("A  b") == cache._key("a b")

    def test_different_questions_get_different_keys(self):
        assert cache._key("who funds Labour?") != cache._key("who funds the Tories?")


class TestLookup:
    def test_exact_hit_returns_l1(self):
        r = MagicMock()
        r.get.return_value = "cached answer"
        with patch("app.cache._get_redis", return_value=r):
            assert cache.lookup("who funds X?") == ("cached answer", "L1")

    def test_miss_returns_none(self):
        r = MagicMock()
        r.get.return_value = None
        with patch("app.cache._get_redis", return_value=r):
            assert cache.lookup("never asked") == (None, None)

    def test_no_redis_returns_none(self):
        with patch("app.cache._get_redis", return_value=None):
            assert cache.lookup("q") == (None, None)

    def test_lookup_never_raises(self):
        with patch("app.cache._get_redis", side_effect=Exception("redis boom")):
            assert cache.lookup("q") == (None, None)


class TestStore:
    def test_writes_with_ttl(self):
        r = MagicMock()
        with patch("app.cache._get_redis", return_value=r):
            cache.store("who funds X?", "the answer")
        args = r.setex.call_args[0]
        assert args[1] == cache.TTL_SECONDS
        assert args[2] == "the answer"

    def test_no_redis_is_noop(self):
        with patch("app.cache._get_redis", return_value=None):
            cache.store("q", "a")   # must not raise

    def test_store_never_raises(self):
        with patch("app.cache._get_redis", side_effect=Exception("boom")):
            cache.store("q", "a")   # must not raise
