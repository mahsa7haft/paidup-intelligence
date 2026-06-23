"""
Tests for skills/conflict-of-interest-report/scripts/align_timeline.py
"""

import pytest
from skills.conflict_of_interest_report.scripts.align_timeline import align, summarise, WINDOW_DAYS


def _donation(date: str, source: str = "interests", amount: float = 5000.0, donor: str = "Acme Corp") -> dict:
    return {"date": date, "amount": amount, "donor": donor, "party": "Labour", "source": source}


def _vote(date: str, title: str = "Finance Bill", vote: str = "Aye") -> dict:
    return {"date": date, "division_title": title, "vote": vote}


# ── Bucketing ──────────────────────────────────────────────────────────────────

class TestBucketing:
    def test_donation_before_window_goes_to_before_window(self):
        donations = [_donation("2023-01-01")]
        votes     = [_vote("2024-01-01")]
        result = align(donations, votes)
        assert len(result[0]["before_window"]) == 1
        assert len(result[0]["in_window"]) == 0
        assert len(result[0]["after"]) == 0

    def test_donation_in_window_goes_to_in_window(self):
        donations = [_donation("2023-12-01")]
        votes     = [_vote("2024-01-01")]
        result = align(donations, votes)
        assert len(result[0]["in_window"]) == 1
        assert len(result[0]["before_window"]) == 0

    def test_donation_after_vote_goes_to_after(self):
        donations = [_donation("2024-06-01")]
        votes     = [_vote("2024-01-01")]
        result = align(donations, votes)
        assert len(result[0]["after"]) == 1
        assert len(result[0]["in_window"]) == 0
        assert len(result[0]["before_window"]) == 0

    def test_donation_on_vote_date_goes_to_in_window(self):
        donations = [_donation("2024-01-01")]
        votes     = [_vote("2024-01-01")]
        result = align(donations, votes)
        assert len(result[0]["in_window"]) == 1

    def test_donation_exactly_at_window_boundary_goes_to_in_window(self):
        donations = [_donation("2023-10-03")]  # exactly 90 days before 2024-01-01
        votes     = [_vote("2024-01-01")]
        result = align(donations, votes)
        assert len(result[0]["in_window"]) == 1

    def test_donation_one_day_outside_window_goes_to_before_window(self):
        donations = [_donation("2023-10-02")]  # 91 days before
        votes     = [_vote("2024-01-01")]
        result = align(donations, votes)
        assert len(result[0]["before_window"]) == 1


# ── Scoring ────────────────────────────────────────────────────────────────────

class TestScoring:
    def test_personal_in_window_is_strong(self):
        donations = [_donation("2023-12-01", source="interests")]
        votes     = [_vote("2024-01-01")]
        assert align(donations, votes)[0]["strength"] == "strong"

    def test_party_in_window_is_moderate(self):
        donations = [_donation("2023-12-01", source="party_donations")]
        votes     = [_vote("2024-01-01")]
        assert align(donations, votes)[0]["strength"] == "moderate"

    def test_personal_historic_is_moderate(self):
        donations = [_donation("2022-01-01", source="interests")]
        votes     = [_vote("2024-01-01")]
        assert align(donations, votes)[0]["strength"] == "moderate"

    def test_party_historic_is_weak(self):
        donations = [_donation("2022-01-01", source="party_donations")]
        votes     = [_vote("2024-01-01")]
        assert align(donations, votes)[0]["strength"] == "weak"

    def test_no_predating_donations_is_none(self):
        donations = [_donation("2024-06-01")]  # after vote
        votes     = [_vote("2024-01-01")]
        assert align(donations, votes)[0]["strength"] == "none"

    def test_no_donations_is_none(self):
        assert align([], [_vote("2024-01-01")])[0]["strength"] == "none"

    def test_personal_beats_party_in_window(self):
        donations = [
            _donation("2023-12-01", source="interests"),
            _donation("2023-12-01", source="party_donations"),
        ]
        votes = [_vote("2024-01-01")]
        assert align(donations, votes)[0]["strength"] == "strong"


# ── Sorting ────────────────────────────────────────────────────────────────────

class TestSorting:
    def test_results_sorted_strongest_first(self):
        donations = [
            _donation("2022-01-01", source="party_donations"),   # weak
            _donation("2023-12-01", source="interests"),          # strong for second vote
        ]
        votes = [
            _vote("2024-01-01", title="Bill A"),
            _vote("2024-01-15", title="Bill B"),
        ]
        results = align(donations, votes)
        order = ["strong", "moderate", "weak", "none"]
        for i in range(len(results) - 1):
            assert order.index(results[i]["strength"]) <= order.index(results[i + 1]["strength"])


# ── Edge cases ─────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_empty_donations_and_votes(self):
        assert align([], []) == []

    def test_multiple_votes_bucketed_independently(self):
        donations = [_donation("2024-01-10", source="interests")]
        votes = [
            _vote("2024-01-15", title="Bill A"),  # donation is in_window
            _vote("2023-12-01", title="Bill B"),  # donation is after
        ]
        results = align(donations, votes)
        bill_a = next(r for r in results if r["division_title"] == "Bill A")
        bill_b = next(r for r in results if r["division_title"] == "Bill B")
        assert bill_a["strength"] == "strong"
        assert bill_b["strength"] == "none"


# ── Summarise ──────────────────────────────────────────────────────────────────

class TestSummarise:
    def test_no_conflicts_returns_no_donations_message(self):
        result = summarise(align([], [_vote("2024-01-01")]))
        assert "No pre-vote donations" in result

    def test_strong_conflict_appears_in_summary(self):
        donations = [_donation("2023-12-01", source="interests")]
        votes     = [_vote("2024-01-01", title="Finance Bill")]
        result = summarise(align(donations, votes))
        assert "STRONG" in result
        assert "Finance Bill" in result

    def test_none_strength_excluded_from_summary(self):
        donations = [_donation("2024-06-01")]  # postdates vote
        votes     = [_vote("2024-01-01", title="Finance Bill")]
        result = summarise(align(donations, votes))
        assert "Finance Bill" not in result
