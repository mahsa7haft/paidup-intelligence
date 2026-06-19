---
title: Use text-embedding-3-small (OpenAI) at 1536 dimensions
status: Accepted
date: 2026-06-19
---

## Context

An embedding model is needed to convert text chunks into vectors for similarity search. The main options were:

- **text-embedding-3-small** (OpenAI) — 1536 dims, $0.02/1M tokens
- **text-embedding-3-large** (OpenAI) — 3072 dims, $0.13/1M tokens
- **text-embedding-ada-002** (OpenAI) — 1536 dims, $0.10/1M tokens (older)

## Decision

Use `text-embedding-3-small` at the default 1536 dimensions.

All four vector tables use `VECTOR(1536)` to match.

## Consequences

**Good:**
- 5× cheaper than `text-embedding-3-large` with only a small quality drop for this use case (structured parliamentary text, not nuanced prose)
- At Phase 1 scale (~575k chunks), initial embed cost ≈ $0.80; monthly refresh ≈ $0.10 with smart re-embed
- 1536 dims is a well-supported size for IVFFlat in pgvector

**Bad / watch out for:**
- If search quality is poor for complex multi-concept queries, try `text-embedding-3-large` on the votes table first (highest row count, most varied content)
- Changing dimensions later requires dropping and recreating all vector columns and re-embedding everything — a significant migration
