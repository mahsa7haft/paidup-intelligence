# PaidUp Intelligence

AI-powered parliamentary intelligence — semantic search across UK Parliament data using RAG, MCP tools, and a LangGraph agent.

A companion service to [PaidUp](https://github.com/mahsa7haft/paidup), which surfaces individual MP donor cards. PaidUp Intelligence answers the reverse question: **"which MPs are funded by X?"** — and cross-references donors, votes, party funding, and APPG memberships to surface conflicts of interest that would take hours to find manually.

---

## What it answers

- *"Which MPs received money from fossil fuel companies?"*
- *"Which Reform MPs represent constituencies where Reform received crypto donations?"*
- *"Which MPs are in the fossil fuel APPG, voted against green energy bills, AND whose party received oil company donations?"*
- *"Are there any donors who give to both Labour and Conservative MPs?"*
- *"Which MPs declared new interests this week?"*

---

## Status

The full pipeline is built and working against real data: **ingest → vectors → MCP tools
→ LangGraph agent → conversational `/ask` chat → L1 cache.**

| Piece | Status |
|---|---|
| Ingestion (interests, donations, votes) | ✅ live |
| Ingestion (APPGs) | ⏸ deferred — TheyWorkForYou API cost; `appg_vectors` empty |
| IVFFlat indexes | ✅ built |
| MCP search tools (interests, donations, votes) | ✅ |
| LangGraph agent (think → act loop, cited answers) | ✅ |
| `/ask` conversational chat UI (memory, PaidUp-branded) | ✅ |
| L1 answer cache (Redis) + agent cost controls | ✅ |
| Read-only DB role for the agent path | ✅ |
| Deployment to Railway / VPS | ⬜ next |

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  INGESTION PIPELINE                  │
│  (scheduled cron jobs on Railway)                    │
│                                                      │
│  Parliament Register  → embed → pgvector          ✅ │
│  Electoral Commission → embed → pgvector          ✅ │
│  Voting records       → embed → pgvector          ✅ │
│  APPG memberships     → embed → pgvector           ⏸ │
└─────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│              POSTGRES + pgvector                     │
│                                                      │
│  interests_vectors       (Parliament Register)    ✅ │
│  party_donations_vectors (Electoral Commission)   ✅ │
│  votes_vectors           (voting records)         ✅ │
│  appg_vectors            (APPG memberships)         ⏸ │
└─────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│                  MCP TOOLS LAYER                     │
│                                                      │
│  search_interests()        → interests_vectors    ✅ │
│  search_party_donations()  → party_donations…     ✅ │
│  search_votes()            → votes_vectors        ✅ │
│  search_appgs()            → appg_vectors          ⏸ │
│  get_latest_declarations() → live Parliament API   ⬜ │
└─────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│                  AGENT LAYER                         │
│  LangGraph — think → act loop, conversational memory │
│                                                      │
│  START → think → tool? → execute → think → answer   │
└─────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│              /ask  chat UI  (Flask)                 │
│  Conversational Q&A → cited answers, L1-cached      │
│  PaidUp-branded; remembers the conversation          │
└─────────────────────────────────────────────────────┘
```

✅ live · ⏸ deferred (APPG — API cost) · ⬜ planned

---

## Data sources (Phase 1)

Record counts are **actuals** from the first full load (the original estimates were off
by 4–25×).

| Source | What it gives us | Records | Status |
|---|---|---|---|
| [Parliament Register of Members' Financial Interests](https://interests-api.parliament.uk) | Individual MP donations, gifts, paid jobs | 717 | ✅ live |
| [Electoral Commission](https://www.electoralcommission.org.uk) | Party donations and loans | 81,348 | ✅ live |
| [Parliament Members API](https://members-api.parliament.uk) | MP voting records (every division) | 113,969 | ✅ live |
| [TheyWorkForYou](https://www.theyworkforyou.com/api) | APPG memberships and roles | 0 | ⏸ deferred (API cost) |

**Phase 2 candidates:**
- **Lobbying / influence data** — UK Lobbying Register + ministers' meetings, to close
  the money-vs-influence gap ([#36](https://github.com/mahsa7haft/paidup-intelligence/issues/36)).
- **Hansard** parliamentary debates (~2M records).

---

## Caching & cost control

- **L1 Redis cache** — exact question match, 24h TTL, first-turn questions only. A repeat
  question returns in ~1ms for $0 (measured ~850× faster than a fresh agent run).
- **No semantic (L2) cache** — deliberately. In this domain topically-similar questions
  ("oil" vs "gas", "Labour" vs "Conservative") need *different* answers, so caching by
  question similarity risks serving the wrong one. L1 + precompute is the safe combo.
  See [ADR 016](docs/decisions/016-caching-and-cost-control.md).
- **Agent cost controls** — parallel tool calls, reuse-context, and a recursion cap to
  cut LLM calls per question.
- **Smart re-embed** — records are only re-embedded when their content changes (hash
  check), keeping monthly embedding cost near zero.

---

## Cost

Two independent cost axes:

- **LLM API (scales with traffic)** — embeddings (OpenAI) are negligible (~$0.19 for the
  whole initial load; near-$0/month after, thanks to smart re-embed). Claude Sonnet is
  the variable to watch per query, mitigated by the L1 cache + cost controls.
- **Infrastructure (scales with uptime)** — Railway bills RAM **per minute a service is
  up**, so the always-on stack (two Postgres + Redis + app) is **~$20/month** estimated —
  *not* the ~$3 earlier drafts quoted. RAM, not LLM, dominates.

Levers (serverless sleep, right-sizing, VPS) are tracked in
[#38](https://github.com/mahsa7haft/paidup-intelligence/issues/38). Full breakdown:
[docs/cost-analysis.md](docs/cost-analysis.md).

---

## Tech stack

| Layer | Technology |
|---|---|
| Web / API | Flask (`/ask` chat + `/health`) |
| Agent orchestration | LangGraph (think → act loop, conversational memory) |
| Tools | MCP server (FastMCP) + in-process LangChain tools — both over one `similarity_search` ([ADR 015](docs/decisions/015-agent-tools-direct-not-wire-mcp.md)) |
| LLM | Claude Sonnet (Anthropic) |
| Embeddings | text-embedding-3-small (OpenAI) |
| Vector store | pgvector on Postgres (separate `intelligence-postgres` instance) |
| Cache | Redis (L1, exact match) |
| Security | read-only DB role (`intelligence_ro`) on the agent path ([ADR 013](docs/decisions/013-database-security.md)) |
| Ingestion | Python + scheduled Railway cron jobs |
| Local dev / deployment | Docker + docker-compose; Railway (VPS option documented) |

---

## Running locally

You need [Docker](https://www.docker.com/products/docker-desktop/) and
[uv](https://github.com/astral-sh/uv) installed.

**1. Start a local Postgres + pgvector** (seeded automatically from `docs/schema.sql`):

```bash
docker compose up -d          # start in background
docker compose ps             # confirm STATUS = running (healthy)
```

This exposes the database on host port **5433** (not 5432, to avoid clashing with any
local Postgres). Tables are created on first boot but start empty.

**2. Point your `.env` at it** (copy from `.env.example` and set):

```
DATABASE_URL=postgresql://intelligence:localdev@localhost:5433/intelligence
OPENAI_API_KEY=sk-...
```

**3. Connect with psql** to poke around:

```bash
psql "postgresql://intelligence:localdev@localhost:5433/intelligence"
# then \dt to list tables
```

**4. Install deps and run things:**

```bash
uv sync                                            # install dependencies
uv run pytest                                      # run the test suite
PYTHONPATH=src uv run python -m app.ingest_interests   # run an ingestion script
```

**Stopping:**

```bash
docker compose down            # stop (data persists in the volume)
docker compose down -v         # stop AND wipe the data (fresh start)
```

> The local database starts empty. For development, insert a few rows for testing
> rather than re-ingesting the full datasets. See [docs/how-to-run.md](docs/how-to-run.md)
> for full details. The API / MCP server is in active development.

---

## Build order

1. ✅ Enable pgvector on Railway Postgres — [#1](https://github.com/mahsa7haft/paidup-intelligence/issues/1)
2. ✅ Ingest Parliament Register — [#2](https://github.com/mahsa7haft/paidup-intelligence/issues/2)
3. ✅ Ingest Electoral Commission — [#3](https://github.com/mahsa7haft/paidup-intelligence/issues/3)
4. ✅ Ingest voting records — [#4](https://github.com/mahsa7haft/paidup-intelligence/issues/4)
5. ⏸ Ingest APPG memberships — deferred (API cost) — [#5](https://github.com/mahsa7haft/paidup-intelligence/issues/5)
6. ✅ MCP search tools (interests, donations, votes) — [#6](https://github.com/mahsa7haft/paidup-intelligence/issues/6) [#7](https://github.com/mahsa7haft/paidup-intelligence/issues/7) [#8](https://github.com/mahsa7haft/paidup-intelligence/issues/8)
7. ✅ LangGraph agent — [#11](https://github.com/mahsa7haft/paidup-intelligence/issues/11)
8. ✅ L1 cache + cost controls — [#12](https://github.com/mahsa7haft/paidup-intelligence/issues/12)
9. ✅ `/ask` conversational chat UI — [#13](https://github.com/mahsa7haft/paidup-intelligence/issues/13)
10. ✅ Read-only DB role — [#28](https://github.com/mahsa7haft/paidup-intelligence/issues/28)
11. ⬜ Deploy (Railway / VPS) — [#30](https://github.com/mahsa7haft/paidup-intelligence/issues/30)

**Later:** `get_latest_declarations` live tool ([#10](https://github.com/mahsa7haft/paidup-intelligence/issues/10)), Grafana observability ([#27](https://github.com/mahsa7haft/paidup-intelligence/issues/27)), lobbying data ([#36](https://github.com/mahsa7haft/paidup-intelligence/issues/36)).

---

## Related

- [PaidUp](https://github.com/mahsa7haft/paidup) — the core MP donor lookup tool this service extends
