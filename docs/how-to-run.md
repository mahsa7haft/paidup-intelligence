# How to Run Ingestion Scripts

Reference guide for running the four ingestion scripts that populate the vector tables.

---

## Prerequisites

Make sure your `.env` file exists with the right keys (copy from `.env.example`):

```
DATABASE_URL=postgresql://...   ← Railway public URL for local runs
OPENAI_API_KEY=sk-...
```

---

## Option 1 — Run locally (quick test / small scripts)

Standard command for any ingestion script:

```bash
PYTHONPATH=src uv run python -m app.ingest_interests
PYTHONPATH=src uv run python -m app.ingest_donations
PYTHONPATH=src uv run python -m app.ingest_votes
PYTHONPATH=src uv run python -m app.ingest_appgs
```

**Problem:** If your Mac goes to sleep, the network drops and Railway closes the Postgres connection mid-run.

**Fix — keep Mac awake with `caffeinate`:**

```bash
PYTHONPATH=src caffeinate -i uv run python -m app.ingest_donations
```

`caffeinate -i` prevents the Mac from sleeping until the command finishes.
Use this for any run expected to take more than a few minutes (donations ~15 min, votes ~2–3 hrs).

---

## Checkpoint files

Each script saves its progress so interrupted runs resume where they left off.

| Script | Checkpoint file |
|--------|----------------|
| ingest_donations | `.ingest_donations_checkpoint.json` |
| ingest_interests | `.ingest_interests_checkpoint.json` |
| ingest_votes | `.ingest_votes_checkpoint.json` |

The checkpoint is deleted automatically on clean completion.

**To force a full re-run from scratch**, delete the checkpoint file first:

```bash
rm .ingest_donations_checkpoint.json
```

---

## Checking run history

Every run is recorded in the `ingest_runs` table. Connect to Railway Postgres and query:

```sql
-- See all recent runs
SELECT id, script, started_at, finished_at, status, embedded, skipped, errors
FROM ingest_runs
ORDER BY started_at DESC
LIMIT 20;

-- Find interrupted runs (crashed mid-run)
SELECT * FROM ingest_runs
WHERE finished_at IS NULL OR status = 'running'
ORDER BY started_at DESC;
```

---

## Checking record counts

```sql
SELECT 'interests'  AS table, COUNT(*) FROM interests_vectors
UNION ALL
SELECT 'donations',            COUNT(*) FROM party_donations_vectors
UNION ALL
SELECT 'votes',                COUNT(*) FROM votes_vectors
UNION ALL
SELECT 'appgs',                COUNT(*) FROM appg_vectors;
```

---

## Option 2 — Scheduled cron job on Railway

Railway has a native Cron Job service type — no Docker needed, same nixpacks build as the main app.

### Step 1 — Create the cron service

1. Go to your Railway project dashboard
2. Click **New Service → Empty Service**
3. In the service settings, change the service type to **Cron Job**
4. Connect the same GitHub repo (`paidup-intelligence`)

### Step 2 — Set the build and run commands

In the service settings:

| Setting | Value |
|---------|-------|
| Build command | `uv sync` |
| Start / run command | `bash -c "PYTHONPATH=src uv run python -m app.ingest_all"` |
| Schedule | `0 2 * * 0` (Sundays at 2am — adjust to taste) |

`ingest_all.py` runs interests → donations → votes in sequence, each with their own checkpoint and run logging.

### Step 3 — Add environment variables

Copy these from your main app service in Railway (or set them directly):

```
DATABASE_URL        ← will automatically use internal URL when running on Railway
OPENAI_API_KEY
ANTHROPIC_API_KEY
```

### Step 4 — Deploy

Push to main or trigger a manual deploy. The cron service will run on schedule and each run will appear in `ingest_runs`.

**Cron schedule syntax reference:**

```
0 2 * * 0   → every Sunday at 2am
0 2 1 * *   → first day of every month at 2am
0 2 * * *   → every day at 2am
```

---

## After first data load — rebuild IVFFlat indexes

IVFFlat indexes must be rebuilt after the initial bulk load because centroids are learned from existing data (see [ADR 003](decisions/003-ivfflat-index.md)). Run the rebuild SQL from `schema-fixes.sql` once all four tables have data. Tracked in GitHub issue #15.
