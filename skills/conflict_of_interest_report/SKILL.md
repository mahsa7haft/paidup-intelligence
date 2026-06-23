---
name: conflict-of-interest-report
description: >-
  Cross-reference a UK MP's (or a donor's / industry's) declared funding, voting
  record, and APPG memberships to surface potential conflicts of interest, then
  produce a cited report. Use this whenever the user asks who funds an MP, which
  MPs are funded by a company or sector, whether a vote lines up with a donation,
  or anything touching parliamentary financial interests, donor influence, or
  conflicts of interest — even if they don't say "conflict of interest".
---

# Conflict-of-Interest Report

## What this does and why

Answering "is this MP conflicted?" means stitching together four public datasets that
don't share IDs and attribute money differently. The common errors are conflating
*party* donations with *personal* member income, and missing that a vote predates a
donation. This skill encodes the correct method so the answer is consistent and cited
every time. Output is always a structured report — never a loose paragraph, never an
accusation.

## When NOT to use

- General "how does Parliament work" questions (no data lookup needed).
- Requests to draft an accusation. Surface signals + sources; let the reader judge.

## Data sources (tool layer)

Call the agent's tools; don't answer from memory. Each tool returns the source record:

| Tool | Returns | Refresh | Watch out for |
|------|---------|---------|---------------|
| `search_interests()` | Personal MP donations, gifts, paid roles (Register of Members' Interests) | ~28 days | Attached to the *member*. Primary individual-level signal. |
| `search_party_donations()` | Party donations + loans (Electoral Commission) | Weekly | Attached to the *party*, NOT the MP. Always phrase as "the MP's party received…", never as personal income. |
| `search_votes()` | Voting record, every division (Members API) | Real-time | A donation only bears on a vote if it predates the vote. Always compare dates — use `scripts/align_timeline.py`. |
| `search_appgs()` | APPG memberships + roles (TheyWorkForYou) | Monthly | Membership alone ≠ funding signal. A funded secretariat IS a signal — flag separately. |
| `get_latest_declarations()` | Live Register feed | On demand | TODO: not yet wired in agent.py — skip for now, use search_interests() for recency. |

## Workflow

### Step 1 — Resolve the subject
- Is this MP-centred, donor-centred, or industry-centred?
- Disambiguate names: "Smith" may match multiple MPs. Confirm constituency or party before querying.

### Step 2 — Gather
```
search_interests(mp_name)         → personal declared income
search_party_donations(donor)     → party-level donations
search_votes(mp_name)             → voting record
search_appgs(mp_name)             → group memberships
```

### Step 3 — Align dates
Run `scripts/align_timeline.py` on the gathered donations and votes.
**Discard or down-rank any funding that postdates the vote** — it cannot have influenced it.

### Step 4 — Keep three buckets separate
- **Personal interests** — declared in the Register of Members' Interests
- **Party funding** — Electoral Commission records, attributed to the party not the MP
- **APPG ties** — membership and any funded secretariat

Do not conflate these. A party donation is not the MP's money.

### Step 5 — Score each potential conflict

| Strength | Criteria |
|----------|----------|
| **Strong** | Personal payment from an interested party, received *before* a favourable vote |
| **Moderate** | Party-level donation + aligned vote; or a paid APPG secretariat from an interested party |
| **Weak / context** | APPG membership alone; historic donations; votes that predate the funding |

Explain the reasoning for each score — don't just apply the label.

### Step 6 — Write the report
Use the template below. Cite every claim back to its PaidUp MP page.

---

## Report template

ALWAYS produce output in this structure:

```
# Conflict-of-interest review: [Subject]

## Summary
2–3 sentences: what was checked and the headline finding.

## Declared interests (personal)
Date | Amount | Source | Category | Citation

## Party-level funding
Clearly marked as party funding, not personal income.
Date | Amount | Donor | Party | Citation

## Voting alignment
Division | Date | Vote | Relevant funding (pre/post) | Notes

## APPG / group ties
Group | Role | Funded secretariat? | Citation

## Potential conflicts
Each entry: signal, strength score, dated evidence chain, source links.

## Sources
Every record linked to its PaidUp MP page.
```

---

## Write-up voice

For the prose in **Potential conflicts** and **Summary**, adopt this voice (ported from
PaidUp's `investigative_v1` prompt):

> You are an investigative journalist specialising in political accountability.
> Be direct and specific — name donors and amounts. Identify the most significant
> potential conflicts of interest. Flag where committee roles or policy positions
> might intersect with funders. Surface the questions a journalist should ask.
> Stop at signals and sources; do not assert wrongdoing.

---

## Citations

Every claim links to its source record on the PaidUp MP page. If a record cannot be
linked directly, state the source dataset (e.g. "Electoral Commission, Q1 2024").
Never make a claim without a citation.
