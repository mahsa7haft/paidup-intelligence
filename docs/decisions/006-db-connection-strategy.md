---
title: Use short-lived DB connections per operation in long-running ingestion scripts
status: Accepted
date: 2026-06-21
---

## Context

The ingestion scripts run for extended periods (15 min for donations, 2-3 hrs for
votes). The original implementation opened one Postgres connection at startup and
kept it open for the entire run.

Railway's managed Postgres closes connections that have been idle for too long.
During ingestion, the connection sits idle while the script is fetching from
external APIs and waiting for OpenAI embeddings — which can take several minutes
per page. Railway terminated the connection mid-run, causing:

```
psycopg2.OperationalError: server closed the connection unexpectedly
```

This happened at ~6,800 records into the donations run (after the connection had
been idle during ~2 minutes of API fetching + embedding).

## Decision

Use short-lived connections — open a connection, do the database operation,
close it immediately. Never hold a connection open while doing non-DB work.

```
BEFORE — one long-lived connection:

  connect ──────────────────────────────────────────────────── close
           │ fetch API │ embed  │ upsert │ fetch API │ embed  │ upsert
           │  ~2 min   │  ~30s  │ instant│  ~2 min   │  ~30s  │ instant
                       ↑
               Railway kills idle connection here
               psycopg2.OperationalError: server closed the connection unexpectedly


AFTER — short-lived connections:

  setup:    connect → load hashes → close

  per page: [fetch API — no connection]
                │
                ▼
            [embed via OpenAI — no connection]
                │
                ▼
            connect → upsert → commit → close
                │
                ▼
            [fetch next page — no connection]
                ...

  Connection is only open for milliseconds → Railway never sees it as idle.
```

Pattern applied in all three ingestion scripts:

```python
def _connect(db_url: str):
    conn = psycopg2.connect(db_url)
    register_vector(conn)
    return conn

# Setup: connect → load enrichment + hashes → close
conn = _connect(db_url)
existing = _fetch_existing_hashes(conn)
conn.close()

# Per page/MP: connect → upsert → close
conn = _connect(db_url)
with conn.cursor() as cur:
    _upsert(cur, rows)
conn.commit()
conn.close()
```

## Consequences

**Good:**
- Connections are never idle — Railway has nothing to kill
- Safe to run scripts locally against the public Railway URL or inside Railway

**Bad / watch out for:**
- Slightly more connection overhead (one connect/close per page)
- At 1,628 pages for donations, that's 1,628 connects — acceptable, not a bottleneck
- If Railway ever adds connection limits per minute, revisit using a connection pool
  with keepalive instead
