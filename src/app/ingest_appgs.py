"""
Ingest MP APPG (All-Party Parliamentary Group) memberships into appg_vectors.

Usage:
    PYTHONPATH=src uv run python -m app.ingest_appgs

Requires THEYWORKFORYOU_API_KEY — free at https://www.theyworkforyou.com/api/key
Uses getMPInfo for each MP and extracts current APPG roles from the office array.
"""

import hashlib
import json
import logging
import os
import time

import psycopg2
import psycopg2.extras
import requests
from dotenv import load_dotenv
from openai import OpenAI
from pgvector.psycopg2 import register_vector

load_dotenv()

MEMBERS_API  = "https://members-api.parliament.uk/api"
TWFY_API     = "https://www.theyworkforyou.com/api"
EMBED_MODEL  = "text-embedding-3-small"
EMBED_BATCH  = 100

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ── Parliament API ─────────────────────────────────────────────────────────────

def _all_mps() -> list[dict]:
    mps, skip = [], 0
    while True:
        r = requests.get(
            f"{MEMBERS_API}/Members/Search",
            params={"House": 1, "IsCurrentMember": "true", "take": 100, "skip": skip},
            timeout=10,
        )
        r.raise_for_status()
        data  = r.json()
        items = data.get("items", [])
        if not items:
            break
        mps.extend(m["value"] for m in items)
        skip += 100
        if skip >= data.get("totalResults", 0):
            break
    return mps


# ── TheyWorkForYou API ─────────────────────────────────────────────────────────

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


# ── Content + hash ─────────────────────────────────────────────────────────────

def _build_content(name: str, party: str, role: dict) -> str:
    return (
        f"MP {name} ({party}) is a {role['role']} of the "
        f"All-Party Parliamentary Group on {role['appg_name']}."
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ── Database ───────────────────────────────────────────────────────────────────

def _fetch_existing_hashes(cur, mp_id: int) -> dict[str, str]:
    cur.execute(
        "SELECT source_id, content_hash FROM appg_vectors WHERE mp_id = %s",
        (mp_id,),
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def _upsert(cur, rows: list[dict]) -> None:
    psycopg2.extras.execute_batch(
        cur,
        """
        INSERT INTO appg_vectors
            (source_id, mp_id, mp_name, appg_name, role,
             content, metadata, embedding, content_hash)
        VALUES
            (%(source_id)s, %(mp_id)s, %(mp_name)s, %(appg_name)s, %(role)s,
             %(content)s, %(metadata)s, %(embedding)s, %(content_hash)s)
        ON CONFLICT (source_id) DO UPDATE SET
            mp_name      = EXCLUDED.mp_name,
            appg_name    = EXCLUDED.appg_name,
            role         = EXCLUDED.role,
            content      = EXCLUDED.content,
            metadata     = EXCLUDED.metadata,
            embedding    = EXCLUDED.embedding,
            content_hash = EXCLUDED.content_hash
        """,
        rows,
    )


# ── Embeddings ─────────────────────────────────────────────────────────────────

def _embed_batch(client: OpenAI, texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]


# ── Per-MP ingestion ───────────────────────────────────────────────────────────

def _ingest_mp(conn, client: OpenAI, mp: dict, twfy_key: str) -> dict:
    member_id = mp["id"]
    name      = mp["nameDisplayAs"]
    party     = mp["latestParty"]["name"]

    roles = _get_appg_roles(name, twfy_key)
    if not roles:
        return {"status": "no-appgs"}

    with conn.cursor() as cur:
        existing = _fetch_existing_hashes(cur, member_id)

    to_embed = []
    for role in roles:
        source_id    = f"appg_{member_id}_{_sha256(role['appg_name'] + role['role'])[:12]}"
        content      = _build_content(name, party, role)
        content_hash = _sha256(content)
        role["_source_id"]    = source_id
        role["_content"]      = content
        role["_content_hash"] = content_hash
        if existing.get(source_id) != content_hash:
            to_embed.append(role)

    if not to_embed:
        return {"status": "skip", "count": len(roles)}

    embeddings = []
    for i in range(0, len(to_embed), EMBED_BATCH):
        batch = to_embed[i : i + EMBED_BATCH]
        embeddings.extend(_embed_batch(client, [r["_content"] for r in batch]))

    rows = []
    for role, embedding in zip(to_embed, embeddings):
        rows.append({
            "source_id":    role["_source_id"],
            "mp_id":        member_id,
            "mp_name":      name,
            "appg_name":    role["appg_name"],
            "role":         role["role"],
            "content":      role["_content"],
            "metadata":     json.dumps({}),
            "embedding":    embedding,
            "content_hash": role["_content_hash"],
        })

    with conn.cursor() as cur:
        _upsert(cur, rows)
    conn.commit()

    return {"status": "embedded", "embedded": len(rows), "skipped": len(roles) - len(to_embed)}


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    db_url   = os.environ.get("DATABASE_URL", "")
    twfy_key = os.environ.get("THEYWORKFORYOU_API_KEY", "")
    if not db_url:
        raise SystemExit("DATABASE_URL not set")
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY not set")
    if not twfy_key:
        raise SystemExit(
            "THEYWORKFORYOU_API_KEY not set\n"
            "Get a free key at https://www.theyworkforyou.com/api/key"
        )

    db_url = db_url.replace("postgres://", "postgresql://", 1)
    conn   = psycopg2.connect(db_url)
    register_vector(conn)
    client = OpenAI()

    log.info("Fetching MP list…")
    mps = _all_mps()
    log.info("Found %d current MPs.", len(mps))

    counts = {"embedded": 0, "skipped": 0, "no-appgs": 0, "error": 0}

    for i, mp in enumerate(mps, 1):
        name = mp["nameDisplayAs"]
        try:
            result = _ingest_mp(conn, client, mp, twfy_key)
            status = result["status"]
            if status == "embedded":
                counts["embedded"] += result["embedded"]
                counts["skipped"]  += result["skipped"]
                log.info("[%3d/%d] embedded %-3d  skipped %-3d  %s",
                         i, len(mps), result["embedded"], result["skipped"], name)
            elif status == "skip":
                counts["skipped"] += result["count"]
                log.info("[%3d/%d] skip  (%d unchanged)  %s", i, len(mps), result["count"], name)
            else:
                counts["no-appgs"] += 1
                log.info("[%3d/%d] no-appgs  %s", i, len(mps), name)
        except Exception as exc:
            counts["error"] += 1
            log.error("[%3d/%d] ERROR %s: %s", i, len(mps), name, exc)

        time.sleep(0.5)  # TWFY rate limit is lenient but be polite

    conn.close()
    log.info(
        "\nDone. embedded=%d  skipped=%d  no-appgs=%d  errors=%d",
        counts["embedded"], counts["skipped"], counts["no-appgs"], counts["error"],
    )


if __name__ == "__main__":
    main()
