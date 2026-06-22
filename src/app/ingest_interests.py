"""
Ingest Parliament Register of Members' Financial Interests into interests_vectors.

Usage:
    PYTHONPATH=src uv run python -m app.ingest_interests

Fetches all 647 current Commons MPs, embeds each declared interest, and upserts
into interests_vectors. Only calls the OpenAI API for records whose content has
changed since the last run (hash check).

Note: DATABASE_URL on Railway uses the internal hostname (postgres.railway.internal).
Run this script from within Railway (cron job) or swap to the public URL for local runs.
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

from app.config import EMBED_BATCH, EMBED_MODEL, INTERESTS_API, MEMBERS_API
from app import run_log

load_dotenv()

PAGE_SIZE = 100  # Parliament Members/Search API page size
CHECKPOINT_FILE = ".ingest_interests_checkpoint.json"


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
    """Return all current Commons MPs from the Parliament Members API."""
    mps, skip = [], 0
    while True:
        r = requests.get(
            f"{MEMBERS_API}/Members/Search",
            params={"House": 1, "IsCurrentMember": "true", "take": PAGE_SIZE, "skip": skip},
            timeout=10,
        )
        r.raise_for_status()
        data  = r.json()
        items = data.get("items", [])
        if not items:
            break
        mps.extend(m["value"] for m in items)
        skip += PAGE_SIZE
        if skip >= data.get("totalResults", 0):
            break
    return mps


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


# ── Content + hash ─────────────────────────────────────────────────────────────

def _build_content(name: str, party: str, interest: dict) -> str:
    amount = f"£{interest['value']:,.0f}" if interest["value"] else "an unspecified amount"
    date   = interest["date"] or "unknown date"
    return (
        f"MP {name} ({party}) received {amount} from {interest['donor']} "
        f"as a {interest['category']}, registered {date}."
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ── Metadata enrichment from PaidUp tables ────────────────────────────────────

def _load_enrichment(conn) -> tuple[dict, list]:
    """
    Load donor_company_links and donor_tags from PaidUp's shared tables.
    Returns (company_map, tag_rules) — used to enrich metadata at embed time.
    """
    company_map, tag_rules = {}, []
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT donor_name, company_name, logo_domain FROM donor_company_links")
            for row in cur.fetchall():
                company_map[row[0].lower()] = {"company_name": row[1], "logo_domain": row[2]}
            cur.execute("SELECT name_pattern, tag, label FROM donor_tags")
            tag_rules = [{"pattern": r[0], "tag": r[1], "label": r[2]} for r in cur.fetchall()]
    except Exception as exc:
        log.warning("Could not load PaidUp enrichment tables: %s", exc)
    return company_map, tag_rules


def _build_metadata(interest: dict, company_map: dict, tag_rules: list) -> dict:
    donor_lower = interest["donor"].lower()

    company = company_map.get(donor_lower, {})
    tags = [
        {"tag": r["tag"], "label": r["label"]}
        for r in tag_rules
        if r["pattern"] in donor_lower
    ]
    return {
        "donor":        interest["donor"],
        "value":        interest["value"],
        "date":         interest["date"],
        "summary":      interest["summary"],
        "company_name": company.get("company_name"),
        "logo_domain":  company.get("logo_domain"),
        "tags":         tags,
        "raw":          interest["raw"],
    }


# ── Embeddings ─────────────────────────────────────────────────────────────────

def _embed_batch(client: OpenAI, texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]


# ── Database ───────────────────────────────────────────────────────────────────

def _fetch_existing_hashes(cur, mp_id: int) -> dict[str, str]:
    """Return {source_id: content_hash} for all stored interests for this MP."""
    cur.execute(
        "SELECT source_id, content_hash FROM interests_vectors WHERE mp_id = %s",
        (mp_id,),
    )
    return {row[0]: row[1] for row in cur.fetchall()}


def _upsert(cur, rows: list[dict]) -> None:
    psycopg2.extras.execute_batch(
        cur,
        """
        INSERT INTO interests_vectors
            (source_id, mp_id, mp_name, category, content, metadata, embedding, content_hash)
        VALUES
            (%(source_id)s, %(mp_id)s, %(mp_name)s, %(category)s,
             %(content)s, %(metadata)s, %(embedding)s, %(content_hash)s)
        ON CONFLICT (source_id) DO UPDATE SET
            mp_name      = EXCLUDED.mp_name,
            category     = EXCLUDED.category,
            content      = EXCLUDED.content,
            metadata     = EXCLUDED.metadata,
            embedding    = EXCLUDED.embedding,
            content_hash = EXCLUDED.content_hash
        """,
        rows,
    )


# ── Per-MP ingestion ───────────────────────────────────────────────────────────

def _connect(db_url: str):
    conn = psycopg2.connect(db_url)
    register_vector(conn)
    return conn


def _ingest_mp(db_url: str, client: OpenAI, mp: dict, company_map: dict, tag_rules: list) -> dict:
    member_id = mp["id"]
    name      = mp["nameDisplayAs"]
    party     = mp["latestParty"]["name"]

    raw_interests = _get_interests(member_id)
    if not raw_interests:
        return {"status": "no-interests"}

    interests = _parse_interests(raw_interests)

    conn = _connect(db_url)
    with conn.cursor() as cur:
        existing = _fetch_existing_hashes(cur, member_id)
    conn.close()

    # Determine which interests need embedding
    to_embed = []
    for interest in interests:
        source_id = f"interests_{member_id}_{interest['id']}" if interest["id"] else \
                    f"interests_{member_id}_{_sha256(interest['summary'] + interest['date'])[:12]}"
        content      = _build_content(name, party, interest)
        content_hash = _sha256(content)
        interest["_source_id"]    = source_id
        interest["_content"]      = content
        interest["_content_hash"] = content_hash
        if existing.get(source_id) != content_hash:
            to_embed.append(interest)

    if not to_embed:
        return {"status": "skip", "count": len(interests)}

    # Embed in batches
    embeddings = []
    for i in range(0, len(to_embed), EMBED_BATCH):
        batch  = to_embed[i : i + EMBED_BATCH]
        vecs   = _embed_batch(client, [e["_content"] for e in batch])
        embeddings.extend(vecs)

    # Build upsert rows
    rows = []
    for interest, embedding in zip(to_embed, embeddings):
        rows.append({
            "source_id":    interest["_source_id"],
            "mp_id":        member_id,
            "mp_name":      name,
            "category":     interest["category"],
            "content":      interest["_content"],
            "metadata":     json.dumps(_build_metadata(interest, company_map, tag_rules)),
            "embedding":    embedding,
            "content_hash": interest["_content_hash"],
        })

    conn = _connect(db_url)
    with conn.cursor() as cur:
        _upsert(cur, rows)
    conn.commit()
    conn.close()

    return {"status": "embedded", "embedded": len(rows), "skipped": len(interests) - len(to_embed)}


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        raise SystemExit("DATABASE_URL not set")
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY not set")

    db_url = db_url.replace("postgres://", "postgresql://", 1)
    client = OpenAI()

    conn = _connect(db_url)
    log.info("Loading PaidUp enrichment data…")
    company_map, tag_rules = _load_enrichment(conn)
    log.info("  donor_company_links: %d  donor_tags: %d", len(company_map), len(tag_rules))
    conn.close()

    log.info("Fetching MP list…")
    mps = _all_mps()
    log.info("Found %d current MPs.", len(mps))

    counts = {"embedded": 0, "skipped": 0, "no-interests": 0, "error": 0}

    resume_from = _load_checkpoint()
    if resume_from:
        log.info("Resuming from MP %d/%d (delete %s to start over)",
                 resume_from, len(mps), CHECKPOINT_FILE)

    run_id = run_log.start_run(db_url, "ingest_interests")
    try:
        for i, mp in enumerate(mps, 1):
            if i <= resume_from:
                continue
            name = mp["nameDisplayAs"]
            try:
                result = _ingest_mp(db_url, client, mp, company_map, tag_rules)
                status = result["status"]
                if status == "embedded":
                    counts["embedded"] += result["embedded"]
                    counts["skipped"]  += result["skipped"]
                    log.info("[%3d/%d] embedded %-3d  skipped %-3d  %s",
                             i, len(mps), result["embedded"], result["skipped"], name)
                elif status == "skip":
                    counts["skipped"] += result["count"]
                    log.info("[%3d/%d] skip            (%d unchanged)  %s",
                             i, len(mps), result["count"], name)
                else:
                    counts["no-interests"] += 1
                    log.info("[%3d/%d] no-interests                     %s", i, len(mps), name)
            except Exception as exc:
                counts["error"] += 1
                log.error("[%3d/%d] ERROR %s: %s", i, len(mps), name, exc)

            _save_checkpoint(i)
            run_log.update_run_progress(db_url, run_id, counts["embedded"], counts["skipped"], counts["error"])
            time.sleep(0.5)

        _clear_checkpoint()
        log.info(
            "\nDone. embedded=%d  skipped=%d  no-interests=%d  errors=%d",
            counts["embedded"], counts["skipped"], counts["no-interests"], counts["error"],
        )
        run_log.finish_run(db_url, run_id, "success",
                           counts["embedded"], counts["skipped"], counts["error"])
    except Exception as exc:
        run_log.finish_run(db_url, run_id, "error",
                           counts["embedded"], counts["skipped"], counts["error"], notes=str(exc))
        raise


if __name__ == "__main__":
    main()
