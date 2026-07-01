"""
Ingest Parliament Register of Members' Financial Interests into interests_vectors.

Usage:
    PYTHONPATH=src uv run python -m app.ingest_interests

Fetches all current Commons MPs, embeds each declared interest, and upserts
into interests_vectors. Only calls the OpenAI API for records whose content has
changed since the last run (hash check).

Note: DATABASE_URL on Railway uses the internal hostname (postgres.railway.internal).
Run this script from within Railway (cron job) or swap to the public URL for local runs.
"""

import requests

from app.config import INTERESTS_API
from app.ingest_common import (
    Checkpoint, MPIngestionPipeline, company_and_tags, load_enrichment, sha256,
)


def _get_interests(member_id: int) -> list[dict]:
    r = requests.get(f"{INTERESTS_API}/Interests", params={"MemberId": member_id}, timeout=10)
    r.raise_for_status()
    return r.json().get("items", [])


def _parse_interests(raw: list[dict]) -> list[dict]:
    parsed = []
    for item in raw:
        fields   = {f["name"]: f["value"] for f in item.get("fields", [])}
        donor    = (fields.get("DonorName")
                    or fields.get("DonorCompanyName")
                    or fields.get("UltimatePayerName")
                    or fields.get("PayerName")
                    or "Unknown")
        value    = fields.get("Value") or fields.get("AmountOfDonation")
        category = item.get("category", {}).get("name", "Other")
        date     = (item.get("registrationDate") or "")[:10]
        parsed.append({
            "id":       item.get("id", ""),
            "donor":    donor,
            "value":    float(value) if value else 0.0,
            "category": category,
            "date":     date,
            "summary":  item.get("summary", ""),
            "raw":      {k: v for k, v in fields.items() if v},
        })
    return parsed


def _build_content(name: str, party: str, interest: dict) -> str:
    amount = f"£{interest['value']:,.0f}" if interest["value"] else "an unspecified amount"
    date   = interest["date"] or "unknown date"
    return (
        f"MP {name} ({party}) received {amount} from {interest['donor']} "
        f"as a {interest['category']}, registered {date}."
    )


def _build_metadata(interest: dict, company_map: dict, tag_rules: list) -> dict:
    return {
        "donor":   interest["donor"],
        "value":   interest["value"],
        "date":    interest["date"],
        "summary": interest["summary"],
        **company_and_tags(interest["donor"], company_map, tag_rules),
        "raw":     interest["raw"],
    }


class InterestsIngestion(MPIngestionPipeline):
    script_name   = "ingest_interests"
    checkpoint    = Checkpoint(".ingest_interests_checkpoint.json", "mp_index")
    table         = "interests_vectors"
    columns       = ["source_id", "mp_id", "mp_name", "category",
                     "content", "metadata", "embedding", "content_hash"]
    empty_status  = "no-interests"
    sleep_seconds = 0.5

    def setup(self) -> None:
        self.company_map, self.tag_rules = load_enrichment()

    def fetch_records(self, mp: dict) -> list[dict]:
        return _parse_interests(_get_interests(mp["id"]))

    def build_content(self, name: str, party: str, interest: dict) -> str:
        return _build_content(name, party, interest)

    def source_id(self, member_id: int, interest: dict) -> str:
        if interest["id"]:
            return f"interests_{member_id}_{interest['id']}"
        return f"interests_{member_id}_{sha256(interest['summary'] + interest['date'])[:12]}"

    def metadata(self, interest: dict) -> dict:
        return _build_metadata(interest, self.company_map, self.tag_rules)

    def row_extras(self, interest: dict) -> dict:
        return {"category": interest["category"]}


def main() -> None:
    InterestsIngestion().run()


if __name__ == "__main__":
    main()
