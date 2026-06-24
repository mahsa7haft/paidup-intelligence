---
title: Database security — least-privilege roles, backups, credential separation
status: Accepted
date: 2026-06-24
---

## Context

The question that prompted this: *can a database be deleted from a chat / agent?*

The answer is yes, in principle — not through the committed code, but through any
process that holds a full-privilege connection string. An audit of both repos
(June 2026) found the code itself is clean:

```
paidup-intelligence:
  .env tracked in git ............ no (gitignored) ✓
  destructive SQL in code ........ none ✓
  schema ops ..................... CREATE TABLE only ✓

PaidUp:
  .env tracked in git ............ no (gitignored) ✓
  destructive SQL in code ........ none ✓
  schema ops ..................... CREATE TABLE IF NOT EXISTS only ✓
  SQL injection (string SQL) ..... none — parameterized queries ✓
```

So the risk is not the code. It is **who holds credentials that can write or drop**:

1. **Claude Code / any agent with shell access** — can run `psql "$DATABASE_URL"`
   with whatever privileges that URL carries. If it's the Railway superuser, a
   destructive command is possible. Mitigated by permission mode (destructive Bash
   requires human approval) — but that's a behavioural control, not a hard one.
2. **The MCP search tools (not yet built, issues #6–9)** — will hold a live
   connection. If they connect as superuser, a bug or prompt injection through the
   public `/ask` or PaidUp `/analyze` endpoint could in theory issue a write.
3. **Railway's default role** — superuser. Every script currently uses this one
   all-powerful string for both reads and writes.

The crash (ADR 011) already proved we had no recovery path — PITR was not enabled,
so when the disk filled there was no way back. Deletion has the same gap.

## Decision

Defence in depth — make the dangerous action *impossible* where we can, *recoverable*
everywhere else.

### 1. Least-privilege roles (hard control)

The read path (agent, MCP tools, `/ask`) only needs `SELECT`. Give it a role that
cannot write or drop. Then a hallucinated `DROP TABLE` or an injected write is
rejected by Postgres itself — not relying on the model or the prompt behaving.

```sql
CREATE ROLE intelligence_ro LOGIN PASSWORD 'xxx';
GRANT CONNECT ON DATABASE railway TO intelligence_ro;
GRANT USAGE ON SCHEMA public TO intelligence_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO intelligence_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO intelligence_ro;
```

SQL lives in `docs/schema.sql` so it's part of every fresh setup.

| Path | Role | Privileges |
|---|---|---|
| Ingestion scripts | write role / `DATABASE_URL` | INSERT, UPDATE, SELECT — no DROP |
| Agent / MCP / `/ask` | `intelligence_ro` / `DATABASE_URL_READONLY` | SELECT only |
| One-off admin | superuser | full — used manually in psql, never in app env |

### 2. Backups (recovery control)

Enable Railway automated backups on **both** `paidup-postgres` and
`intelligence-postgres`. PaidUp's data (user-generated `analyses`) is not
re-derivable; intelligence vectors are, but re-ingestion costs hours. Backups are
the undo button the crash showed we lacked.

### 3. Credential separation

- The superuser connection string never lives in any app's `.env` or Railway
  service env. It is used only for manual admin in psql.
- App env vars carry only the least-privilege role they need.
- Never commit real credentials (the OpenAI key incident — already burned once).

### Invariant to preserve

Model output is never interpolated into SQL. All queries are parameterized
(psycopg2 `%s` placeholders). This is what keeps prompt injection through the LLM
from becoming SQL injection. Any new query path must keep this invariant.

## Consequences

**Good:**
- A compromised or hallucinating agent on the read path *cannot* delete data —
  enforced by Postgres, not by prompt or permission mode
- Backups give a recovery path the crash proved we needed
- Blast radius of any single leaked credential is bounded by its role

**Watch out for:**
- The read-only role must be created *before* the MCP tools are built, or they'll
  default to the superuser string — apply this ahead of issues #6–9
- `ALTER DEFAULT PRIVILEGES` only affects tables created by the role that runs it;
  if a new table is created by a different role, re-grant SELECT to `intelligence_ro`
- Same role split should be applied to PaidUp (read-mostly web role with writes
  scoped to `analyses` only) — tracked separately in the PaidUp repo

## Related

- [[011-disk-space-management]] — the crash that proved we had no recovery path
- GitHub issues #6–9 — MCP tools that must use the read-only role
