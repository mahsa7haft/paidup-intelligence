"""
Shared machinery for the ingestion scripts (Template Method).

IngestionPipeline owns the run skeleton every script shares: env validation,
disk safety check, run logging, checkpoint lifecycle. MPIngestionPipeline adds
the per-MP fetch → hash-diff → embed → upsert loop used by interests, votes,
and APPGs. Donations iterates Electoral Commission API pages instead of MPs,
so it subclasses IngestionPipeline directly with its own loop.

Each ingestion script defines a subclass that supplies only what varies:
which records to fetch, how to phrase the content sentence, how to build the
source_id, and which table-specific columns to store.
"""

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass

import psycopg2
import psycopg2.extras
import requests
from dotenv import load_dotenv
from openai import OpenAI
from pgvector.psycopg2 import register_vector

from app.config import EMBED_BATCH, EMBED_MODEL, MEMBERS_API
from app import run_log

load_dotenv()

log = logging.getLogger(__name__)

MP_PAGE_SIZE = 100  # Parliament Members/Search API page size


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def normalize_db_url(url: str) -> str:
    """Railway (and some tools) emit postgres:// — psycopg2 needs postgresql://."""
    return url.replace("postgres://", "postgresql://", 1)


def connect(db_url: str):
    conn = psycopg2.connect(db_url)
    register_vector(conn)
    return conn


def all_mps() -> list[dict]:
    """Return all current Commons MPs from the Parliament Members API."""
    mps, skip = [], 0
    while True:
        r = requests.get(
            f"{MEMBERS_API}/Members/Search",
            params={"House": 1, "IsCurrentMember": "true", "take": MP_PAGE_SIZE, "skip": skip},
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        items = data.get("items", [])
        if not items:
            break
        mps.extend(m["value"] for m in items)
        skip += MP_PAGE_SIZE
        if skip >= data.get("totalResults", 0):
            break
    return mps


def embed_texts(client: OpenAI, texts: list[str]) -> list[list[float]]:
    """Embed texts in EMBED_BATCH-sized API calls, preserving input order."""
    embeddings: list[list[float]] = []
    for i in range(0, len(texts), EMBED_BATCH):
        response = client.embeddings.create(model=EMBED_MODEL, input=texts[i : i + EMBED_BATCH])
        embeddings.extend(item.embedding for item in sorted(response.data, key=lambda x: x.index))
    return embeddings


def load_enrichment() -> tuple[dict, list]:
    """
    Load donor_company_links and donor_tags from PaidUp's shared tables.
    Returns (company_map, tag_rules) — used to enrich metadata at embed time.
    Prefers PAIDUP_DATABASE_URL, falling back to the local DATABASE_URL.
    """
    paidup_url = normalize_db_url(os.environ.get("PAIDUP_DATABASE_URL", ""))
    url = paidup_url or normalize_db_url(os.environ.get("DATABASE_URL", ""))
    log.info("Loading PaidUp enrichment data%s…",
             "" if paidup_url else " (PAIDUP_DATABASE_URL not set, trying local)")

    company_map, tag_rules = {}, []
    conn = connect(url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT donor_name, company_name, logo_domain FROM donor_company_links")
            for row in cur.fetchall():
                company_map[row[0].lower()] = {"company_name": row[1], "logo_domain": row[2]}
            cur.execute("SELECT name_pattern, tag, label FROM donor_tags")
            tag_rules = [{"pattern": r[0], "tag": r[1], "label": r[2]} for r in cur.fetchall()]
    except Exception as exc:
        conn.rollback()
        log.warning("Could not load PaidUp enrichment tables: %s", exc)
    finally:
        conn.close()

    log.info("  donor_company_links: %d  donor_tags: %d", len(company_map), len(tag_rules))
    return company_map, tag_rules


def company_and_tags(donor: str, company_map: dict, tag_rules: list) -> dict:
    """Return the enrichment fields for one donor name (lowercase-keyed lookups)."""
    donor_lower = donor.lower()
    company = company_map.get(donor_lower, {})
    return {
        "company_name": company.get("company_name"),
        "logo_domain":  company.get("logo_domain"),
        "tags": [
            {"tag": r["tag"], "label": r["label"]}
            for r in tag_rules
            if r["pattern"] in donor_lower
        ],
    }


def fetch_existing_hashes(cur, table: str, mp_id: int | None = None) -> dict[str, str]:
    """Return {source_id: content_hash} for stored rows, optionally scoped to one MP."""
    if mp_id is None:
        cur.execute(f"SELECT source_id, content_hash FROM {table}")
    else:
        cur.execute(f"SELECT source_id, content_hash FROM {table} WHERE mp_id = %s", (mp_id,))
    return dict(cur.fetchall())


def upsert(cur, table: str, columns: list[str], rows: list[dict]) -> None:
    """Batch upsert keyed on source_id; every other column takes the new value."""
    # table/columns only ever come from pipeline class constants, never user input,
    # so interpolating them into the SQL is safe.
    col_sql = ", ".join(columns)
    values_sql = ", ".join(f"%({c})s" for c in columns)
    update_sql = ", ".join(f"{c} = EXCLUDED.{c}" for c in columns if c != "source_id")
    psycopg2.extras.execute_batch(
        cur,
        f"INSERT INTO {table} ({col_sql}) VALUES ({values_sql}) "
        f"ON CONFLICT (source_id) DO UPDATE SET {update_sql}",
        rows,
    )


class Checkpoint:
    """Resume marker persisted to a JSON file between runs."""

    def __init__(self, path: str, field: str):
        self.path = path
        self.field = field

    def load(self) -> int:
        try:
            with open(self.path) as f:
                return json.load(f).get(self.field, 0)
        except (FileNotFoundError, ValueError):
            return 0

    def save(self, value: int) -> None:
        with open(self.path, "w") as f:
            json.dump({self.field: value}, f)

    def clear(self) -> None:
        try:
            os.remove(self.path)
        except FileNotFoundError:
            pass


@dataclass
class PreparedRecord:
    """A source record with its derived identity, content sentence, and hash."""
    source_id: str
    content: str
    content_hash: str
    record: dict


class IngestionPipeline:
    """
    Template method for one ingestion run.

    run() owns env validation, the disk check, run logging, and checkpoint
    cleanup. Subclasses implement ingest() (the source-specific loop) and may
    override validate_env() and setup() for extra requirements.
    """

    script_name: str
    checkpoint: Checkpoint
    table: str
    columns: list[str]

    def run(self) -> None:
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            raise SystemExit("DATABASE_URL not set")
        if not os.environ.get("OPENAI_API_KEY"):
            raise SystemExit("OPENAI_API_KEY not set")
        self.validate_env()

        db_url = normalize_db_url(db_url)
        run_log.check_disk_space(db_url)
        client = OpenAI()

        self.counts: dict[str, int] = {"embedded": 0, "skipped": 0, "errors": 0}
        self.setup()

        run_id = run_log.start_run(db_url, self.script_name)
        try:
            self.ingest(db_url, client, run_id)
            self.checkpoint.clear()
            log.info("\nDone. %s", "  ".join(f"{k}={v}" for k, v in self.counts.items()))
            run_log.finish_run(db_url, run_id, "success",
                               self.counts["embedded"], self.counts["skipped"], self.counts["errors"])
        except Exception as exc:
            run_log.finish_run(db_url, run_id, "error",
                               self.counts["embedded"], self.counts["skipped"], self.counts["errors"],
                               notes=str(exc))
            raise

    def validate_env(self) -> None:
        pass

    def setup(self) -> None:
        pass

    def ingest(self, db_url: str, client: OpenAI, run_id: int | None) -> None:
        raise NotImplementedError


class MPIngestionPipeline(IngestionPipeline):
    """
    Per-MP ingestion loop: for each current MP, fetch records, diff content
    hashes against the table, embed only what changed, and upsert.

    Subclasses supply the hooks: fetch_records, build_content, source_id,
    metadata, and row_extras (the table-specific columns).
    """

    empty_status: str
    sleep_seconds: float

    def ingest(self, db_url: str, client: OpenAI, run_id: int | None) -> None:
        log.info("Fetching MP list…")
        mps = all_mps()
        log.info("Found %d current MPs.", len(mps))

        self.counts[self.empty_status] = 0
        resume_from = self.checkpoint.load()
        if resume_from:
            log.info("Resuming from MP %d/%d (delete %s to start over)",
                     resume_from, len(mps), self.checkpoint.path)

        conn = connect(db_url)
        try:
            for i, mp in enumerate(mps, 1):
                if i <= resume_from:
                    continue
                name = mp["nameDisplayAs"]
                try:
                    result = self._ingest_mp(conn, client, mp)
                    status = result["status"]
                    if status == "embedded":
                        self.counts["embedded"] += result["embedded"]
                        self.counts["skipped"] += result["skipped"]
                        log.info("[%3d/%d] embedded %-4d  skipped %-4d  %s",
                                 i, len(mps), result["embedded"], result["skipped"], name)
                    elif status == "skip":
                        self.counts["skipped"] += result["count"]
                        log.info("[%3d/%d] skip  (%d unchanged)  %s",
                                 i, len(mps), result["count"], name)
                    else:
                        self.counts[self.empty_status] += 1
                        log.info("[%3d/%d] %s  %s", i, len(mps), self.empty_status, name)
                except Exception as exc:
                    conn.rollback()
                    self.counts["errors"] += 1
                    log.error("[%3d/%d] ERROR %s: %s", i, len(mps), name, exc)

                self.checkpoint.save(i)
                run_log.update_run_progress(db_url, run_id, self.counts["embedded"],
                                            self.counts["skipped"], self.counts["errors"])
                time.sleep(self.sleep_seconds)
        finally:
            conn.close()

    def _ingest_mp(self, conn, client: OpenAI, mp: dict) -> dict:
        member_id = mp["id"]
        name      = mp["nameDisplayAs"]
        party     = mp["latestParty"]["name"]

        records = self.fetch_records(mp)
        if not records:
            return {"status": self.empty_status}

        with conn.cursor() as cur:
            existing = fetch_existing_hashes(cur, self.table, member_id)

        prepared = []
        for record in records:
            content = self.build_content(name, party, record)
            prepared.append(PreparedRecord(
                source_id=self.source_id(member_id, record),
                content=content,
                content_hash=sha256(content),
                record=record,
            ))

        to_embed = [p for p in prepared if existing.get(p.source_id) != p.content_hash]
        if not to_embed:
            return {"status": "skip", "count": len(records)}

        embeddings = embed_texts(client, [p.content for p in to_embed])
        rows = [
            {
                "source_id":    p.source_id,
                "mp_id":        member_id,
                "mp_name":      name,
                "content":      p.content,
                "metadata":     json.dumps(self.metadata(p.record)),
                "embedding":    embedding,
                "content_hash": p.content_hash,
                **self.row_extras(p.record),
            }
            for p, embedding in zip(to_embed, embeddings)
        ]

        with conn.cursor() as cur:
            upsert(cur, self.table, self.columns, rows)
        conn.commit()

        return {"status": "embedded", "embedded": len(rows),
                "skipped": len(records) - len(to_embed)}

    def fetch_records(self, mp: dict) -> list[dict]:
        raise NotImplementedError

    def build_content(self, name: str, party: str, record: dict) -> str:
        raise NotImplementedError

    def source_id(self, member_id: int, record: dict) -> str:
        raise NotImplementedError

    def metadata(self, record: dict) -> dict:
        raise NotImplementedError

    def row_extras(self, record: dict) -> dict:
        raise NotImplementedError
