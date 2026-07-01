"""
Tests for ingest_common.py — pure functions only (no live DB or API calls).

Checkpoint and sha256 were previously duplicated per ingestion script and
tested per script; they now live here and are tested once.
"""

import pytest
from app.ingest_common import (
    Checkpoint,
    PreparedRecord,
    company_and_tags,
    normalize_db_url,
    sha256,
)
from app.ingest_appgs import AppgIngestion
from app.ingest_interests import InterestsIngestion
from app.ingest_votes import VotesIngestion


# ── sha256 ─────────────────────────────────────────────────────────────────────

class TestSha256:
    def test_deterministic(self):
        assert sha256("hello") == sha256("hello")

    def test_different_inputs_differ(self):
        assert sha256("abc") != sha256("xyz")

    def test_returns_64_char_hex(self):
        result = sha256("test")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)


# ── normalize_db_url ───────────────────────────────────────────────────────────

class TestNormalizeDbUrl:
    def test_rewrites_postgres_scheme(self):
        assert normalize_db_url("postgres://u:p@h/db") == "postgresql://u:p@h/db"

    def test_leaves_postgresql_scheme_alone(self):
        assert normalize_db_url("postgresql://u:p@h/db") == "postgresql://u:p@h/db"

    def test_empty_string(self):
        assert normalize_db_url("") == ""


# ── Checkpoint ─────────────────────────────────────────────────────────────────

class TestCheckpoint:
    def _cp(self, tmp_path, field="mp_index"):
        return Checkpoint(str(tmp_path / ".checkpoint.json"), field)

    def test_load_returns_zero_when_no_file(self, tmp_path):
        assert self._cp(tmp_path).load() == 0

    def test_save_and_load_roundtrip(self, tmp_path):
        cp = self._cp(tmp_path)
        cp.save(312)
        assert cp.load() == 312

    def test_clear_removes_file(self, tmp_path):
        cp = self._cp(tmp_path)
        cp.save(100)
        cp.clear()
        assert cp.load() == 0

    def test_clear_when_no_file_is_safe(self, tmp_path):
        self._cp(tmp_path).clear()

    def test_corrupted_file_returns_zero(self, tmp_path):
        cp = self._cp(tmp_path)
        (tmp_path / ".checkpoint.json").write_text("{bad json")
        assert cp.load() == 0

    def test_overwrite_advances_checkpoint(self, tmp_path):
        cp = self._cp(tmp_path)
        cp.save(100)
        cp.save(200)
        assert cp.load() == 200

    def test_field_name_is_respected(self, tmp_path):
        cp = self._cp(tmp_path, field="start")
        cp.save(29200)
        assert '"start"' in (tmp_path / ".checkpoint.json").read_text()
        assert cp.load() == 29200

    def test_different_field_reads_as_zero(self, tmp_path):
        self._cp(tmp_path, field="start").save(50)
        assert self._cp(tmp_path, field="mp_index").load() == 0


# ── company_and_tags ───────────────────────────────────────────────────────────

class TestCompanyAndTags:
    def test_no_enrichment(self):
        result = company_and_tags("Acme Corp", {}, [])
        assert result == {"company_name": None, "logo_domain": None, "tags": []}

    def test_company_matched_via_lowercase_key(self):
        company_map = {"acme corp": {"company_name": "Acme", "logo_domain": "acme.com"}}
        result = company_and_tags("Acme Corp", company_map, [])
        assert result["company_name"] == "Acme"
        assert result["logo_domain"] == "acme.com"

    def test_tag_pattern_matches_substring(self):
        tag_rules = [{"pattern": "acme", "tag": "corporate", "label": "Corporate"}]
        result = company_and_tags("Acme Corp", {}, tag_rules)
        assert result["tags"] == [{"tag": "corporate", "label": "Corporate"}]

    def test_tag_no_match(self):
        tag_rules = [{"pattern": "fossil", "tag": "fossil_fuel", "label": "Fossil Fuel"}]
        assert company_and_tags("Acme Corp", {}, tag_rules)["tags"] == []


# ── pipeline source_id hooks ───────────────────────────────────────────────────

class TestSourceIds:
    def test_interests_uses_register_id(self):
        interest = {"id": "abc-123", "summary": "s", "date": "2024-01-01"}
        assert InterestsIngestion().source_id(42, interest) == "interests_42_abc-123"

    def test_interests_falls_back_to_hash_when_no_id(self):
        interest = {"id": "", "summary": "s", "date": "2024-01-01"}
        sid = InterestsIngestion().source_id(42, interest)
        assert sid == f"interests_42_{sha256('s2024-01-01')[:12]}"

    def test_votes_uses_division_id(self):
        assert VotesIngestion().source_id(42, {"id": 1809}) == "vote_42_1809"

    def test_appgs_hashes_name_and_role(self):
        role = {"appg_name": "APPG on Music", "role": "Chair"}
        sid = AppgIngestion().source_id(42, role)
        assert sid == f"appg_42_{sha256('APPG on MusicChair')[:12]}"


# ── PreparedRecord ─────────────────────────────────────────────────────────────

class TestPreparedRecord:
    def test_fields(self):
        p = PreparedRecord(source_id="s", content="c", content_hash="h", record={"a": 1})
        assert (p.source_id, p.content, p.content_hash, p.record) == ("s", "c", "h", {"a": 1})
