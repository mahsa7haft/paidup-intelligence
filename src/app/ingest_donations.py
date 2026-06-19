"""
Ingest Electoral Commission party donation records into party_donations_vectors.

Usage:
    PYTHONPATH=src uv run python -m app.ingest_donations

Fetches all political party donations from the Electoral Commission API,
embeds each record, and upserts into party_donations_vectors. Only calls
the OpenAI API for records whose content has changed since the last run.
"""

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import requests
from dotenv import load_dotenv
from openai import OpenAI
from pgvector.psycopg2 import register_vector

load_dotenv()

EC_API      = "https://search.electoralcommission.org.uk/api/search/Donations"
EMBED_MODEL = "text-embedding-3-small"
EMBED_BATCH = 100
FETCH_ROWS  = 100  # records per API page

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ── Electoral Commission API ───────────────────────────────────────────────────

def _parse_ms_date(value: str | None) -> str:
    """Convert /Date(1234567890000)/ to YYYY-MM-DD. Returns '' on failure."""
    if not value:
        return ""
    m = re.search(r"/Date\((\d+)\)/", value)
    if not m:
        return ""
    ts = int(m.group(1)) / 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _fetch_page(params: dict, attempt: int = 0) -> dict:
    """Fetch one page from the EC API with up to 3 retries on timeout."""
    try:
        r = requests.get(EC_API, params=params, timeout=60)
        r.raise_for_status()
        return r.json()
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
        if attempt >= 2:
            raise
        wait = 5 * (attempt + 1)
        log.warning("EC API timeout, retrying in %ds… (%s)", wait, exc)
        time.sleep(wait)
        return _fetch_page(params, attempt + 1)


def _donation_pages():
    """
    Generator — yields one parsed page of records at a time.
    Fetches, parses, and yields immediately so the caller can embed+upsert
    each page without holding all 81k records in memory.
    """
    params = {
        "query":                   "",
        "sort":                    "AcceptedDate",
        "order":                   "desc",
        "et":                      "pp",
        "date":                    "All",
        "register":                ["gb", "ni"],
        "isIrishSourceYes":        "true",
        "isIrishSourceNo":         "true",
        "includeOutsideSection75": "true",
        "rows":                    FETCH_ROWS,
        "start":                   0,
    }

    fetched, total = 0, None
    while True:
        data    = _fetch_page(params)
        total   = total or data.get("Total", 0)
        results = data.get("Result", [])
        if not results:
            break
        fetched += len(results)
        log.info("  fetched %d / %d", fetched, total)
        yield [r for raw in results if (r := _parse_record(raw))]
        if fetched >= total:
            break
        params["start"] += FETCH_ROWS
        time.sleep(0.3)


def _parse_record(raw: dict) -> dict | None:
    ec_ref = raw.get("ECRef", "").strip()
    party  = raw.get("RegulatedEntityName", "").strip()
    donor  = raw.get("DonorName", "").strip()
    if not (ec_ref and party and donor):
        return None

    return {
        "ec_ref":        ec_ref,
        "party":         party,
        "donor":         donor,
        "value":         float(raw.get("Value") or 0),
        "date":          _parse_ms_date(raw.get("AcceptedDate")),
        "dtype":         raw.get("DonationType") or "",
        "nature":        raw.get("NatureOfDonation") or "",
        "donor_status":  raw.get("DonorStatus") or "",
        "is_bequest":    bool(raw.get("IsBequest")),
        "is_agg":        bool(raw.get("IsAggregation")),
        "is_irish":      bool(raw.get("IsIrishSource")),
        "account_unit":  raw.get("AccountingUnitName") or "",
        "period":        raw.get("ReportingPeriodName") or "",
    }


# ── Content + hash ─────────────────────────────────────────────────────────────

def _build_content(record: dict) -> str:
    amount = f"£{record['value']:,.0f}" if record["value"] else "an unspecified amount"
    date   = record["date"] or "unknown date"
    dtype  = record["dtype"] or "donation"
    return (
        f"The {record['party']} received {amount} from {record['donor']} "
        f"as a {dtype} on {date}."
    )


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


# ── Metadata enrichment ────────────────────────────────────────────────────────

def _load_enrichment(conn) -> tuple[dict, list]:
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


def _build_metadata(record: dict, company_map: dict, tag_rules: list) -> dict:
    donor_lower = record["donor"].lower()
    company = company_map.get(donor_lower, {})
    tags = [
        {"tag": r["tag"], "label": r["label"]}
        for r in tag_rules
        if r["pattern"] in donor_lower
    ]
    return {
        "ec_ref":       record["ec_ref"],
        "dtype":        record["dtype"],
        "nature":       record["nature"],
        "donor_status": record["donor_status"],
        "is_bequest":   record["is_bequest"],
        "is_agg":       record["is_agg"],
        "is_irish":     record["is_irish"],
        "account_unit": record["account_unit"],
        "period":       record["period"],
        "company_name": company.get("company_name"),
        "logo_domain":  company.get("logo_domain"),
        "tags":         tags,
    }


# ── Embeddings ─────────────────────────────────────────────────────────────────

def _embed_batch(client: OpenAI, texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]


# ── Database ───────────────────────────────────────────────────────────────────

def _fetch_existing_hashes(cur) -> dict[str, str]:
    cur.execute("SELECT source_id, content_hash FROM party_donations_vectors")
    return {row[0]: row[1] for row in cur.fetchall()}


def _upsert(cur, rows: list[dict]) -> None:
    psycopg2.extras.execute_batch(
        cur,
        """
        INSERT INTO party_donations_vectors
            (source_id, party_name, donor_name, amount, donation_date,
             content, metadata, embedding, content_hash)
        VALUES
            (%(source_id)s, %(party_name)s, %(donor_name)s, %(amount)s, %(donation_date)s,
             %(content)s, %(metadata)s, %(embedding)s, %(content_hash)s)
        ON CONFLICT (source_id) DO UPDATE SET
            party_name    = EXCLUDED.party_name,
            donor_name    = EXCLUDED.donor_name,
            amount        = EXCLUDED.amount,
            donation_date = EXCLUDED.donation_date,
            content       = EXCLUDED.content,
            metadata      = EXCLUDED.metadata,
            embedding     = EXCLUDED.embedding,
            content_hash  = EXCLUDED.content_hash
        """,
        rows,
    )


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        raise SystemExit("DATABASE_URL not set")
    if not os.environ.get("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY not set")

    db_url = db_url.replace("postgres://", "postgresql://", 1)
    conn   = psycopg2.connect(db_url)
    register_vector(conn)
    client = OpenAI()

    log.info("Loading PaidUp enrichment data…")
    company_map, tag_rules = _load_enrichment(conn)

    log.info("Fetching existing hashes…")
    with conn.cursor() as cur:
        existing = _fetch_existing_hashes(cur)
    log.info("  %d records already in DB.", len(existing))

    log.info("Fetching and embedding EC donations page by page…")
    total_embedded, total_skipped = 0, 0

    for page_records in _donation_pages():
        to_embed = []
        for record in page_records:
            source_id    = f"donation_{record['ec_ref']}"
            content      = _build_content(record)
            content_hash = _sha256(content)
            record["_source_id"]    = source_id
            record["_content"]      = content
            record["_content_hash"] = content_hash
            if existing.get(source_id) != content_hash:
                to_embed.append(record)

        total_skipped += len(page_records) - len(to_embed)

        if not to_embed:
            continue

        embeddings = _embed_batch(client, [r["_content"] for r in to_embed])
        rows = []
        for record, embedding in zip(to_embed, embeddings):
            rows.append({
                "source_id":     record["_source_id"],
                "party_name":    record["party"],
                "donor_name":    record["donor"],
                "amount":        record["value"],
                "donation_date": record["date"] or None,
                "content":       record["_content"],
                "metadata":      json.dumps(_build_metadata(record, company_map, tag_rules)),
                "embedding":     embedding,
                "content_hash":  record["_content_hash"],
            })

        with conn.cursor() as cur:
            _upsert(cur, rows)
        conn.commit()
        total_embedded += len(rows)
        log.info("  embedded %d this page  |  total embedded=%d  skipped=%d",
                 len(rows), total_embedded, total_skipped)

    conn.close()
    log.info("\nDone. embedded=%d  skipped=%d", total_embedded, total_skipped)


if __name__ == "__main__":
    main()
