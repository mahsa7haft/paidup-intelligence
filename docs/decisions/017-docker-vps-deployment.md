# 017 — Docker image + Compose for VPS deployment

## Status
Accepted

## Context
Both apps deployed on Railway via Nixpacks. Nixpacks is convenient but
Railway-proprietary: the build is opaque, not reproducible locally, and can't be
moved to a plain VPS. We want to run PaidUp and PaidUp Intelligence on our own
host — for cost control (issue #38) and to avoid lock-in — and to build/test the
vector search stack against a local pgvector instance (issue #30).

## Decision
Ship a `Dockerfile` per app and a Compose stack for the VPS.

- **Base image:** the `ghcr.io/astral-sh/uv` images. `uv sync --frozen` gives
  reproducible, lockfile-pinned installs and the same image runs locally and in
  production. PaidUp pins Python 3.12 (scikit-learn / OpenCV / Pillow wheels);
  Intelligence tracks a newer Python since its dependency set is lighter.
- **Serving:** gunicorn, shell-form `CMD` so `$PORT` is expanded. Intelligence
  uses threads + a long timeout (agent requests hold the worker for the whole
  think→tool loop); PaidUp uses a couple of workers for CPU-bound card rendering.
- **Deployment topology:** one Compose file (`deploy/`) brings up both apps, two
  Postgres instances, and Redis. The two apps build from sibling repo checkouts
  (`~/paidup`, `~/paidup-intelligence`).
- **Two Postgres instances, not one.** Mixing PaidUp's OLTP with the vector
  tables' bulk writes and index builds filled the disk once
  (`engineering-maturity.md`). They stay separate images/volumes.
- **HTTPS is an opt-in profile.** Apps publish host ports for immediate IP-only
  access; a `tls`-profiled Caddy service adds automatic Let's Encrypt certs once
  real domains exist. This keeps first deploy trivial and defers DNS/TLS.
- **Redis is shared, logical DBs separated** — PaidUp on db 0, Intelligence on
  db 1 — so their keyspaces can't collide.

## Consequences
- Same artifact locally and in prod; no Railway-specific build step. `railway.toml`
  already builds from the Dockerfile, so Railway still works if we keep it.
- Operators must clone both repos as siblings; the dependency is documented in
  `DEPLOY.md` and the Compose header.
- IVFFlat indexes still have to be built after the first data load (ADR 003 /
  issue #15) — not automated by Compose. `DEPLOY.md` covers it.
- The `ghcr.io` base pull needs open egress at build time (fine on a VPS).
