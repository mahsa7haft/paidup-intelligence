"""
Run all ingestion scripts in sequence.

Used as the entry point for the Railway cron job. Each script handles its own
checkpointing, run logging, and error handling — this just calls them in order.

Usage:
    PYTHONPATH=src uv run python -m app.ingest_all

Order:
    1. interests   (~5 min,  ~20k records)
    2. donations   (~15 min, ~81k records)
    3. votes       (~2-3 hr, ~500k records)
    4. appgs       (skipped in Phase 1 — no free API, table stays empty)
"""

import logging
import sys

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger(__name__)


def main() -> None:
    from app.ingest_interests import main as run_interests
    from app.ingest_donations import main as run_donations
    from app.ingest_votes import main as run_votes

    steps = [
        ("interests",  run_interests),
        ("donations",  run_donations),
        ("votes",      run_votes),
    ]

    failed = []
    for name, run in steps:
        log.info("=" * 60)
        log.info("Starting %s", name)
        log.info("=" * 60)
        try:
            run()
        except Exception as exc:
            log.error("%s failed: %s", name, exc)
            failed.append(name)

    log.info("=" * 60)
    if failed:
        log.error("Completed with failures: %s", ", ".join(failed))
        sys.exit(1)
    else:
        log.info("All ingestion scripts completed successfully.")


if __name__ == "__main__":
    main()
