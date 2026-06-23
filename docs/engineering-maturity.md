# Engineering Maturity Roadmap

Things that are intentionally deferred for MVP but must be addressed before
going multi-environment, multi-developer, or production at scale.

---

## Database

### Migrations
**Current:** Single `schema-fixes.sql` with `IF NOT EXISTS` guards.
**Needed:** Versioned migrations (Alembic for Python) so each environment
knows exactly what schema version it's on and new changes apply cleanly.

**When:** Before adding a staging environment or a second developer.

---

## Infrastructure

### Separate databases per concern
**Current:** PaidUp and paidup-intelligence share one Railway Postgres.
**Needed:** Separate instances — one for PaidUp (OLTP), one for vector tables
(bulk writes, large rows, index builds). Mixing them caused a disk full crash.

**When:** Already doing this — intelligence-postgres being set up now.

### Disk monitoring and alerts
**Current:** No alerts. Disk filled silently during IVFFlat index build.
**Needed:** Railway alert at 75% disk usage on both Postgres instances.

**When:** Immediately — set this up on every new Postgres.

### Pre-flight disk check before index builds
**Current:** Manual check recommended in ADR 011.
**Needed:** Automated check in ingestion scripts before `CREATE INDEX`.

**When:** Before next index rebuild cycle.

---

## Testing

### Integration tests
**Current:** Unit tests only (pure functions, mocked DB).
**Needed:** Integration tests that run against a real test database to catch
upsert logic, schema mismatches, and connection handling bugs.

**When:** Before adding a second developer or staging environment.

---

## Observability

### Structured logging
**Current:** `logging.basicConfig` with plain text output.
**Needed:** Structured JSON logs (e.g. structlog) so logs are queryable in
Railway or a log aggregator.

**When:** Before production traffic.

### Run duration tracking
**Current:** `ingest_runs` tracks embedded/skipped counts and timestamps.
**Needed:** Per-MP and per-page timing so slow API calls are visible.

**When:** If ingestion runs start taking longer than expected.

---

## Security

### Secret rotation process
**Current:** Manual — rotate in platform dashboard, update `.env` locally.
**Needed:** Documented rotation runbook. One key was accidentally committed
to git history (see `.env.example` incident).

**When:** Before any team members are added.

### Environment variable audit
**Current:** All envs set manually per service in Railway.
**Needed:** Documented list of which services need which variables, audited
on each new deployment.

**When:** Before staging environment.

---

## Deployment

### Staging environment
**Current:** Single environment (production on Railway).
**Needed:** Staging environment to test ingestion changes before they run
against production data.

**When:** Before the agent/API is user-facing.

### CI/CD
**Current:** Tests run manually (`uv run pytest`).
**Needed:** GitHub Actions to run tests on every PR before merge.

**When:** Before adding a second developer.
