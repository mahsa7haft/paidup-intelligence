"""
Ingest MP voting records (divisions) into votes_vectors.

Usage:
    PYTHONPATH=src uv run python -m app.ingest_votes

Fetches every division vote for all current Commons MPs via the Parliament
Members API. ~500,000 records expected. Only re-embeds changed records.

Note: This script is slow on first run (~2-3 hours for 500k records due to
API pagination). Subsequent runs are fast — only new divisions are embedded.
"""

import time

import requests

from app.config import MEMBERS_API
from app.ingest_common import Checkpoint, MPIngestionPipeline


def _get_votes(member_id: int) -> list[dict]:
    """Fetch all division votes for one MP across all pages."""
    votes, page = [], 1
    while True:
        r = requests.get(
            f"{MEMBERS_API}/Members/{member_id}/Voting",
            params={"house": 1, "page": page},
            timeout=10,
        )
        if r.status_code == 404:
            break
        r.raise_for_status()
        data  = r.json()
        items = data.get("items", [])
        if not items:
            break
        votes.extend(v["value"] for v in items)
        if len(votes) >= data.get("totalResults", 0):
            break
        page += 1
        time.sleep(0.1)
    return votes


def _vote_label(vote: dict) -> str:
    if vote.get("inAffirmativeLobby"):
        return "Aye"
    if vote.get("inNegativeLobby"):
        return "No"
    if vote.get("actedAsTeller"):
        return "Teller"
    return "Abstain"


def _build_content(name: str, party: str, vote: dict) -> str:
    label = _vote_label(vote)
    date  = (vote.get("date") or "")[:10]
    title = vote.get("title", "an untitled division")
    return (
        f"MP {name} ({party}) voted {label} on '{title}' "
        f"on {date} (division {vote.get('divisionNumber', '?')})."
    )


class VotesIngestion(MPIngestionPipeline):
    script_name   = "ingest_votes"
    checkpoint    = Checkpoint(".ingest_votes_checkpoint.json", "mp_index")
    table         = "votes_vectors"
    columns       = ["source_id", "mp_id", "mp_name", "division_id", "vote", "vote_date",
                     "content", "metadata", "embedding", "content_hash"]
    empty_status  = "no-votes"
    sleep_seconds = 0.3

    def fetch_records(self, mp: dict) -> list[dict]:
        return _get_votes(mp["id"])

    def build_content(self, name: str, party: str, vote: dict) -> str:
        return _build_content(name, party, vote)

    def source_id(self, member_id: int, vote: dict) -> str:
        return f"vote_{member_id}_{vote.get('id', '')}"

    def metadata(self, vote: dict) -> dict:
        return {
            "title":            vote.get("title"),
            "division_number":  vote.get("divisionNumber"),
            "number_in_favour": vote.get("numberInFavour"),
            "number_against":   vote.get("numberAgainst"),
        }

    def row_extras(self, vote: dict) -> dict:
        return {
            "division_id": str(vote.get("id", "")),
            "vote":        _vote_label(vote),
            "vote_date":   (vote.get("date") or "")[:10] or None,
        }


def main() -> None:
    VotesIngestion().run()


if __name__ == "__main__":
    main()
