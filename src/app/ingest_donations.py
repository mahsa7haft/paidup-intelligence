"""
Ingest Electoral Commission party donation records into party_donations_vectors.

Usage:
    PYTHONPATH=src uv run python -m app.ingest_donations

Fetches all political party donations from the Electoral Commission API,
embeds each record, and upserts into party_donations_vectors. Only calls
the OpenAI API for records whose content has changed since the last run.

Unlike the per-MP scripts, this iterates EC API pages, so it implements its
own ingest() loop on top of the shared pipeline scaffolding.
"""

import json
import logging
import re
import time
from datetime import datetime, timezone

import requests
from openai import OpenAI

from app import run_log
from app.config import EC_API, FETCH_ROWS
from app.ingest_common import (
    Checkpoint, IngestionPipeline, PreparedRecord, company_and_tags, connect,
    embed_texts, fetch_existing_hashes, load_enrichment, sha256, upsert,
)

log = logging.getLogger(__name__)


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


def _parse_record(raw: dict) -> dict | None:
    ec_ref = (raw.get("ECRef") or "").strip()
    party  = (raw.get("RegulatedEntityName") or "").strip()
    donor  = (raw.get("DonorName") or "").strip()
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


def _build_content(record: dict) -> str:
    amount = f"£{record['value']:,.0f}" if record["value"] else "an unspecified amount"
    date   = record["date"] or "unknown date"
    dtype  = record["dtype"] or "donation"
    return (
        f"The {record['party']} received {amount} from {record['donor']} "
        f"as a {dtype} on {date}."
    )


def _build_metadata(record: dict, company_map: dict, tag_rules: list) -> dict:
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
        **company_and_tags(record["donor"], company_map, tag_rules),
    }


class DonationsIngestion(IngestionPipeline):
    script_name = "ingest_donations"
    checkpoint  = Checkpoint(".ingest_donations_checkpoint.json", "start")
    table       = "party_donations_vectors"
    columns     = ["source_id", "party_name", "donor_name", "amount", "donation_date",
                   "content", "metadata", "embedding", "content_hash"]

    def setup(self) -> None:
        self.company_map, self.tag_rules = load_enrichment()

    def ingest(self, db_url: str, client: OpenAI, run_id: int | None) -> None:
        conn = connect(db_url)
        try:
            log.info("Fetching existing hashes…")
            with conn.cursor() as cur:
                existing = fetch_existing_hashes(cur, self.table)
            log.info("  %d records already in DB.", len(existing))

            log.info("Fetching and embedding EC donations page by page…")
            for page_records, page_start in self._donation_pages():
                prepared = []
                for record in page_records:
                    content = _build_content(record)
                    prepared.append(PreparedRecord(
                        source_id=f"donation_{record['ec_ref']}",
                        content=content,
                        content_hash=sha256(content),
                        record=record,
                    ))

                to_embed = [p for p in prepared if existing.get(p.source_id) != p.content_hash]
                self.counts["skipped"] += len(prepared) - len(to_embed)

                if to_embed:
                    embeddings = embed_texts(client, [p.content for p in to_embed])
                    rows = [
                        {
                            "source_id":     p.source_id,
                            "party_name":    p.record["party"],
                            "donor_name":    p.record["donor"],
                            "amount":        p.record["value"],
                            "donation_date": p.record["date"] or None,
                            "content":       p.content,
                            "metadata":      json.dumps(_build_metadata(
                                                 p.record, self.company_map, self.tag_rules)),
                            "embedding":     embedding,
                            "content_hash":  p.content_hash,
                        }
                        for p, embedding in zip(to_embed, embeddings)
                    ]
                    with conn.cursor() as cur:
                        upsert(cur, self.table, self.columns, rows)
                    conn.commit()
                    self.counts["embedded"] += len(rows)
                    log.info("  embedded %d this page  |  total embedded=%d  skipped=%d",
                             len(rows), self.counts["embedded"], self.counts["skipped"])

                self.checkpoint.save(page_start)
                run_log.update_run_progress(db_url, run_id,
                                            self.counts["embedded"], self.counts["skipped"])
        finally:
            conn.close()

    def _donation_pages(self):
        """
        Generator — yields (records, start_offset) one page at a time.
        Resumes from the saved checkpoint so re-runs skip already-processed pages.
        Caller saves the checkpoint AFTER a successful upsert using the yielded offset.
        """
        resume_at = self.checkpoint.load()
        if resume_at:
            log.info("Resuming from EC API offset %d (delete %s to start over)",
                     resume_at, self.checkpoint.path)

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
            "start":                   resume_at,
        }

        fetched, total = resume_at, None
        while True:
            data    = _fetch_page(params)
            total   = total or data.get("Total", 0)
            results = data.get("Result", [])
            if not results:
                break
            fetched += len(results)
            log.info("  fetched %d / %d", fetched, total)
            yield [r for raw in results if (r := _parse_record(raw))], params["start"]
            if fetched >= total:
                break
            params["start"] += FETCH_ROWS
            time.sleep(0.3)


def main() -> None:
    DonationsIngestion().run()


if __name__ == "__main__":
    main()
