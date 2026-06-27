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
  │   · · · · · · ·   ·  · ·                    │
  │   · · ·  ·   · ·  · ·  ·                    │
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

`CREATE INDEX` needs temporary disk space to run k-means clustering across all vectors.
Postgres must make a working copy of the data and iterate over it. The observed rule of
thumb from this project:

```
temp_space ≈ 1–2× table size on disk
```

Higher `lists` means more k-means iterations, which increases both time and temp writes.
The relationship is approximately linear with `lists` relative to `sqrt(row_count)`:

```
temp_space ≈ (table_size_on_disk × lists) / sqrt(row_count)

All four tables — estimated disk size and index build overhead:

  Table                    Rows     Disk size   lists   Temp space   Peak during build
  ─────────────────────────────────────────────────────────────────────────────────────
  votes_vectors          113,969    ~700 MB      200     ~415 MB      ~1.1 GB
  party_donations_vectors ~50,000   ~300 MB      100     ~134 MB      ~434 MB
  interests_vectors       ~20,000   ~120 MB      100     ~85 MB       ~205 MB
  appg_vectors             ~5,000    ~30 MB      100     ~42 MB        ~72 MB

  votes at lists=700 (crashed):  (700 × 700) / √113,969 ≈ 1.45 GB temp
  → at 3.5 GB already used on a 5 GB disk, left only 1.5 GB free — not enough
```

### Safe sequential build order on intelligence-postgres (5 GB limit)

Building one table at a time, checking disk between each step:

```
Step  Action                          Disk used after   Peak during   Free (of 5 GB)
────────────────────────────────────────────────────────────────────────────────────
 0    votes data loaded (current)       ~700 MB           —           ~4.3 GB
 1    BUILD votes index (lists=200)     ~750 MB         ~1.1 GB       ~3.9 GB  ✓
 2    Load interests data               ~870 MB           —           ~3.9 GB
 3    BUILD interests index (lists=100) ~880 MB         ~1.1 GB       ~3.9 GB  ✓
 4    Load donations data              ~1.18 GB           —           ~3.8 GB
 5    BUILD donations index (lists=100)~1.20 GB         ~1.6 GB       ~3.4 GB  ✓
 6    Load appgs data                  ~1.23 GB           —           ~3.8 GB
 7    BUILD appgs index (lists=100)    ~1.24 GB         ~1.3 GB       ~3.7 GB  ✓

Final state: ~1.24 GB used / 5 GB  →  75% headroom remaining
```

Peak disk usage across all builds: ~1.6 GB — well within the 5 GB limit.
**Always run the disk check query between steps:**

```sql
SELECT
  pg_size_pretty(pg_database_size(current_database())) AS used,
  pg_size_pretty(4.5 * 1024::bigint^3 - pg_database_size(current_database())) AS approx_free;
```

**Post-incident note (June 2026):** The original `lists=700` for votes caused a disk-full
PANIC on the old `intelligence-postgres` (3.5 GB used, build needed ~1.45 GB temp, 5 GB
hard limit — only 1.5 GB free, not the 3× safety margin). Postgres could not write
`postmaster.pid` and became unrecoverable. Solution: separate `intelligence-postgres`
from PaidUp's Postgres, run votes ingestion first on an empty disk, build index with
`lists=200` conservatively. See ADR 011.

## Consequences

**Good:**
- IVFFlat keeps memory usage low and build time fast — important for a single Railway Postgres instance
- Cosine similarity is the correct metric for normalised text embeddings from OpenAI

**Bad / watch out for:**
- **IVFFlat must be created after data is loaded.** The index learns centroids from existing rows. If created on an empty table the centroids are meaningless. Always load data first, then `CREATE INDEX` (or drop and recreate after first bulk load).
- If `votes_vectors` grows past ~2M rows, revisit whether HNSW or a separate pgvector instance makes sense
- At query time, set `SET ivfflat.probes = N` where N is 1–10% of `lists` to trade recall vs speed. Default probes = 1 (fastest, lower recall).
