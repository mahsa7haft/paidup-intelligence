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
