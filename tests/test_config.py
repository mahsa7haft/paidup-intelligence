"""
Tests for config.py — sanity checks on shared constants.
"""

from app.config import EC_API, EMBED_BATCH, EMBED_MODEL, FETCH_ROWS, INTERESTS_API, MEMBERS_API


class TestConfig:
    def test_embed_model_is_non_empty_string(self):
        assert isinstance(EMBED_MODEL, str) and EMBED_MODEL

    def test_embed_batch_is_positive_int(self):
        assert isinstance(EMBED_BATCH, int)
        assert EMBED_BATCH > 0

    def test_fetch_rows_is_50(self):
        # EC API hard cap — if this changes it means the EC changed their API
        assert FETCH_ROWS == 50

    def test_all_api_urls_use_https(self):
        for name, url in [("MEMBERS_API", MEMBERS_API), ("INTERESTS_API", INTERESTS_API), ("EC_API", EC_API)]:
            assert url.startswith("https://"), f"{name} must use HTTPS, got: {url}"

    def test_all_api_urls_are_non_empty(self):
        for url in [MEMBERS_API, INTERESTS_API, EC_API]:
            assert isinstance(url, str) and url
