---
title: Containerization — docker-compose for local dev, Dockerfile for deploy
status: Accepted
date: 2026-06-29
---

## Context

Development hit Railway directly, and local setup depended on having the right Postgres
+ pgvector installed on each machine (we lost time to a `libpq` PATH issue). There was
no isolated, reproducible local environment, and no way to develop the upcoming MCP
layer without touching production data.

## Decision

Containerize in two parts, built in the order each becomes meaningful.

### 1. `docker-compose.yml` — local development (now)

A `db` service using `pgvector/pgvector:pg16` (Postgres + pgvector prebuilt), seeded
from `docs/schema.sql` via the image's `/docker-entrypoint-initdb.d/` hook. Data
persists in a named volume; exposed on host port **5433** to avoid clashing with any
local Postgres.

This gives an isolated, reproducible local database — same engine and schema as
production, empty and safe to break — which is the prerequisite for building and
testing the MCP search tools locally.

### 2. `Dockerfile` — deployment (after the server exists)

A single application image, built once, used for every role (API server, ingest cron,
MCP server) by overriding the start command — the "one image, many roles" pattern.
Railway switches from Nixpacks to building this Dockerfile for local/prod parity.

**Why deferred:** a deployment Dockerfile's `CMD` runs the app. Until the API/MCP
server code exists, there is nothing to run — a Dockerfile written now would only
crash-loop. We build the server first, then containerize it. The local `db` service
(what we actually need today) does not depend on the Dockerfile.

## Consequences

**Good:**
- Reproducible local DB in one command (`docker compose up`); no per-machine installs
- MCP layer can be developed against a local, isolated, throwaway database
- One image for all roles keeps dependencies in sync and matches how Railway already
  runs the API and cron services

**Watch out for:**
- Local DB starts empty — seed a few rows for testing; don't re-ingest full datasets
- `docker compose down -v` wipes the volume (intended, for a clean slate)
- When the Dockerfile lands, keep its layer order deps-before-code so rebuilds stay
  cache-fast

## Related

- [[001-vector-store]] / `docs/schema.sql` — what the local db is seeded with
- Learning notes: Docker, Images & Containers (personal knowledge base)
- GitHub issue #30
