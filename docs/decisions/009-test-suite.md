---
title: Unit test suite for ingestion scripts — pure functions, no live dependencies
status: Accepted
date: 2026-06-22
---

## Context

The ingestion scripts run for hours against live external APIs (Parliament, Electoral
Commission, OpenAI) and a real production database. The only way to discover bugs was
to run the script and watch it fail mid-run — often after thousands of API calls and
significant embedding cost.

A concrete example: `_parse_record` in `ingest_donations.py` crashed at record ~55,000
because `raw.get("DonorName", "")` returns `None` when the key exists but the EC API
sends `null`. The default only fires when the key is *missing*. This caused an
`AttributeError: 'NoneType' object has no attribute 'strip'` that wasn't discoverable
without a full run.

```
Without tests:                    With tests:

run script for 2 hrs              uv run pytest  (0.67s)
crash at record 55,000            TestParseRecord::test_none_donor_name_returns_none FAILED
fix, restart from checkpoint      fix, re-run tests
```

## Decision

Write a unit test suite covering the pure functions in every ingestion script and shared
module. Keep tests fast and dependency-free — no live DB, no API calls, no OpenAI.

```
What we test                      What we don't test
─────────────────────────────     ────────────────────────────────
Parsing logic                     Live API responses
Content sentence format           Database reads/writes
Hash determinism                  OpenAI embedding calls
Metadata enrichment               End-to-end ingestion flow
Checkpoint save/load/clear        (these require integration tests)
run_log success + failure paths
Config constant types/values
```

### Test layout

```
tests/
  test_config.py              ← shared constants (types, HTTPS URLs, EC page cap)
  test_ingest_donations.py    ← _parse_ms_date, _parse_record, _build_content,
                                 _sha256, _build_metadata, checkpoint lifecycle
  test_ingest_interests.py    ← _parse_interests (donor fallback chain), _build_content,
                                 _build_metadata, _sha256, checkpoint lifecycle
  test_ingest_votes.py        ← _vote_label (all 4 cases + priority), _build_content,
                                 checkpoint lifecycle
  test_run_log.py             ← start_run / finish_run (mocked DB),
                                 graceful failure when DB unavailable
```

### DB and API calls are mocked

`run_log` tests use `unittest.mock.patch` on `_connect`. Checkpoint tests use
pytest's `monkeypatch.chdir(tmp_path)` to redirect file I/O to a temp directory.
No environment variables or network access required.

### Results

```
96 tests collected
96 passed in 0.67s
```

## Consequences

**Good:**
- Parsing bugs are caught before a multi-hour run, not during it
- Regression tests for the `None`-field crash and similar EC API surprises
- `uv run pytest` runs in under 1 second — safe to run before every ingestion run
- Content sentence format is locked down — if the format changes (and therefore all
  content_hash values change, triggering a full re-embed), the test failure makes
  that cost visible before it happens

**Bad / watch out for:**
- Tests don't catch bugs in DB upsert logic, API pagination, or Railway connectivity
- Checkpoint tests use `monkeypatch.chdir` — tests must not be run from a directory
  where real checkpoint files exist (the standard `uv run pytest` from the repo root
  is safe; each test gets an isolated `tmp_path`)

## Related

- [[008-ingestion-resilience]] — checkpoint files being tested here
- [[004-smart-reembed]] — content_hash format tests lock in the sentence that gets hashed
- GitHub issue #20
