---
title: Disk space management — monitoring, limits, and IVFFlat build overhead
status: Accepted
date: 2026-06-23
---

## Context

During the first full data load, the Railway Postgres disk filled completely
while building the IVFFlat index on `votes_vectors`. This caused a Postgres
PANIC, crashed the service, and required a full database rebuild.

Three failures contributed:

**1. Space estimate was wrong**

We estimated ~3GB needed for vectors and allocated 5GB, expecting 2GB headroom.
What we didn't account for: IVFFlat `CREATE INDEX` needs 2–3× the table size as
temporary workspace during the build.

```
votes_vectors actual size:     ~1.5 GB  (113k rows × 1536 dims × 4 bytes + content)
IVFFlat build temp workspace:  ~1.5 GB  (sorting + centroid computation)
WAL for the transaction:       ~0.5 GB
─────────────────────────────────────
Total needed for index build:  ~3.5 GB  (on top of the other three tables)
```

5GB was not enough. 8–10GB would have been safe.

**2. No disk monitoring**

There was no Railway alert set for disk usage. The disk filled silently
during a long-running index build with no warning.

**3. No pre-flight check**

The index build was run without first checking available disk space.
A simple check before `CREATE INDEX` would have caught this.

## Decision

### Before any large operation

Always check available disk first:

```sql
SELECT pg_size_pretty(pg_database_size(current_database())) AS db_size;

SELECT tablename, pg_size_pretty(pg_total_relation_size(tablename::text)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY pg_total_relation_size(tablename::text) DESC;
```

Rule: **never run `CREATE INDEX` with less than 3× the table size free.**

### IVFFlat build space requirement

| Table | Vector data | Index build temp | Total needed |
|-------|------------|-----------------|-------------|
| interests_vectors | ~300 MB | ~300 MB | ~600 MB |
| party_donations_vectors | ~500 MB | ~500 MB | ~1 GB |
| votes_vectors | ~1.5 GB | ~1.5 GB | ~3 GB |
| appg_vectors | ~50 MB | ~50 MB | ~100 MB |

**Minimum safe disk for full rebuild: 8 GB**

### lists sizing trade-off

Smaller `lists` = smaller index = less disk needed for build:

| lists | Build disk needed | Search quality |
|-------|-----------------|----------------|
| 700 | ~3 GB temp | Optimal |
| 200 | ~1 GB temp | Good |
| 50 | ~300 MB temp | Acceptable |

On a 5GB plan, use `lists = 50` for votes to stay safe. On 8GB+, use `lists = 200`.

### Set Railway disk alert

In Railway → Postgres service → Metrics → set an alert at **75% disk usage**.
This fires before the database is in danger, giving time to react.

### On a 5GB plan — skip votes IVFFlat

If disk is constrained, skip the votes IVFFlat index entirely. pgvector falls
back to exact nearest-neighbour search (sequential scan). Slower, but the API
works and no crash risk. Add the index later when storage is upgraded.

## Consequences

**Good:**
- Documented the real disk requirement for IVFFlat builds
- Pre-flight check prevents silent disk exhaustion
- Railway alert gives early warning before crisis

**Bad / watch out for:**
- IVFFlat build on votes requires a temporary spike to ~3.5 GB — plan for this
  before scheduling a rebuild
- `VACUUM` after large upsert runs can reclaim significant space — run it before
  index builds

## Post-incident retrospective

After the crash, we rebuilt from scratch on a separate `intelligence-postgres` and
discovered the real row counts and sizes were much smaller than estimated:

| Table | Estimated rows | Actual rows | Actual disk |
|---|---|---|---|
| votes_vectors | ~500,000 | 113,969 | ~739 MB |
| interests_vectors | ~20,000 | 717 | ~1 MB |
| party_donations_vectors | ~50,000 | TBD | TBD |
| appg_vectors | ~5,000 | TBD | TBD |

With actual row counts, the correct `lists` values (using `rows/1000` per pgvector docs)
are far smaller than originally planned — votes needs `lists=114`, not 700. The index
build with `lists=114` uses ~400 MB temp, well within the 5 GB limit.

**The crash was avoidable without separating the databases.** Using the correct
`lists` value from the start would have kept the build under 1 GB temp and the
single Postgres would have been fine. The two-DB split is still the right
architecture for isolation (a runaway ingestion job cannot affect PaidUp), but
it was a response to a crash that the correct `lists` value would have prevented.

## Related

- [[003-ivfflat-index]] — lists sizing and when to rebuild
- GitHub issue #15 — IVFFlat rebuild tracking
