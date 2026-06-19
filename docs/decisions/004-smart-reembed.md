---
title: Use content_hash for smart re-embed (skip unchanged chunks)
status: Accepted
date: 2026-06-19
---

## Context

All four ingestion pipelines run on a schedule. On each run they fetch fresh data from their source APIs and need to upsert into the vector tables. Re-embedding every row on every run would cost ~$0.80/run and make the "~$0.10/month" estimate impossible.

## Decision

Each vector table has a `content_hash TEXT` column. During ingestion:

1. Build the text chunk that will be embedded (`content`)
2. Hash it: `content_hash = sha256(content)`
3. Upsert with `ON CONFLICT (source_id) DO UPDATE SET ... WHERE content_hash != EXCLUDED.content_hash`
4. Only call the OpenAI embeddings API for rows where the hash changed (or is new)

This means unchanged records are touched with a cheap hash comparison, not an expensive API call.

## Consequences

**Good:**
- Embedding cost stays near zero for stable datasets (MP interests, APPG memberships change slowly)
- The `source_id UNIQUE` constraint is the deduplication key; `content_hash` is purely the change-detection signal

**Bad / watch out for:**
- The hash must cover exactly the text passed to the embedding model — if the `content` construction logic changes, all hashes become stale and a full re-embed is triggered. This is intentional and correct behaviour.
- `content_hash` is nullable at column creation time so the ALTER TABLE can run on existing tables without backfilling. It will be populated on first ingestion run.
