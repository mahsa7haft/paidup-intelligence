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

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                  INGESTION PIPELINE                  │
│  (scheduled cron jobs on Railway)                    │
│                                                      │
│  Parliament Register  → embed → pgvector             │
│  Electoral Commission → embed → pgvector             │
│  Voting records       → embed → pgvector             │
│  APPG memberships     → embed → pgvector             │
└─────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│              POSTGRES + pgvector                     │
│                                                      │
│  interests_vectors      (Parliament Register)        │
│  party_donations_vectors (Electoral Commission)      │
│  votes_vectors          (voting records)             │
│  appg_vectors           (APPG memberships)           │
└─────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│                  MCP TOOLS LAYER                     │
│                                                      │
│  search_interests()        → interests_vectors       │
│  search_party_donations()  → party_donations_vectors │
│  search_votes()            → votes_vectors           │
│  search_appgs()            → appg_vectors            │
│  get_latest_declarations() → live Parliament API     │
└─────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│                  AGENT LAYER                        │
│                    LangGraph                        │
│                                                     │
│  START → think → tool? → execute → think → answer   │
└─────────────────────────────────────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────┐
│              /ask  (PaidUp Core)                    │
│  Natural language question → streamed answer        │
│  with citations linking back to PaidUp MP pages     │
└─────────────────────────────────────────────────────┘
```

---

## Data sources (Phase 1)

| Source | What it gives us | Records | Refresh |
|---|---|---|---|
| [Parliament Register of Members' Financial Interests](https://interests-api.parliament.uk) | Individual MP donations, gifts, paid jobs | ~20,000 | 28 days |
| [Electoral Commission](https://www.electoralcommission.org.uk) | Party donations and loans | ~50,000 | Weekly |
| [Parliament Members API](https://members-api.parliament.uk) | MP voting records (every division) | ~500,000 | Real-time |
| [TheyWorkForYou](https://www.theyworkforyou.com/api) | APPG memberships and roles | ~5,000 | Monthly |

**Phase 2:** Hansard parliamentary debates (~2M records) — once Phase 1 pipeline is proven.

---

## Caching

Two-level cache to minimise Claude API costs:

- **L1 Redis** — exact question match, 24h TTL
- **L2 Postgres** — semantic question match (similar questions hit the same cache), 7-day TTL
- **Smart re-embed** — chunks are only re-embedded when their content changes (hash check), keeping monthly embedding costs near zero

---

## Cost (Phase 1, without Hansard)

| Item | Cost/month |
|---|---|
| Embedding refresh (smart re-embed) | ~$0.10 |
| pgvector storage (~3.5GB) | ~$0.63 |
| Claude Sonnet queries | ~$0.02/query |
| **Total at low traffic** | **~$3/month** |

Embedding model: `text-embedding-3-small` (OpenAI).

---

## Tech stack

| Layer | Technology |
|---|---|
| Agent orchestration | LangGraph |
| LLM | Claude Sonnet (Anthropic) |
| Embeddings | text-embedding-3-small (OpenAI) |
| Vector store | pgvector on Postgres |
| Cache | Redis (L1) + Postgres (L2) |
| Ingestion | Python + scheduled Railway cron jobs |
| Deployment | Railway |

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

1. Enable pgvector on Railway Postgres — [#1](https://github.com/mahsa7haft/paidup-intelligence/issues/1)
2. Ingest Parliament Register — [#2](https://github.com/mahsa7haft/paidup-intelligence/issues/2)
3. Ingest Electoral Commission — [#3](https://github.com/mahsa7haft/paidup-intelligence/issues/3)
4. Ingest voting records — [#4](https://github.com/mahsa7haft/paidup-intelligence/issues/4)
5. Ingest APPG memberships — [#5](https://github.com/mahsa7haft/paidup-intelligence/issues/5)
6. MCP tools (one per data source) — [#6](https://github.com/mahsa7haft/paidup-intelligence/issues/6) [#7](https://github.com/mahsa7haft/paidup-intelligence/issues/7) [#8](https://github.com/mahsa7haft/paidup-intelligence/issues/8) [#9](https://github.com/mahsa7haft/paidup-intelligence/issues/9) [#10](https://github.com/mahsa7haft/paidup-intelligence/issues/10)
7. LangGraph agent — [#11](https://github.com/mahsa7haft/paidup-intelligence/issues/11)
8. Two-level cache — [#12](https://github.com/mahsa7haft/paidup-intelligence/issues/12)
9. /ask page on PaidUp — [#13](https://github.com/mahsa7haft/paidup-intelligence/issues/13)

---

## Related

- [PaidUp](https://github.com/mahsa7haft/paidup) — the core MP donor lookup tool this service extends
