---
title: Two-level answer cache + agent cost controls
status: Accepted
date: 2026-06-29
---

## Context

The conversational agent makes several Claude calls per question (the think→act loop),
and re-sends growing context each turn — so cost scales with traffic and conversation
length. We want to cut both the number of LLM calls and the cost of repeated questions.

## Decision

### Two-level cache (`cache.py`)

```
question → L1 Redis (exact match) → L2 Postgres (semantic match) → agent (LLM $$)
```

- **L1 Redis** — exact normalised-text match, 24h TTL. Instant, $0.
- **L2 Postgres + pgvector** — semantic match: embed the question, cosine-search past
  questions, hit if similarity ≥ 0.95 (within 7 days). Reuses the same embedding +
  cosine machinery as document retrieval. An L2 hit is promoted into L1.

**Only first-turn questions are cached.** Follow-ups depend on conversation context
("how much did *they* donate?"), so a text-keyed cache would serve wrong answers. The
signal is simple: a request with no incoming `thread_id` is a first turn.

**Graceful degradation:** every cache operation is wrapped — if Redis is down or
embedding fails, we log and fall through to the agent. The cache can never break `/ask`.

**Write path:** the cache *writes* (`query_cache` table, Redis keys), so it uses the
write `DATABASE_URL`, not the read-only role (consistent with ADR 013 — reads go
read-only, writes go through the write role).

### Agent cost controls (`agent.py`)

Prompt/config tweaks that cut *calls per question* (complementary to caching, which
cuts *repeat* questions):

1. **Parallel tool calls** — system prompt tells the agent to call all relevant tools
   at once rather than one think→act round each. Halves loops on cross-dataset questions.
2. **Reuse context** — don't re-search for records already retrieved earlier in the
   conversation.
3. **Recursion cap** (`recursion_limit = 12`) — bounds the worst case so a misbehaving
   run can't spiral into many LLM calls.

### Deferred: Anthropic prompt caching

Prompt caching only engages above a minimum prefix (~1024 tokens for Sonnet). Our
system prompt (~300 tokens) + 3 tool schemas (~400 tokens) is below that, so a cache
marker would be a no-op. Revisit when the static prefix grows (more tools, longer
prompt, or large fixed context). Adding ineffective code now would only mislead.

## Consequences

**Good:**
- Repeat/similar first-turn questions cost $0 and return in ~1–20ms
- Fewer LLM calls per question via parallel tools + context reuse
- Cache failures never affect correctness or availability

**Watch out for:**
- L1 (Redis) is ephemeral; L2 (Postgres) is the durable layer
- The 0.95 semantic threshold is a tuning knob — too low risks serving a near-but-wrong
  cached answer; too high reduces hit rate
- Cached answers can go stale after re-ingestion; the 7-day L2 window bounds staleness.
  Clear `query_cache` + Redis after a major data refresh if needed.

## Related

- [[013-database-security]] — read-only vs write roles
- [[010-vector-similarity-and-retrieval]] — the cosine search L2 reuses
- GitHub issue #12
