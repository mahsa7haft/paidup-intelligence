---
title: Skip APPG ingestion in Phase 1 — no viable free API exists
status: Accepted
date: 2026-06-19
---

## Context

Issue #5 planned to ingest MP APPG (All-Party Parliamentary Group) memberships
into `appg_vectors` using TheyWorkForYou as the data source.

During implementation we found:

- **TheyWorkForYou API** is now a paid service (£20–£300/month). At 647 MPs per
  run, even the cheapest plan (1,000 calls/month) barely covers one full
  ingestion, making it unviable for a weekly refresh.
- **data.parliament.uk OData API** (`/api/data/AllPartyParliamentaryGroup`)
  returned 404 — endpoint appears to have been retired.
- **Parliament Members API** (`/api/Members/{id}/Biography`) does not include
  APPG roles. `otherPosts` contains internal party positions; `committeeMemberships`
  covers formal select committees only. APPGs are informal and not tracked here.
- **Parliament APPG register** (`publications.parliament.uk/pa/cm/cmallparty/`)
  returns 403 — the HTML page blocks automated access.
- **Parliament Interests API** — APPGs that have declared financial interests
  are already captured in `interests_vectors` under their relevant category.
  This covers the financially active APPGs, which are the most relevant for
  conflict-of-interest queries.

## Decision

Skip the dedicated `appg_vectors` ingestion in Phase 1. The table exists in the
schema but will remain empty.

APPG memberships are partially covered by `interests_vectors` (APPGs with
declared financial interests appear there). The three funded tables —
`interests_vectors`, `party_donations_vectors`, `votes_vectors` — are
sufficient to answer the core Phase 1 questions.

## Consequences

**Good:**
- No ongoing API cost for APPG data
- The most financially relevant APPGs (those with declared interests) are
  already searchable via `interests_vectors`
- Agent and MCP tools can be built without waiting for this dataset

**Bad / watch out for:**
- Queries like "which MPs are in the fossil fuel APPG" will miss members who
  have no declared financial interest in that APPG
- `appg_vectors` remains an empty table — MCP tool for it should not be built
  until data exists (see issue #9)

## Revisit when

- A free or low-cost Parliament API for APPGs becomes available
- Traffic justifies paying for TheyWorkForYou
- A community-maintained APPG dataset appears on data.gov.uk or similar

## Related

- GitHub issue #5 (closed as deferred)
- [[003-ivfflat-index]] — `appg_vectors` IVFFlat index exists but is irrelevant until populated
