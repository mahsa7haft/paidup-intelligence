-- Read-only role for the query / agent / MCP path on intelligence-postgres.
--
-- The agent and MCP tools only ever SELECT, so they connect as this role. Then a bug,
-- a hallucinated query, or prompt injection through /ask physically cannot write or
-- drop anything — Postgres rejects it. See ADR 013.
--
-- Run ONCE as the database owner/superuser on each instance (prod, and locally):
--   psql "postgresql://<owner>@<host>/<db>" -f docs/security-roles.sql
--
-- Then build a connection string for intelligence_ro and set it as DATABASE_URL_READONLY
-- on the app/agent service. Ingestion keeps using the write DATABASE_URL.

-- 1. Create the role. REPLACE 'CHANGE_ME' with a strong password.
CREATE ROLE intelligence_ro LOGIN PASSWORD 'CHANGE_ME';

-- 2. Read-only access to current AND future tables in the public schema.
GRANT USAGE  ON SCHEMA public TO intelligence_ro;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO intelligence_ro;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO intelligence_ro;

-- Note: CONNECT is granted to PUBLIC by default, so intelligence_ro can already
-- connect. If you have revoked PUBLIC CONNECT, also run (with your real db name):
--   GRANT CONNECT ON DATABASE <your_database> TO intelligence_ro;
--
-- ALTER DEFAULT PRIVILEGES only covers tables created by the role that runs this
-- script (the owner). If a new table is later created by a different role, re-run:
--   GRANT SELECT ON ALL TABLES IN SCHEMA public TO intelligence_ro;
