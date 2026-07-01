"""
Ingest MP APPG (All-Party Parliamentary Group) memberships into appg_vectors.

Usage:
    PYTHONPATH=src uv run python -m app.ingest_appgs

Requires THEYWORKFORYOU_API_KEY — free at https://www.theyworkforyou.com/api/key
Uses getMPInfo for each MP and extracts current APPG roles from the office array.
"""

import logging
import os

import requests

from app.ingest_common import Checkpoint, MPIngestionPipeline, sha256

TWFY_API = "https://www.theyworkforyou.com/api"

log = logging.getLogger(__name__)


def _get_appg_roles(name: str, key: str) -> list[dict]:
    """
    Look up an MP by name and return their current APPG memberships.
    Each role is a dict with 'appg_name' and 'role'.
    Returns [] on any failure.
    """
    try:
        r = requests.get(f"{TWFY_API}/getMP",
                         params={"name": name, "key": key, "output": "json"}, timeout=5)
        if r.status_code != 200:
            return []
        data = r.json()
        if isinstance(data, list):
            data = data[0] if data else {}
        person_id = data.get("person_id")
        if not person_id:
            return []

        r2 = requests.get(f"{TWFY_API}/getMPInfo",
                          params={"id": person_id, "key": key, "output": "json"}, timeout=5)
        if r2.status_code != 200:
            return []
        info = r2.json()

        roles = []
        for entry in info.get("office", []):
            org      = entry.get("org_name", "")
            position = entry.get("position", "")
            to_date  = entry.get("to_date", "")
            # Only current roles (far-future to_date = still active)
            if to_date and to_date < "2024-01-01":
                continue
            if "all-party" in org.lower() or "appg" in org.lower():
                roles.append({
                    "appg_name": org,
                    "role":      position or "Member",
                })
        return roles

    except Exception as exc:
        log.debug("TWFY lookup failed for %s: %s", name, exc)
        return []


def _build_content(name: str, party: str, role: dict) -> str:
    return (
        f"MP {name} ({party}) is a {role['role']} of the "
        f"All-Party Parliamentary Group on {role['appg_name']}."
    )


class AppgIngestion(MPIngestionPipeline):
    script_name   = "ingest_appgs"
    checkpoint    = Checkpoint(".ingest_appgs_checkpoint.json", "mp_index")
    table         = "appg_vectors"
    columns       = ["source_id", "mp_id", "mp_name", "appg_name", "role",
                     "content", "metadata", "embedding", "content_hash"]
    empty_status  = "no-appgs"
    sleep_seconds = 0.5  # TWFY rate limit is lenient but be polite

    def validate_env(self) -> None:
        self.twfy_key = os.environ.get("THEYWORKFORYOU_API_KEY", "")
        if not self.twfy_key:
            raise SystemExit(
                "THEYWORKFORYOU_API_KEY not set\n"
                "Get a free key at https://www.theyworkforyou.com/api/key"
            )

    def fetch_records(self, mp: dict) -> list[dict]:
        return _get_appg_roles(mp["nameDisplayAs"], self.twfy_key)

    def build_content(self, name: str, party: str, role: dict) -> str:
        return _build_content(name, party, role)

    def source_id(self, member_id: int, role: dict) -> str:
        return f"appg_{member_id}_{sha256(role['appg_name'] + role['role'])[:12]}"

    def metadata(self, role: dict) -> dict:
        return {}

    def row_extras(self, role: dict) -> dict:
        return {"appg_name": role["appg_name"], "role": role["role"]}


def main() -> None:
    AppgIngestion().run()


if __name__ == "__main__":
    main()
