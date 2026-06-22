"""
Ingest MP voting records (divisions) into votes_vectors.

Usage:
    PYTHONPATH=src uv run python -m app.ingest_votes

Fetches every division vote for all current Commons MPs via the Parliament
Members API. ~500,000 records expected. Only re-embeds changed records.

Note: This script is slow on first run (~2-3 hours for 500k records due to
API pagination). Subsequent runs are fast — only new divisions are embedded.
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

from app.config import EMBED_BATCH, EMBED_MODEL, MEMBERS_API
from app import run_log

load_dotenv()

PAGE_SIZE = 25  # Parliament API max for the voting endpoint
CHECKPOINT_FILE = ".ingest_votes_checkpoint.json"


def _load_checkpoint() -> int:
    try:
        with open(CHECKPOINT_FILE) as f:
            return json.load(f).get("mp_index", 0)
    except (FileNotFoundError, ValueError):
        return 0


def _save_checkpoint(mp_index: int) -> None:
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump({"mp_index": mp_index}, f)


def _clear_checkpoint() -> None:
    try:
        os.remove(CHECKPOINT_FILE)
    except FileNotFoundError:
        pass

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


# ── Content + hash ─────────────────────────────────────────────────────────────

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


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ── Database ───────────────────────────────────────────────────────────────────

def _fetch_existing_hashes(cur, mp_id: int) -> dict[str, str]:
    cur.execute(
        "SELECT source_id, content_hash FROM votes_vectors WHERE mp_id = %s",
        (mp_id,),
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def _upsert(cur, rows: list[dict]) -> None:
    psycopg2.extras.execute_batch(
        cur,
        """
        INSERT INTO votes_vectors
            (source_id, mp_id, mp_name, division_id, vote, vote_date,
             content, metadata, embedding, content_hash)
        VALUES
            (%(source_id)s, %(mp_id)s, %(mp_name)s, %(division_id)s, %(vote)s, %(vote_date)s,
             %(content)s, %(metadata)s, %(embedding)s, %(content_hash)s)
        ON CONFLICT (source_id) DO UPDATE SET
            mp_name      = EXCLUDED.mp_name,
            vote         = EXCLUDED.vote,
            vote_date    = EXCLUDED.vote_date,
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

def _connect(db_url: str):
    conn = psycopg2.connect(db_url)
    register_vector(conn)
    return conn


def _ingest_mp(db_url: str, client: OpenAI, mp: dict) -> dict:
    member_id = mp["id"]
    name      = mp["nameDisplayAs"]
    party     = mp["latestParty"]["name"]

    votes = _get_votes(member_id)
    if not votes:
        return {"status": "no-votes"}

    conn = _connect(db_url)
    with conn.cursor() as cur:
        existing = _fetch_existing_hashes(cur, member_id)
    conn.close()

    to_embed = []
    for vote in votes:
        division_id  = str(vote.get("id", ""))
        source_id    = f"vote_{member_id}_{division_id}"
        content      = _build_content(name, party, vote)
        content_hash = _sha256(content)
        vote["_source_id"]    = source_id
        vote["_division_id"]  = division_id
        vote["_content"]      = content
        vote["_content_hash"] = content_hash
        if existing.get(source_id) != content_hash:
            to_embed.append(vote)

    if not to_embed:
        return {"status": "skip", "count": len(votes)}

    embeddings = []
    for i in range(0, len(to_embed), EMBED_BATCH):
        batch = to_embed[i : i + EMBED_BATCH]
        embeddings.extend(_embed_batch(client, [v["_content"] for v in batch]))

    rows = []
    for vote, embedding in zip(to_embed, embeddings):
        date_val = (vote.get("date") or "")[:10] or None
        rows.append({
            "source_id":   vote["_source_id"],
            "mp_id":       member_id,
            "mp_name":     name,
            "division_id": vote["_division_id"],
            "vote":        _vote_label(vote),
            "vote_date":   date_val,
            "content":     vote["_content"],
            "metadata":    json.dumps({
                "title":          vote.get("title"),
                "division_number": vote.get("divisionNumber"),
                "number_in_favour": vote.get("numberInFavour"),
                "number_against":   vote.get("numberAgainst"),
            }),
            "embedding":    embedding,
            "content_hash": vote["_content_hash"],
        })

    conn = _connect(db_url)
    with conn.cursor() as cur:
        _upsert(cur, rows)
    conn.commit()
    conn.close()

    return {"status": "embedded", "embedded": len(rows), "skipped": len(votes) - len(to_embed)}


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        raise SystemExit("DATABASE_URL not set")
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY not set")

    db_url = db_url.replace("postgres://", "postgresql://", 1)
    client = OpenAI()

    log.info("Fetching MP list…")
    mps = _all_mps()
    log.info("Found %d current MPs.", len(mps))

    counts = {"embedded": 0, "skipped": 0, "no-votes": 0, "error": 0}

    resume_from = _load_checkpoint()
    if resume_from:
        log.info("Resuming from MP %d/%d (delete %s to start over)",
                 resume_from, len(mps), CHECKPOINT_FILE)

    run_id = run_log.start_run(db_url, "ingest_votes")
    try:
        for i, mp in enumerate(mps, 1):
            if i <= resume_from:
                continue
            name = mp["nameDisplayAs"]
            try:
                result = _ingest_mp(db_url, client, mp)
                status = result["status"]
                if status == "embedded":
                    counts["embedded"] += result["embedded"]
                    counts["skipped"]  += result["skipped"]
                    log.info("[%3d/%d] embedded %-4d  skipped %-4d  %s",
                             i, len(mps), result["embedded"], result["skipped"], name)
                elif status == "skip":
                    counts["skipped"] += result["count"]
                    log.info("[%3d/%d] skip  (%d unchanged)  %s", i, len(mps), result["count"], name)
                else:
                    counts["no-votes"] += 1
                    log.info("[%3d/%d] no-votes  %s", i, len(mps), name)
            except Exception as exc:
                counts["error"] += 1
                log.error("[%3d/%d] ERROR %s: %s", i, len(mps), name, exc)

            _save_checkpoint(i)
            run_log.update_run_progress(db_url, run_id, counts["embedded"], counts["skipped"], counts["error"])
            time.sleep(0.3)

        _clear_checkpoint()
        log.info(
            "\nDone. embedded=%d  skipped=%d  no-votes=%d  errors=%d",
            counts["embedded"], counts["skipped"], counts["no-votes"], counts["error"],
        )
        run_log.finish_run(db_url, run_id, "success",
                           counts["embedded"], counts["skipped"], counts["error"])
    except Exception as exc:
        run_log.finish_run(db_url, run_id, "error",
                           counts["embedded"], counts["skipped"], counts["error"], notes=str(exc))
        raise


if __name__ == "__main__":
    main()
