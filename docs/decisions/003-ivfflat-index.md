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

| Table | Expected rows | lists |
|---|---|---|
| interests_vectors | ~20,000 | 100 |
| party_donations_vectors | ~50,000 | 100 |
| votes_vectors | ~500,000 | 700 |
| appg_vectors | ~5,000 | 100 |

HNSW is not used because the memory overhead is not justified at this scale on a shared Railway instance.

## Consequences

**Good:**
- IVFFlat keeps memory usage low and build time fast — important for a single Railway Postgres instance
- Cosine similarity is the correct metric for normalised text embeddings from OpenAI

**Bad / watch out for:**
- **IVFFlat must be created after data is loaded.** The index learns centroids from existing rows. If created on an empty table the centroids are meaningless. Always load data first, then `CREATE INDEX` (or drop and recreate after first bulk load).
- If `votes_vectors` grows past ~2M rows, revisit whether HNSW or a separate pgvector instance makes sense
- At query time, set `SET ivfflat.probes = N` where N is 1–10% of `lists` to trade recall vs speed. Default probes = 1 (fastest, lower recall).
