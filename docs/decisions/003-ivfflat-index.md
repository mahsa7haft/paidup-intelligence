---
title: Use IVFFlat (cosine) indexes, with lists sized to sqrt(n)
status: Accepted
date: 2026-06-19
---

## Context

pgvector offers two index types for approximate nearest-neighbour search:

- **IVFFlat** — clusters vectors into lists, searches only the nearest lists at query time. Fast build, good performance up to ~1M rows.
- **HNSW** — graph-based index, better recall and faster queries but uses significantly more memory and build time.

For cosine similarity (which matches how text embeddings are compared), the operator class is `vector_cosine_ops`.

The `lists` parameter controls how many clusters IVFFlat builds. Too few → slow queries (searches too many vectors). Too many → poor recall (misses neighbours in adjacent clusters). Rule of thumb: `lists = sqrt(row_count)`.

## Decision

Use IVFFlat with `vector_cosine_ops` on all four tables. Size `lists` to `sqrt(expected_row_count)`, rounded:

```
How IVFFlat works:

  Training phase (at CREATE INDEX time):
  ┌─────────────────────────────────────────────┐
  │  All vectors in the table                   │
  │  · · · · · · ·   ·  · ·                    │
  │    · · ·  ·   · ·  · ·  ·                  │
  │  IVFFlat groups them into N clusters (lists)│
  │   [list 1]   [list 2]   [list 3] ...        │
  └─────────────────────────────────────────────┘

  Query phase:
  question vector → find nearest lists → search only those lists → return top K
                                ↑
                         probes parameter (default 1)
                         higher probes = better recall, slower query

lists sizing per table:

  interests_vectors       ~20,000 rows  →  lists = 100  (√20k  ≈ 141)
  party_donations_vectors ~50,000 rows  →  lists = 100  (√50k  ≈ 224)
  votes_vectors          ~500,000 rows  →  lists = 700  (√500k ≈ 707) ← different
  appg_vectors             ~5,000 rows  →  lists = 100  (√5k   ≈  71)
```

| Table | Expected rows | lists |
|---|---|---|
| interests_vectors | ~20,000 | 100 |
| party_donations_vectors | ~50,000 | 100 |
| votes_vectors | ~500,000 | 700 |
| appg_vectors | ~5,000 | 100 |

HNSW is not used because the memory overhead is not justified at this scale on a shared Railway instance.

### Index build disk overhead

`CREATE INDEX` needs temporary disk space to sort and cluster vectors. The temp space
required scales roughly with `lists`:

```
temp_space ≈ (table_size_on_disk × lists) / sqrt(row_count)

Example — votes_vectors at 113,969 rows, ~700 MB on disk:

  lists = 200  →  (700 MB × 200) / √113,969  ≈  700 MB  (safe on 5 GB)
  lists = 336  →  (700 MB × 336) / √113,969  ≈ 1.2 GB   (safe on 5 GB, mathematically correct √113k ≈ 336)
  lists = 700  →  (700 MB × 700) / √113,969  ≈ 2.5 GB   (crashed old DB at 3.5 GB used — no headroom)
```

Rule: before running `CREATE INDEX`, verify at least **3× the expected temp space** is free:

```sql
-- Check free space before building index
SELECT
  pg_size_pretty(pg_database_size(current_database())) AS used,
  pg_size_pretty(4.5 * 1024^3 - pg_database_size(current_database())) AS approx_free;
```

**Post-incident note (June 2026):** The original `lists=700` for votes caused a disk-full
PANIC on the old `intelligence-postgres` (3.5 GB used, build needed ~2.5 GB temp, 5 GB
hard limit). Postgres could not write `postmaster.pid` and became unrecoverable.
Solution: separate `intelligence-postgres` from PaidUp's Postgres, run votes ingestion
first on an empty disk, build index with `lists=200` conservatively (search quality
still acceptable at this row count). See ADR 011.

## Consequences

**Good:**
- IVFFlat keeps memory usage low and build time fast — important for a single Railway Postgres instance
- Cosine similarity is the correct metric for normalised text embeddings from OpenAI

**Bad / watch out for:**
- **IVFFlat must be created after data is loaded.** The index learns centroids from existing rows. If created on an empty table the centroids are meaningless. Always load data first, then `CREATE INDEX` (or drop and recreate after first bulk load).
- If `votes_vectors` grows past ~2M rows, revisit whether HNSW or a separate pgvector instance makes sense
- At query time, set `SET ivfflat.probes = N` where N is 1–10% of `lists` to trade recall vs speed. Default probes = 1 (fastest, lower recall).
