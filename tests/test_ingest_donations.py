"""
Tests for ingest_donations.py — pure functions only (no live DB or API calls).
"""

import pytest
from app.ingest_donations import (
    _build_content,
    _build_metadata,
    _parse_ms_date,
    _parse_record,
)


# ── _parse_ms_date ─────────────────────────────────────────────────────────────

class TestParseMsDate:
    def test_valid_timestamp(self):
        assert _parse_ms_date("/Date(1609459200000)/") == "2021-01-01"

    def test_none_returns_empty(self):
        assert _parse_ms_date(None) == ""

    def test_empty_string_returns_empty(self):
        assert _parse_ms_date("") == ""

    def test_malformed_string_returns_empty(self):
        assert _parse_ms_date("2024-01-01") == ""

    def test_epoch_zero(self):
        assert _parse_ms_date("/Date(0)/") == "1970-01-01"


# ── _parse_record ──────────────────────────────────────────────────────────────

class TestParseRecord:
    def _raw(self, **overrides):
        base = {
            "ECRef":                 "EC-123",
            "RegulatedEntityName":   "Labour Party",
            "DonorName":             "Unite the Union",
            "Value":                 "50000",
            "AcceptedDate":          "/Date(1609459200000)/",
            "DonationType":          "Cash",
            "NatureOfDonation":      "Political",
            "DonorStatus":           "Trade Union",
            "IsBequest":             False,
            "IsAggregation":         False,
            "IsIrishSource":         False,
            "AccountingUnitName":    "Central",
            "ReportingPeriodName":   "Q1 2021",
        }
        base.update(overrides)
        return base

    def test_valid_record_parses_correctly(self):
        result = _parse_record(self._raw())
        assert result is not None
        assert result["ec_ref"] == "EC-123"
        assert result["party"] == "Labour Party"
        assert result["donor"] == "Unite the Union"
        assert result["value"] == 50000.0
        assert result["date"] == "2021-01-01"

    def test_none_donor_name_returns_none(self):
        # Regression: key present but value is None (EC API returns null)
        assert _parse_record(self._raw(DonorName=None)) is None

    def test_empty_donor_name_returns_none(self):
        assert _parse_record(self._raw(DonorName="")) is None

    def test_none_ec_ref_returns_none(self):
        assert _parse_record(self._raw(ECRef=None)) is None

    def test_none_party_returns_none(self):
        assert _parse_record(self._raw(RegulatedEntityName=None)) is None

    def test_null_value_defaults_to_zero(self):
        result = _parse_record(self._raw(Value=None))
        assert result is not None
        assert result["value"] == 0.0

    def test_boolean_fields_parsed(self):
        result = _parse_record(self._raw(IsBequest=True, IsIrishSource=True))
        assert result["is_bequest"] is True
        assert result["is_irish"] is True

    def test_optional_fields_default_to_empty_string(self):
        result = _parse_record(self._raw(DonationType=None, NatureOfDonation=None))
        assert result["dtype"] == ""
        assert result["nature"] == ""


# ── _build_content ─────────────────────────────────────────────────────────────

class TestBuildContent:
    def _record(self, **overrides):
        base = {
            "party": "Conservative Party",
            "donor": "Some Corp Ltd",
            "value": 10000.0,
            "date":  "2024-01-15",
            "dtype": "Cash",
        }
        base.update(overrides)
        return base

    def test_standard_sentence(self):
        assert _build_content(self._record()) == (
            "The Conservative Party received £10,000 from Some Corp Ltd "
            "as a Cash on 2024-01-15."
        )

    def test_zero_value_uses_unspecified(self):
        assert "an unspecified amount" in _build_content(self._record(value=0))

    def test_empty_date_uses_unknown(self):
        assert "unknown date" in _build_content(self._record(date=""))

    def test_empty_dtype_uses_donation(self):
        assert "as a donation" in _build_content(self._record(dtype=""))

    def test_large_amount_has_commas(self):
        assert "£1,234,567" in _build_content(self._record(value=1_234_567.0))


# ── _build_metadata ────────────────────────────────────────────────────────────

class TestBuildMetadata:
    def _record(self, donor="Unite the Union"):
        return {
            "donor":        donor,
            "ec_ref":       "EC-123",
            "dtype":        "Cash",
            "nature":       "Political",
            "donor_status": "Trade Union",
            "is_bequest":   False,
            "is_agg":       False,
            "is_irish":     False,
            "account_unit": "Central",
            "period":       "Q1 2021",
        }

    def test_no_enrichment(self):
        meta = _build_metadata(self._record(), {}, [])
        assert meta["ec_ref"] == "EC-123"
        assert meta["company_name"] is None
        assert meta["logo_domain"] is None
        assert meta["tags"] == []

    def test_company_enrichment_matched_case_insensitively(self):
        company_map = {"unite the union": {"company_name": "Unite", "logo_domain": "unite.org"}}
        meta = _build_metadata(self._record(), company_map, [])
        assert meta["company_name"] == "Unite"
        assert meta["logo_domain"] == "unite.org"

    def test_company_enrichment_no_match(self):
        company_map = {"some other org": {"company_name": "Other", "logo_domain": "other.org"}}
        meta = _build_metadata(self._record(), company_map, [])
        assert meta["company_name"] is None

    def test_tag_rule_matches(self):
        tag_rules = [{"pattern": "unite", "tag": "union", "label": "Trade Union"}]
        meta = _build_metadata(self._record(), {}, tag_rules)
        assert len(meta["tags"]) == 1
        assert meta["tags"][0]["tag"] == "union"

    def test_tag_rule_no_match(self):
        tag_rules = [{"pattern": "fossil", "tag": "fossil_fuel", "label": "Fossil Fuel"}]
        meta = _build_metadata(self._record(), {}, tag_rules)
        assert meta["tags"] == []

    def test_multiple_tags_matched(self):
        tag_rules = [
            {"pattern": "unite", "tag": "union", "label": "Trade Union"},
            {"pattern": "the",   "tag": "common", "label": "Common Word"},
        ]
        meta = _build_metadata(self._record(), {}, tag_rules)
        assert len(meta["tags"]) == 2
