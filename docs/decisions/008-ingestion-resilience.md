---
title: Checkpoint files + run audit log for ingestion resilience
status: Accepted
date: 2026-06-21
---

## Context

The ingestion scripts run for extended periods (donations: ~15 min, votes: 2–3 hrs).
Three problems emerged during the first runs:

1. **No resume on crash** — every restart began at record 0, re-fetching and
   hash-checking all previously processed records before reaching the new ones.
   This wasted 5–10 minutes of EC API calls on every restart.

2. **No run history** — there was no record of when a script last ran, how many
   records it processed, or whether it finished cleanly. Weekly/monthly reruns had
   no way to verify the previous run had completed correctly.

3. **Constants duplicated across scripts** — `EMBED_MODEL`, `EMBED_BATCH`,
   `MEMBERS_API`, and EC_API were hardcoded identically in every ingestion script.
   Changing the embedding model or an API URL required editing every file.

## Decision

Three changes applied together:

### 1. Checkpoint files (crash resume)

Each script writes a lightweight JSON file after each successfully processed unit
(page for donations, MP for interests/votes). On restart, it reads the checkpoint
and jumps straight to where it left off. The file is deleted on clean completion.

```
Checkpoint file: .ingest_donations_checkpoint.json  →  {"start": 29200}
                 .ingest_interests_checkpoint.json  →  {"mp_index": 312}
                 .ingest_votes_checkpoint.json      →  {"mp_index": 312}

Run 1 (crashes at page 584):
  page 1    → process → save {"start": 0}
  page 2    → process → save {"start": 50}
  ...
  page 584  → process → save {"start": 29150}
  CRASH

Run 2 (resumes):
  read checkpoint → start = 29150
  skip pages 1–583 entirely  ← no API calls, no hash checks
  page 584  → process → save {"start": 29200}
  ...
  page 1628 → process → delete checkpoint
  Done.

To force a full re-run from scratch: delete the checkpoint file.
```

### 2. Run audit log (`ingest_runs` table)

Each script calls `run_log.start_run()` at the top of `main()` and
`run_log.finish_run()` on success or error. Results are written to `ingest_runs`.

```
ingest_runs table:

  id │ script            │ started_at          │ finished_at         │ status  │ embedded │ skipped │ errors │ notes
  ───┼───────────────────┼─────────────────────┼─────────────────────┼─────────┼──────────┼─────────┼────────┼───────
   1 │ ingest_donations  │ 2026-06-21 09:00:00 │ 2026-06-21 09:14:32 │ success │    81375 │       0 │      0 │
   2 │ ingest_interests  │ 2026-06-21 09:15:00 │ 2026-06-21 09:17:12 │ success │    18432 │       0 │      0 │
   3 │ ingest_donations  │ 2026-06-28 09:00:00 │ 2026-06-28 09:02:11 │ success │      142 │   81233 │      0 │  ← weekly rerun, only new records
   4 │ ingest_donations  │ 2026-07-01 11:22:00 │ (null)              │ running │    29200 │   14600 │      0 │  ← crashed, no finished_at

Rows with finished_at IS NULL (or status = 'running') indicate interrupted runs.
```

### 3. Shared `config.py`

Constants shared across scripts moved to `src/app/config.py`:

```
Before:                          After:

ingest_donations.py              config.py
  EMBED_MODEL = "..."    ──┐       EMBED_MODEL = "text-embedding-3-small"
  EMBED_BATCH = 100        │       EMBED_BATCH = 100
  EC_API = "..."           │       MEMBERS_API  = "https://members-api..."
                           │       INTERESTS_API = "https://interests-api..."
ingest_interests.py        │       EC_API = "https://search.electoral..."
  EMBED_MODEL = "..."    ──┤       FETCH_ROWS = 50
  EMBED_BATCH = 100        │
  MEMBERS_API = "..."      │     each script:
                           │       from app.config import EMBED_MODEL, EMBED_BATCH, ...
ingest_votes.py            │
  EMBED_MODEL = "..."    ──┘
  EMBED_BATCH = 100
  MEMBERS_API = "..."
```

## Consequences

**Good:**
- Interrupted runs resume in seconds, not minutes — no wasted API calls or hash checks
- Every run is permanently recorded; easy to audit what ran, when, and how many records changed
- Changing the embedding model or an API URL is a one-line edit in `config.py`
- `status = 'running'` with no `finished_at` is a clear signal that a run was interrupted

**Bad / watch out for:**
- Checkpoint files are local to the machine running the script — if you switch machines
  mid-run (e.g., from local to Railway cron), delete the checkpoint first
- The `ingest_runs` table must exist before running the scripts. `run_log.start_run()`
  logs a warning and returns `None` if the table is missing — it will not crash the script
- To force a full re-run: delete the checkpoint file AND the script will still skip
  unchanged records via content_hash (see [[004-smart-reembed]])

## Related

- [[004-smart-reembed]] — content_hash skips unchanged records (different from checkpoint: that skips pages entirely)
- [[006-db-connection-strategy]] — short-lived connections used by `run_log.py` too
- `docs/schema-fixes.sql` — `CREATE TABLE ingest_runs` statement
- `src/app/config.py`, `src/app/run_log.py`
