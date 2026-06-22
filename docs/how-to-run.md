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
SELECT id, script, started_at, finished_at, status, embedded, skipped, errors FROM ingest_runs ORDER BY started_at DESC;

-- Find interrupted runs (crashed mid-run)
SELECT * FROM ingest_runs WHERE finished_at IS NULL OR status = 'running' ORDER BY started_at DESC;
```

> **Railway UI note:** Keep queries on one line. Railway's query editor adds its own `LIMIT` clause — a `LIMIT` in your query causes a syntax error.

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

No Docker needed — Railway builds the Python environment automatically via nixpacks.

### Step 1 — Create the service

1. Go to your Railway project dashboard
2. Click **New Service → Empty Service**

### Step 2 — Connect the repo

In the service **Settings → Source**:
- Source Repo: `mahsa7haft/paidup-intelligence`
- Branch: `main`

### Step 3 — Configure deploy settings

In **Settings → Deploy**:

| Setting | Value |
|---------|-------|
| Custom Start Command | `PYTHONPATH=src python -m app.ingest_all` |
| Cron Schedule | `0 2 1 * *` |
| Restart Policy | **Never** |
| Serverless | **Off** (cron schedules require a non-serverless service) |

> **Teardown** controls when the old deployment is terminated after a new one starts. Leave at default — not relevant for a cron job.

`ingest_all.py` runs interests → donations → votes in sequence. Each has its own checkpoint file and run log entry.

### Step 4 — Add environment variables

In the service **Variables** tab, add:

```
DATABASE_URL
OPENAI_API_KEY
ANTHROPIC_API_KEY
THEYWORKFORYOU_API_KEY
```

Copy the values from your main app service (or your local `.env`).

### Step 5 — Deploy

Click **Deploy** or push to main. Railway will build the image with nixpacks. The cron service will sleep between runs and wake on schedule. Each run appears in `ingest_runs`.

**Cron schedule syntax reference:**

```
0 2 1 * *   → first day of every month at 2am  ← recommended for monthly data
0 2 * * 0   → every Sunday at 2am
0 2 * * *   → every day at 2am
```

---

## After first data load — rebuild IVFFlat indexes

IVFFlat indexes must be rebuilt after the initial bulk load because centroids are learned from existing data (see [ADR 003](decisions/003-ivfflat-index.md)). Run the rebuild SQL from `schema-fixes.sql` once all four tables have data. Tracked in GitHub issue #15.
