---
title: Answer caching (L1 only) and agent cost controls
status: Accepted
date: 2026-06-29
---

## Context

The conversational agent makes several Claude calls per question (the think→act loop),
and re-sends the growing conversation each turn — so cost scales with both traffic and
conversation length. We want to cut the number of LLM calls and the cost of repeated
questions, without ever risking a wrong answer or breaking `/ask`.

## Decision

A layered set of cost controls. Each is cheap and independent.

### 1. L1 answer cache (Redis) — exact match

`cache.py` stores answers in Redis keyed by the **normalised** question (lowercased,
whitespace-collapsed), with a 24h TTL.

```
question → L1 Redis (exact match) → hit: return cached answer ($0, ~1ms)
                                   → miss: run agent, then store
```

- **First-turn questions only.** Follow-ups depend on conversation context
  ("how much did *they* donate?"), so a text-keyed cache would serve wrong answers.
  The signal: a request with no incoming `thread_id` is a first turn.
- **Graceful degradation.** Every cache op is wrapped — if Redis is down, lookups miss
  and stores no-op. The cache can never break `/ask`.
- **Write path.** Redis only; no DB writes.

Verified live: an identical question went 19.7s → 0.023s (~850×), $0 on the repeat.

### 2. NO semantic (L2) cache — deliberately

We built and then **removed** an L2 pgvector "semantic" cache (match questions by
embedding similarity). It does not fit this domain:

- **Topical similarity ≠ same answer.** "oil" vs "gas" funded MPs, or "Labour" vs
  "Conservative" donors, score ~0.93–0.95 cosine but need *different* answers. To stay
  correct the threshold must sit so high it barely fires beyond exact matches — which
  L1 already handles (and L1 normalises case/whitespace).
- **It costs on every miss.** An L2 lookup embeds the question (an OpenAI call) just to
  do the cosine search, so common new questions pay extra to catch a few rare safe hits.
- **The safe band is entangled with the dangerous one.** Same-entity rephrasings
  ("who funds Labour?" / "Labour's donors?") are safe, but indistinguishable by score
  from different-entity look-alikes. You can't tell which band a pair is in from the
  number alone.

**Conclusion:** L1 (exact) + precompute is the safe, high-value combo. Semantic caching
on *questions* is treacherous in a domain where the discriminating entity, not the
topic, drives the answer. Measured example: two genuine paraphrases scored 0.9082 —
close, but we will not serve one's answer for the other.

### 3. Agent cost controls (`agent.py`)

Prompt/config tweaks that cut *calls per question* (complementary to caching, which
cuts *repeat* questions):

- **Parallel tool calls.** The system prompt tells the agent to call all relevant tools
  at once rather than one think→act round each. On a 3-tool question this is ~2 LLM
  calls instead of ~4 — and each call re-sends less context. Only safe for *independent*
  tools (ours are); Claude still serialises when one tool needs another's output.
- **Reuse context.** Don't re-search for records already retrieved earlier in the
  conversation.
- **Recursion cap** (`recursion_limit = 12`). Bounds the worst case so a misbehaving run
  can't spiral into many LLM calls.

### 4. Precompute hot answers (recommended, not yet built)

Caching is *reactive* — the first asker still waits. **Precompute** is *proactive*:
run the known-popular questions (e.g. the example chips on the chat page) on a schedule
and warm L1 ahead of time, so even the first user gets an instant answer. The natural
trigger is right after the monthly ingestion cron (answers go stale after re-ingest).
Tracked as follow-up.

### 5. Deferred: Anthropic prompt caching

Prompt caching only engages above a minimum prefix (~1024 tokens for Sonnet). Our
system prompt (~300 tokens) + 3 tool schemas (~400 tokens) is below that, so a cache
marker would be a no-op. Revisit if the static prefix grows. Adding ineffective code now
would only mislead.

## Cost levers summary

| Lever | Cuts | Status |
|---|---|---|
| L1 Redis cache | repeat first-turn questions → $0 | done |
| Parallel tool calls | LLM calls per question | done |
| Reuse context | redundant searches on follow-ups | done |
| Recursion cap | worst-case runaway loops | done |
| Precompute hot answers | first-asker wait on popular Qs | follow-up |
| Anthropic prompt caching | static-prefix token cost | deferred (prefix too small) |
| Model tiering (Haiku/Sonnet) | per-call cost on simple Qs | future |
| Semantic (L2) cache | — | rejected (wrong-answer risk) |

## Consequences

**Good:**
- Repeat first-turn questions cost $0 and return in ~1ms (L1)
- Fewer LLM calls per question (parallel tools, context reuse, recursion cap)
- No semantic-collision risk; cache failures never affect correctness or availability
- Simpler system — no query_cache table, no embedding-on-miss

**Watch out for:**
- L1 (Redis) is ephemeral — cleared on restart; that's acceptable for a cost cache
- Cached answers go stale after re-ingestion; the 24h TTL bounds it. Flush Redis after a
  major data refresh, and re-warm via precompute.

## Related

- [[013-database-security]] — read-only vs write roles
- `docs/cost-analysis.md` — running-cost breakdown
- GitHub issue #12
