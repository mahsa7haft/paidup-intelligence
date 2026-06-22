---
title: Use pgvector on existing Railway Postgres instead of a dedicated vector DB
status: Accepted
date: 2026-06-19
---

## Context

The project needs a vector store for semantic search across four datasets (MP interests, party donations, votes, APPG memberships). Options considered:

- **Pinecone / Weaviate / Qdrant** — managed vector DBs, purpose-built for similarity search
- **pgvector on existing Postgres** — extension on the Railway Postgres instance already used by PaidUp core

## Decision

Use pgvector on the existing Railway Postgres.

```
┌─────────────────┐     ┌──────────────────────────┐
│     PaidUp      │     │   paidup-intelligence     │
│   (Flask app)   │     │  (ingestion + agent)      │
└────────┬────────┘     └────────────┬──────────────┘
         │                           │
         └─────────────┬─────────────┘
                       ▼
          ┌────────────────────────┐
          │   Railway Postgres     │
          │                        │
          │  analyses              │ ← PaidUp
          │  donor_company_links   │ ← PaidUp (shared)
          │  donor_tags            │ ← PaidUp (shared)
          │  ─────────────────     │
          │  interests_vectors     │ ← paidup-intelligence
          │  party_donations_vectors│ ← paidup-intelligence
          │  votes_vectors         │ ← paidup-intelligence
          │  appg_vectors          │ ← paidup-intelligence
          └────────────────────────┘
```

## Consequences

**Good:**
- No extra service to run, pay for, or keep in sync — one Postgres connection string covers relational queries and vector search
- Joins between vector results and relational data (e.g. MP metadata) are trivial SQL, no cross-service calls
- Railway Postgres is already provisioned; pgvector is enabled with a single `CREATE EXTENSION`
- At Phase 1 scale (~575k total rows across four tables) IVFFlat performs well within Postgres

**Bad / watch out for:**
- At very large scale (millions of rows, high QPS) a dedicated vector DB would outperform pgvector — revisit if Hansard phase pushes past ~5M rows or query latency degrades
- IVFFlat indexes must be rebuilt after bulk data loads (centroids are learned from existing data — see ADR 003)
