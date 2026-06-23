"""
Audit log for ingestion runs.

Each ingestion script calls start_run() at the top of main() and finish_run()
at the end (success or error). Results are written to the ingest_runs table so
every weekly/monthly run has a permanent record.

Requires: CREATE TABLE ingest_runs (see docs/schema-fixes.sql)
"""

import logging
from datetime import datetime, timezone

import psycopg2

log = logging.getLogger(__name__)


def _connect(db_url: str):
    return psycopg2.connect(db_url)


def check_disk_space(db_url: str, warn_pct: float = 0.80, abort_pct: float = 0.90) -> None:
    """
    Query current DB size against MAX_DB_BYTES from config.
    Logs a warning at 80%, raises SystemExit at 90%. Call at the top of every main().
    """
    from app.config import MAX_DB_BYTES
    try:
        conn = _connect(db_url)
        with conn.cursor() as cur:
            cur.execute("SELECT pg_database_size(current_database())")
            size_bytes = cur.fetchone()[0]
        conn.close()
        pct = size_bytes / MAX_DB_BYTES
        size_pretty = f"{size_bytes / 1024 ** 3:.2f} GB"
        limit_pretty = f"{MAX_DB_BYTES / 1024 ** 3:.1f} GB"
        if pct >= abort_pct:
            raise SystemExit(
                f"ABORT: DB is {size_pretty} / {limit_pretty} ({pct:.0%}) — "
                f"too full to run safely. Free space or upgrade storage first."
            )
        if pct >= warn_pct:
            log.warning("Disk warning: DB is %s / %s (%.0f%% used) — approaching limit.",
                        size_pretty, limit_pretty, pct * 100)
        else:
            log.info("Disk OK: %s / %s (%.0f%% used)", size_pretty, limit_pretty, pct * 100)
    except SystemExit:
        raise
    except Exception as exc:
        log.warning("Could not check disk space: %s", exc)


def start_run(db_url: str, script: str) -> int | None:
    """
    Insert a new row for this run and return its id.
    Returns None if the table doesn't exist yet — callers treat None as a no-op.
    """
    try:
        conn = _connect(db_url)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingest_runs (script, started_at, status)
                VALUES (%s, %s, 'running')
                RETURNING id
                """,
                (script, datetime.now(tz=timezone.utc)),
            )
            run_id = cur.fetchone()[0]
        conn.commit()
        conn.close()
        log.info("Run %d started  (script=%s)", run_id, script)
        return run_id
    except Exception as exc:
        log.warning("Could not record run start (ingest_runs table missing?): %s", exc)
        return None


def update_run_progress(
    db_url: str,
    run_id: int | None,
    embedded: int = 0,
    skipped: int = 0,
    errors: int = 0,
) -> None:
    """Update live counters mid-run so the table shows progress before finish_run is called."""
    if run_id is None:
        return
    try:
        conn = _connect(db_url)
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE ingest_runs
                SET embedded = %s, skipped = %s, errors = %s, last_updated_at = %s
                WHERE id = %s
                """,
                (embedded, skipped, errors, datetime.now(tz=timezone.utc), run_id),
            )
        conn.commit()
        conn.close()
    except Exception as exc:
        log.warning("Could not update run progress: %s", exc)


def finish_run(
    db_url: str,
    run_id: int | None,
    status: str,
    embedded: int = 0,
    skipped: int = 0,
    errors: int = 0,
    notes: str = "",
) -> None:
    """Update the run row with completion stats. Safe to call even if start_run returned None."""
    if run_id is None:
        return
    try:
        conn = _connect(db_url)
        with conn.cursor() as cur:
            now = datetime.now(tz=timezone.utc)
            cur.execute(
                """
                UPDATE ingest_runs
                SET finished_at     = %s,
                    last_updated_at = %s,
                    status          = %s,
                    embedded        = %s,
                    skipped         = %s,
                    errors          = %s,
                    notes           = %s
                WHERE id = %s
                """,
                (now, now, status, embedded, skipped, errors, notes, run_id),
            )
        conn.commit()
        conn.close()
        log.info("Run %d finished  status=%s  embedded=%d  skipped=%d  errors=%d",
                 run_id, status, embedded, skipped, errors)
    except Exception as exc:
        log.warning("Could not record run finish: %s", exc)
