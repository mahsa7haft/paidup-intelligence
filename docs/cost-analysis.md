# Cost Analysis — paidup-intelligence

Running costs broken down by source. All prices as of June 2026.

---

## OpenAI Embeddings — `text-embedding-3-small`

**Price:** $0.02 per 1M tokens  
**Model:** `text-embedding-3-small` (1536 dimensions)  
**Average tokens per record:** ~50 tokens (short text chunks)

### First-run embedding cost (full data load)

| Table | Records | Tokens (est.) | Cost |
|---|---|---|---|
| `votes_vectors` | 113,969 | 5.7M | $0.11 |
| `party_donations_vectors` | ~50,000 | 2.5M | $0.05 |
| `interests_vectors` | ~20,000 | 1.0M | $0.02 |
| `appg_vectors` | ~5,000 | 0.25M | <$0.01 |
| **Total first run** | **~190,000** | **~9.5M** | **~$0.19** |

### Monthly re-run cost (smart re-embed)

Most records don't change month-to-month. Only new or changed records are re-embedded.

| Table | Typical monthly change | Monthly cost |
|---|---|---|
| `votes_vectors` | ~2,000 new votes | ~$0.002 |
| `party_donations_vectors` | ~500 new donations | ~$0.001 |
| `interests_vectors` | ~100 new/updated | <$0.001 |
| `appg_vectors` | ~50 new/updated | <$0.001 |
| **Monthly total** | | **~$0.004** |

Smart re-embed (SHA-256 hash check) keeps monthly embedding cost near zero.
See `docs/decisions/004-smart-reembed.md`.

---

## Claude API — Agent queries

**Model:** Claude Sonnet 4.6  
**Price:** $3.00 per 1M input tokens / $15.00 per 1M output tokens

A typical `/ask` query:
- System prompt + retrieved context: ~2,000 tokens input
- Answer: ~500 tokens output
- Cost per query: ~$0.006 + $0.007 = **~$0.013 per query**

At 100 queries/month: ~$1.30  
At 1,000 queries/month: ~$13.00

---

## Railway Infrastructure (real numbers, June 2026)

⚠️ **Earlier drafts of this doc quoted ~$2–3/month. That was wrong** — it only counted
embeddings + storage, not RAM. Railway's actual estimate for the running stack is
**~$20/month**. Recording the truth here so we never quote the optimistic figure again.

### How Railway bills — and why RAM dominates

Railway charges **per minute of usage**, mostly for **RAM held while a service is up**:

```
RAM cost = GB held × minutes running × $0.000231 / GB / minute
```

The "GB" figures in the Railway dashboard are **GB-minutes** (memory × time), not
capacity — a scary-looking `24,635 GB` is just `24,635 GB-minutes` = ~$5.70. The dollar
column is the only thing that matters.

The key consequence: **an idle always-on service still costs money** — it holds RAM
every minute whether or not anyone uses it. RAM, not LLM calls or storage, is the bill.

### The running stack (~$20/month estimated)

| Service | Always-on? | Notes |
|---|---|---|
| PaidUp app | yes | RAM 24/7 — the live product |
| `paidup-postgres` | yes | RAM 24/7 |
| `intelligence-postgres` | yes | RAM 24/7 — holds ingested vectors |
| PaidUp-Redis | yes | small |
| Ingest-Intelligence-Cron | **no** | $0 — runs then exits (the ideal pattern) |

Two structural cost facts:
- **Two Postgres instances** (split after the disk crash) roughly *doubles* DB RAM —
  ~$4–5/mo for failure isolation. The crash was avoidable (wrong `lists` value), so this
  is an insurance premium you *could* drop by re-merging — at the cost of migration work
  and shared-failure risk.
- **When intelligence goes fully live** (deploy `/ask` app + a prod Redis), expect
  ~$25–30/mo unless the levers below are applied.

### Keeping it low — the levers

| Lever | Effect |
|---|---|
| **Serverless / sleep on the `/ask` app** | App costs ~$0 when no traffic; wakes on request. Ideal for a testing phase. Do NOT apply to the cron or DBs. |
| **Right-size RAM** per service | Railway over-allocates; capping cuts GB-minutes directly |
| **$5/month free credit** | Offsets ~$5 of the bill |
| **Pre-launch** | Only `intelligence-postgres` (~$5/mo) runs for intelligence; app/Redis are $0 until deployed |
| Re-merge two Postgres → one | Saves ~$4–5/mo, loses isolation (decide later) |

The honest baseline: an always-on multi-service stack costs **~$15–30/month**, not $2.
Tracked in GitHub issue #38.

---

## IVFFlat Index Build — one-time cost

Index builds run on Railway's own compute — no extra charge beyond the Railway plan.  
The cost is time and disk headroom, not money.

```
Index build time estimates (Railway Hobby, 1 vCPU):

  interests_vectors       ~20k rows,  lists=100  →  ~10 seconds
  party_donations_vectors ~50k rows,  lists=100  →  ~20 seconds
  votes_vectors          ~114k rows,  lists=200  →  ~60 seconds
  appg_vectors             ~5k rows,  lists=100  →   ~5 seconds
```

Disk headroom needed during build — see `docs/decisions/003-ivfflat-index.md`
for the full formula.

---

## Total monthly cost summary

| Category | Cost |
|---|---|
| OpenAI embeddings (re-runs) | ~$0.004 |
| Claude API (100 queries) | ~$1.30 |
| Railway infrastructure (real estimate) | **~$20** (heading to ~$25–30 when fully live) |
| **Total** | **~$20–$30/month** |

First-time setup adds a one-off ~$0.19 for the full initial data load.

**The cost lesson:** the variable that grows with *traffic* is the LLM API (mitigated by
the L1 cache + cost controls, ADR 016). The variable that grows with *uptime* is Railway
RAM (mitigated by serverless sleep + right-sizing, issue #38). Infra is the bigger,
steadier number — don't quote "$2".

---

## Cost levers

**To reduce embedding cost:** Smart re-embed already handles this. No action needed.

**To reduce Claude API cost:** Switch to `claude-haiku-4-5` for simple factual queries,
reserve Sonnet for complex cross-source analysis. Estimated 10× cheaper per simple query.

**To reduce infrastructure cost:** The two-Postgres split is the current minimum safe
architecture. Merging back to one Postgres risks repeating the June 2026 disk-full incident.

**Redis query cache:** Caches identical `/ask` queries for 1 hour. Worth enabling once
query volume justifies it — saves Claude API cost on repeated questions.
