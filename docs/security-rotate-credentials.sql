-- Credential rotation + compromise audit for intelligence-postgres (and paidup-postgres).
--
-- Use after any suspected leak of DATABASE_URL / DATABASE_URL_READONLY /
-- PAIDUP_DATABASE_URL (e.g. the Oct 2026 Railway incident — see
-- docs/incidents/2026-10-railway-credential-exposure.md).
--
-- Connect as the database owner/superuser:
--   psql "<owner connection string>" -f docs/security-rotate-credentials.sql
-- Sections 1 and 3 are read-only. Section 2 changes passwords — read it before running.

-- ───────────────────────────────────────────────────────────────────────────
-- 1. AUDIT — look for signs the attacker did more than read the env vars.
--    Anything here you don't recognise is a red flag.
-- ───────────────────────────────────────────────────────────────────────────

-- Every role that can log in. Expected: Railway's owner role (usually "postgres")
-- and intelligence_ro. Anything else is suspect.
SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, rolcanlogin, rolvaliduntil
FROM pg_roles
WHERE rolname NOT LIKE 'pg\_%'
ORDER BY rolname;

-- Who is connected right now, from where, as whom.
SELECT pid, usename, application_name, client_addr, backend_start, state,
       left(query, 80) AS query
FROM pg_stat_activity
WHERE datname = current_database() AND pid <> pg_backend_pid()
ORDER BY backend_start;

-- Tables. Expected: interests_vectors, party_donations_vectors, votes_vectors,
-- appg_vectors (+ donor_company_links, donor_tags on paidup-postgres).
SELECT schemaname, tablename, tableowner
FROM pg_tables
WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
ORDER BY schemaname, tablename;

-- Persistence tricks: functions, triggers and extensions you didn't create.
SELECT n.nspname, p.proname, pg_get_userbyid(p.proowner) AS owner
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname NOT IN ('pg_catalog', 'information_schema')
  AND NOT EXISTS (SELECT 1 FROM pg_depend d
                  WHERE d.objid = p.oid AND d.deptype = 'e');  -- skip extension-owned (pgvector)
SELECT tgname, tgrelid::regclass FROM pg_trigger WHERE NOT tgisinternal;
SELECT extname, extversion FROM pg_extension;  -- expected: plpgsql, vector

-- Row counts — compare against your last known ingestion totals. A big drop means
-- deletion; restore from backup (ADR 013) rather than re-ingest blind.
SELECT relname, n_live_tup, n_tup_del, last_autovacuum
FROM pg_stat_user_tables ORDER BY relname;

-- ───────────────────────────────────────────────────────────────────────────
-- 2. ROTATE — new passwords for every login role.
--
--    PREFER psql's \password: it hashes client-side, so the plaintext never
--    reaches server logs or ~/.psql_history:
--        \password intelligence_ro
--        \password postgres          -- or whatever the owner role is
--
--    RAILWAY OWNER ROLE: if your service variables reference Railway's managed
--    ${{Postgres.DATABASE_URL}}, changing the owner password by hand will NOT
--    update that variable and ingestion will break. Either regenerate the
--    password from the Railway Postgres service (Variables → regenerate), or
--    change it here AND update PGPASSWORD/DATABASE_URL on the Postgres service
--    to match, then redeploy dependents.
--
--    Fallback if \password isn't available (plaintext may be logged):
--        ALTER ROLE intelligence_ro PASSWORD '<new strong password>';
--    Generate one with:  openssl rand -base64 32 | tr -d '/+=' | cut -c1-32
-- ───────────────────────────────────────────────────────────────────────────

-- Drop any login role from the audit above that you did not create, e.g.:
--   REASSIGN OWNED BY suspect_role TO postgres;
--   DROP OWNED BY suspect_role;
--   DROP ROLE suspect_role;

-- ───────────────────────────────────────────────────────────────────────────
-- 3. KICK — end sessions still open on the old credentials. A changed password
--    does not disconnect anyone already logged in. Run AFTER updating Railway
--    variables and redeploying, or you'll drop your own services' fresh
--    connections too (they reconnect automatically, so this is safe to repeat).
-- ───────────────────────────────────────────────────────────────────────────
SELECT pg_terminate_backend(pid), usename, client_addr
FROM pg_stat_activity
WHERE datname = current_database()
  AND pid <> pg_backend_pid()
  AND backend_start < now() - interval '5 minutes';
