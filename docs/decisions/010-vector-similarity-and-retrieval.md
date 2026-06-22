---
title: Cosine similarity and IVFFlat for nearest-neighbour retrieval
status: Accepted
date: 2026-06-22
---

## Context

Once vectors are stored in pgvector, we need to retrieve the most semantically
similar records for a given query. Two decisions are required:

1. **Which similarity metric** — how to measure "closeness" between vectors
2. **Which index type** — how to make that search fast at scale

## Decision

### Cosine similarity

We use cosine similarity rather than Euclidean (L2) distance.

```
cosine similarity = (a · b) / (|a| × |b|)

      similar                       not similar

 b  /                          b  |
   / ← small angle               |  ← large angle
  /_____ a                        |_________ a

  score near 1.0                  score near 0.0
```

**Why direction, not distance:**

Embeddings encode meaning in the *direction* a vector points, not its length.
The magnitude is an artefact of how the model was trained and carries no
meaningful signal. Two sentences that mean the same thing point in the same
direction regardless of how long their vectors are.

Euclidean distance would penalise vectors of different lengths even if they
point the same way — giving worse results for paraphrases and synonyms.

**What "emerges" from training:**

Nobody defines what any dimension means. The model (`text-embedding-3-small`)
learned from hundreds of billions of words that concepts appearing in similar
contexts end up pointing in similar directions. This is a side effect of
training, not a design decision:

```
"donated to Conservative Party"
"gave money to the Tories"
"financial contribution to Conservative"
```

All three land near each other in 1536-dimensional space — which is why
semantic search works across paraphrases without keyword matching.

The famous example: `king − man + woman ≈ queen`. Nobody programmed that.
It falls out of the geometry.

### IVFFlat index

Without an index, every query scans all rows — O(n) comparisons per question.
At 500k votes that is too slow for a live API.

IVFFlat (Inverted File with Flat compression) pre-clusters all vectors at
build time. At query time only the nearest clusters are searched.

```
Build time:                             Query time:

all vectors                             query vector
      │                                       │
      ▼                                       ▼
 cluster   cluster   cluster            find nearest clusters (probes)
    1         2         3                      │
    │         │         │               search only those clusters
 centroid  centroid  centroid                  │
                                         return top-k results
```

**`lists` sizing — why sqrt(n):**

`lists` is the number of clusters. Too few → each cluster is huge and search
is slow. Too many → centroids are meaningless and accuracy drops.

`sqrt(row_count)` is the pgvector-recommended starting point:

| Table | Rows (approx) | lists |
|-------|--------------|-------|
| votes_vectors | ~500,000 | 700 |
| interests_vectors | ~50,000 | 100 |
| party_donations_vectors | ~80,000 | 100 |
| appg_vectors | ~5,000 | 100 |

**Why the index must be built after data load:**

Centroids are learned from the actual vectors during `CREATE INDEX`. Building
on an empty or near-empty table produces meaningless centroids — the index
exists but does nothing useful. See [[003-ivfflat-index]].

### 1536 dimensions

`text-embedding-3-small` uses 1536 dimensions — OpenAI's tradeoff between
quality and cost. See [[002-embedding-model]] for the full model comparison.

The key point: 1536 is not mathematically special. It is where OpenAI landed
for their "small" model. More dimensions = more capacity to represent subtle
meaning differences, but higher storage and slower search with diminishing
quality returns.

`text-embedding-3-small` supports **Matryoshka embeddings** — you can
truncate to 256 or 512 dimensions and retrieval still works, because the
model packs the most important information into the first dimensions. We
use the full 1536 since storage is not a concern at current scale.

If search quality proves poor for complex queries, the upgrade path is
`text-embedding-3-large` at 3072 dimensions (see [[002-embedding-model]]
consequences). This requires re-embedding everything and changing all
`VECTOR(1536)` columns to `VECTOR(3072)` — significant migration cost.

## Consequences

**Good:**
- Cosine similarity is the right metric for semantic meaning — results hold
  across synonyms and paraphrases, not just keyword matches
- IVFFlat makes retrieval fast enough for a live API at current scale
- 1536 dimensions is well-supported in pgvector with good community tooling

**Bad / watch out for:**
- IVFFlat is approximate — it can miss the true nearest neighbour if it lives
  in a cluster not searched. Use `SET ivfflat.probes = N` at query time to
  trade speed for accuracy (higher probes = more clusters searched)
- Centroids must be rebuilt if row count changes significantly (e.g. after
  a large new data source is added)

## Related

- [[002-embedding-model]] — why text-embedding-3-small, cost analysis, upgrade path to large
- [[003-ivfflat-index]] — index creation SQL and lists sizing detail
- GitHub issue #15 — IVFFlat rebuild after first data load
