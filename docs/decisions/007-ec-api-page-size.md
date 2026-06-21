---
title: Electoral Commission API caps responses at 50 records per page
status: Accepted
date: 2026-06-21
---

## Context

The ingestion script requests 100 records per page from the EC API
(`rows=100`). During the first successful run we observed the API
returning only 50 records per page regardless of the `rows` parameter.

Log evidence:
```
INFO   fetched 50 / 81375   ← page 1, despite rows=100
INFO   fetched 100 / 81375  ← page 2, still 50 per page
```

The EC search API (`/api/search/Donations`) enforces a server-side cap
of 50 results per response. Setting `rows` higher than 50 has no effect.

## Decision

Set `FETCH_ROWS = 50` in `ingest_donations.py` to accurately reflect
the API's actual behaviour.

```
Script requests rows=100       EC API always returns 50

  Page 1:    records     1–50    →  fetched    50 / 81,375
  Page 2:    records    51–100   →  fetched   100 / 81,375
  Page 3:    records   101–150   →  fetched   150 / 81,375
  ...
  Page 1,628: records 81,351–81,375 → fetched 81,375 / 81,375

  Total API calls:  81,375 ÷ 50 = 1,628 pages
  Time to fetch:    1,628 × 0.3s sleep ≈ 8 minutes
  OpenAI calls:     81,375 ÷ 100 batch = 814 embedding requests
``` This makes the pagination math in logs
easier to follow and avoids the misleading impression that we control
the page size.

## Consequences

**Good:**
- Log output (`fetched N / 81375`) matches reality
- `FETCH_ROWS` can be used for accurate progress estimation:
  81,375 ÷ 50 = ~1,628 pages per full run

**Bad / watch out for:**
- 1,628 API calls per weekly refresh vs 814 if the cap were 100 — still
  fast enough at 0.3s sleep between pages (~8 min to fetch all records)
- If the EC ever raises their cap, update `FETCH_ROWS` to match and
  the script will automatically use larger pages
