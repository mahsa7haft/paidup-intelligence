"""
Tests for ingest_interests.py — pure functions only (no live DB or API calls).
"""

import pytest
from app.ingest_interests import (
    _build_content,
    _build_metadata,
    _parse_interests,
)


# ── _parse_interests ───────────────────────────────────────────────────────────

class TestParseInterests:
    def _item(self, fields: dict, **overrides):
        return {
            "id":               "abc-123",
            "category":         {"name": "Donations and gifts"},
            "registrationDate": "2024-03-15T00:00:00",
            "summary":          "Test summary",
            "fields":           [{"name": k, "value": v} for k, v in fields.items()],
            **overrides,
        }

    def test_standard_interest(self):
        raw = [self._item({"DonorName": "Acme Corp", "Value": "5000"})]
        result = _parse_interests(raw)
        assert len(result) == 1
        assert result[0]["donor"] == "Acme Corp"
        assert result[0]["value"] == 5000.0
        assert result[0]["category"] == "Donations and gifts"
        assert result[0]["date"] == "2024-03-15"

    def test_donor_name_fallback_to_company_name(self):
        raw = [self._item({"DonorCompanyName": "Fallback Corp", "Value": "1000"})]
        assert _parse_interests(raw)[0]["donor"] == "Fallback Corp"

    def test_donor_name_fallback_to_ultimate_payer(self):
        raw = [self._item({"UltimatePayerName": "Ultimate Ltd", "Value": "500"})]
        assert _parse_interests(raw)[0]["donor"] == "Ultimate Ltd"

    def test_donor_name_fallback_to_payer(self):
        raw = [self._item({"PayerName": "Payer Co", "Value": "250"})]
        assert _parse_interests(raw)[0]["donor"] == "Payer Co"

    def test_donor_name_unknown_when_all_missing(self):
        raw = [self._item({"Value": "100"})]
        assert _parse_interests(raw)[0]["donor"] == "Unknown"

    def test_zero_value_when_no_value_field(self):
        raw = [self._item({"DonorName": "Someone"})]
        assert _parse_interests(raw)[0]["value"] == 0.0

    def test_missing_category_defaults_to_other(self):
        item = self._item({"DonorName": "X"})
        item["category"] = {}
        assert _parse_interests([item])[0]["category"] == "Other"

    def test_date_truncated_to_10_chars(self):
        raw = [self._item({"DonorName": "X"}, registrationDate="2024-06-15T12:34:56")]
        assert _parse_interests(raw)[0]["date"] == "2024-06-15"

    def test_empty_list_returns_empty(self):
        assert _parse_interests([]) == []

    def test_multiple_items(self):
        raw = [
            self._item({"DonorName": "A", "Value": "1000"}),
            self._item({"DonorName": "B", "Value": "2000"}),
        ]
        assert len(_parse_interests(raw)) == 2

    def test_raw_field_filters_falsy_values(self):
        raw = [self._item({"DonorName": "X", "EmptyField": "", "NoneField": None})]
        result = _parse_interests(raw)
        assert "EmptyField" not in result[0]["raw"]
        assert "NoneField" not in result[0]["raw"]


# ── _build_content ─────────────────────────────────────────────────────────────

class TestBuildContent:
    def _interest(self, **overrides):
        base = {
            "donor":    "Acme Corp",
            "value":    5000.0,
            "category": "Donations and gifts",
            "date":     "2024-03-15",
        }
        base.update(overrides)
        return base

    def test_standard_sentence(self):
        assert _build_content("Keir Starmer", "Labour", self._interest()) == (
            "MP Keir Starmer (Labour) received £5,000 from Acme Corp "
            "as a Donations and gifts, registered 2024-03-15."
        )

    def test_zero_value_uses_unspecified(self):
        assert "an unspecified amount" in _build_content("A B", "P", self._interest(value=0))

    def test_empty_date_uses_unknown(self):
        assert "unknown date" in _build_content("A B", "P", self._interest(date=""))

    def test_large_amount_has_commas(self):
        content = _build_content("A B", "P", self._interest(value=1_000_000.0))
        assert "£1,000,000" in content


# ── _build_metadata ────────────────────────────────────────────────────────────

class TestBuildMetadata:
    def _interest(self, donor="Acme Corp"):
        return {
            "donor":   donor,
            "value":   5000.0,
            "date":    "2024-03-15",
            "summary": "Test summary",
            "raw":     {"DonorName": "Acme Corp"},
        }

    def test_no_enrichment(self):
        meta = _build_metadata(self._interest(), {}, [])
        assert meta["donor"] == "Acme Corp"
        assert meta["company_name"] is None
        assert meta["logo_domain"] is None
        assert meta["tags"] == []

    def test_company_enrichment_matched(self):
        company_map = {"acme corp": {"company_name": "Acme", "logo_domain": "acme.com"}}
        meta = _build_metadata(self._interest(), company_map, [])
        assert meta["company_name"] == "Acme"
        assert meta["logo_domain"] == "acme.com"

    def test_company_enrichment_case_insensitive(self):
        company_map = {"ACME CORP": {"company_name": "Acme", "logo_domain": "acme.com"}}
        # donor.lower() used for lookup — "ACME CORP" key won't match "acme corp"
        meta = _build_metadata(self._interest(), company_map, [])
        assert meta["company_name"] is None  # key must already be lowercase in map

    def test_tag_matching(self):
        tag_rules = [{"pattern": "acme", "tag": "corporate", "label": "Corporate"}]
        meta = _build_metadata(self._interest(), {}, tag_rules)
        assert meta["tags"][0]["tag"] == "corporate"

    def test_tag_no_match(self):
        tag_rules = [{"pattern": "fossil", "tag": "fossil_fuel", "label": "Fossil Fuel"}]
        assert _build_metadata(self._interest(), {}, tag_rules)["tags"] == []
