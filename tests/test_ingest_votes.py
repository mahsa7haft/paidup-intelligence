"""
Tests for ingest_votes.py — pure functions only (no live DB or API calls).
"""

import pytest
from app.ingest_votes import (
    _build_content,
    _clear_checkpoint,
    _load_checkpoint,
    _save_checkpoint,
    _vote_label,
)


# ── _vote_label ────────────────────────────────────────────────────────────────

class TestVoteLabel:
    def test_aye(self):
        assert _vote_label({"inAffirmativeLobby": True}) == "Aye"

    def test_no(self):
        assert _vote_label({"inNegativeLobby": True}) == "No"

    def test_teller(self):
        assert _vote_label({"actedAsTeller": True}) == "Teller"

    def test_abstain_when_no_flags_set(self):
        assert _vote_label({}) == "Abstain"

    def test_abstain_when_all_flags_false(self):
        assert _vote_label({
            "inAffirmativeLobby": False,
            "inNegativeLobby":    False,
            "actedAsTeller":      False,
        }) == "Abstain"

    def test_aye_checked_before_no(self):
        # Aye takes priority if multiple flags somehow set
        assert _vote_label({"inAffirmativeLobby": True, "inNegativeLobby": True}) == "Aye"

    def test_no_checked_before_teller(self):
        assert _vote_label({"inNegativeLobby": True, "actedAsTeller": True}) == "No"


# ── _build_content ─────────────────────────────────────────────────────────────

class TestBuildContent:
    def _vote(self, **overrides):
        base = {
            "inAffirmativeLobby": True,
            "inNegativeLobby":    False,
            "actedAsTeller":      False,
            "date":               "2024-03-15T12:00:00",
            "title":              "Finance Bill 2024",
            "divisionNumber":     42,
        }
        base.update(overrides)
        return base

    def test_standard_sentence(self):
        assert _build_content("Keir Starmer", "Labour", self._vote()) == (
            "MP Keir Starmer (Labour) voted Aye on 'Finance Bill 2024' "
            "on 2024-03-15 (division 42)."
        )

    def test_no_vote(self):
        content = _build_content("A B", "P", self._vote(
            inAffirmativeLobby=False, inNegativeLobby=True
        ))
        assert "voted No" in content

    def test_abstain_vote(self):
        content = _build_content("A B", "P", self._vote(inAffirmativeLobby=False))
        assert "voted Abstain" in content

    def test_teller_vote(self):
        content = _build_content("A B", "P", self._vote(
            inAffirmativeLobby=False, actedAsTeller=True
        ))
        assert "voted Teller" in content

    def test_date_truncated_to_10_chars(self):
        content = _build_content("A B", "P", self._vote(date="2024-06-01T23:59:59"))
        assert "on 2024-06-01" in content

    def test_missing_title_uses_fallback(self):
        vote = self._vote()
        del vote["title"]
        assert "an untitled division" in _build_content("A B", "P", vote)

    def test_missing_division_number_uses_question_mark(self):
        vote = self._vote()
        del vote["divisionNumber"]
        assert "division ?" in _build_content("A B", "P", vote)


# ── checkpoint ─────────────────────────────────────────────────────────────────

class TestCheckpoint:
    def test_load_returns_zero_when_no_file(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        assert _load_checkpoint() == 0

    def test_save_and_load_roundtrip(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        _save_checkpoint(450)
        assert _load_checkpoint() == 450

    def test_clear_removes_file(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        _save_checkpoint(100)
        _clear_checkpoint()
        assert _load_checkpoint() == 0

    def test_clear_when_no_file_is_safe(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        _clear_checkpoint()

    def test_corrupted_file_returns_zero(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        (tmp_path / ".ingest_votes_checkpoint.json").write_text("bad")
        assert _load_checkpoint() == 0

    def test_overwrite_advances_checkpoint(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        _save_checkpoint(100)
        _save_checkpoint(200)
        assert _load_checkpoint() == 200
