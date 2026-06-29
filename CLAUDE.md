# CLAUDE.md — paidup-intelligence

This file is for Claude Code. It documents run commands, architecture, and non-obvious design decisions.

## Run commands

```bash
# Install dependencies
uv sync

# Run ingestion scripts
PYTHONPATH=src uv run python -m app.ingest_interests
PYTHONPATH=src uv run python -m app.ingest_donations
PYTHONPATH=src uv run python -m app.ingest_votes
PYTHONPATH=src uv run python -m app.ingest_appgs

# Run the /ask API (once built)
PYTHONPATH=src uv run python -m app.main
# → http://localhost:5003

# Run tests
uv run pytest
```

## Architecture

See README.md for the full architecture diagram.

### Module responsibilities

| File | Responsibility |
|---|---|
| `main.py` | Flask routes for `/ask`. Orchestrates agent calls. |
| `parliament.py` | Parliament Members + Interests API client. Copied from PaidUp. |
| `electoral.py` | Electoral Commission donations API client. |
| `theyworkforyou.py` | TheyWorkForYou API — APPG memberships. |
| `database.py` | Postgres connection pool. Vector table upserts and similarity search. |
| `embeddings.py` | OpenAI embeddings client. Handles batching and smart re-embed (hash check). |
| `agent.py` | LangGraph agent — think → tool → execute → answer loop. |
| `ingest_interests.py` | Ingestion script: Parliament Register → interests_vectors. |
| `ingest_donations.py` | Ingestion script: Electoral Commission → party_donations_vectors. |
| `ingest_votes.py` | Ingestion script: Parliament votes → votes_vectors. |
| `ingest_appgs.py` | Ingestion script: TheyWorkForYou APPGs → appg_vectors. |

### Ingestion pattern

All four ingestion scripts follow the same pattern:

1. Fetch records from source API
2. Build a text chunk (`content`) for each record
3. `content_hash = sha256(content)`
4. Check hash against existing row via `ON CONFLICT (source_id)`
5. Only call OpenAI embeddings API when hash changed or record is new
6. Upsert into vector table with embedding + metadata

Metadata is enriched from PaidUp's shared `donor_company_links` and `donor_tags` tables where relevant (interests and donations).

### Smart re-embed

Embeddings are only regenerated when `content_hash` changes. This keeps monthly embedding cost near zero for stable datasets. See `docs/decisions/004-smart-reembed.md`.

### IVFFlat indexes

All four vector tables have IVFFlat cosine indexes. **Rebuild these after the first data load** — they need real data to learn centroids. See GitHub issue #15 and `docs/decisions/003-ivfflat-index.md`.

## Environment variables

| Variable | Required | Notes |
|---|---|---|
| `DATABASE_URL` | Yes | `intelligence-postgres` — vector tables. Write role; used by ingestion. |
| `DATABASE_URL_READONLY` | No | Read-only role (`intelligence_ro`) for the agent / MCP / `/ask` path. Falls back to `DATABASE_URL` if unset. See `docs/security-roles.sql` and ADR 013. |
| `PAIDUP_DATABASE_URL` | No | `paidup-postgres` — enrichment tables (`donor_company_links`, `donor_tags`). Falls back to `DATABASE_URL` if not set. Use Railway internal URL inside Railway. |
| `OPENAI_API_KEY` | Yes | For `text-embedding-3-small` embeddings |
| `ANTHROPIC_API_KEY` | Yes (agent only) | Claude Sonnet for the LangGraph agent |
| `THEYWORKFORYOU_API_KEY` | Yes (APPG ingestion) | Free at theyworkforyou.com/api/key |
| `REDIS_URL` | No | L1 query cache; Railway Redis plugin sets this |
| `PORT` | No | Defaults to 5003; Railway sets this automatically |

## Skills

Reusable analysis methods that load when a task matches their description.

| Skill | Path | Triggers on |
|-------|------|-------------|
| `conflict-of-interest-report` | `skills/conflict-of-interest-report/SKILL.md` | Who funds an MP, donor influence, conflicts of interest, vote alignment with donations |

Each skill is self-contained and portable to Claude.ai. See `docs/decisions/012-analysis-as-skill.md`.

## Related

- [PaidUp](../PaidUp) — `donor_company_links` and `donor_tags` tables used for metadata enrichment
- Fresh schema: `docs/schema.sql`
- Incremental fixes: `docs/schema-fixes.sql`
- Architecture decisions: `docs/decisions/`
- Engineering maturity roadmap: `docs/engineering-maturity.md`
