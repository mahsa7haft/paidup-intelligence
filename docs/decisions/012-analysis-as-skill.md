---
title: Package conflict-of-interest analysis as a portable Skill
status: Accepted
date: 2026-06-23
---

## Context

Analysis logic currently lives as fixed prompts in PaidUp core
(`prompts/investigative_v1.txt`) scoped to personal declared interests only.
The cross-source method — how to combine four datasets that don't share IDs,
the party-vs-personal money distinction, donation-before-vote ordering, conflict
scoring, and output format — isn't written down anywhere reusable.

The common errors this method needs to prevent:

```
Error 1: conflating party donations with personal MP income
  "The MP received £50,000 from Fossil Corp"
  ← wrong if it went to the party, not the member

Error 2: treating a post-vote donation as evidence of influence
  donation date: 2024-06-01
  vote date:     2024-03-15       ← donation postdates the vote, exclude it
```

## Decision

Introduce `skills/conflict-of-interest-report/` — a self-contained skill the
agent loads on conflict/funding questions.

```
skills/
└── conflict-of-interest-report/
    ├── SKILL.md                    ← method, workflow, tool table, report template
    └── scripts/
        └── align_timeline.py      ← deterministic donation-before-vote date check
```

**Skill vs prompt distinction:**

| | Prompt (`investigative_v1.txt`) | Skill (`SKILL.md`) |
|---|---|---|
| Scope | Personal interests only | All four data sources |
| Loaded | Always (baked into one pipeline step) | On demand when task matches |
| Contains | Voice + ask | Method + workflow + script + voice |
| Party vs personal | Not distinguished | Explicitly separated |
| Date ordering | Not enforced | `align_timeline.py` handles it |

The journalist voice from `investigative_v1.txt` is **ported into** the skill
rather than cross-linked — keeping the skill portable to Claude.ai or another repo.

**`align_timeline.py`** handles the donation-before-vote check deterministically:

```
align(donations, votes) → one entry per vote with donations bucketed:

  in_window      donations within 90 days before the vote  ← strong signal
  before_window  donations > 90 days before                ← weaker, historic
  after          donations after the vote                  ← excluded, cannot have influenced
```

Conflict strength is scored by the function, not left to model judgment:
- **strong** — personal donation in window
- **moderate** — party donation in window, or personal historic
- **weak** — party donation only, historic

## Consequences

**Good:**
- Consistent, cited output every time — the method is the same regardless of which
  MP or donor is queried
- Party-vs-personal and date-ordering rules are enforced in code, not in-prompt
- Portable — works in Claude.ai, the agent, or any future interface
- The always-loaded `description` is short; full method only loads when triggered

**Watch out for:**
- If MCP tool names change in `agent.py`, update the data-sources table in SKILL.md
- `get_latest_declarations()` is marked TODO — not yet wired in agent.py
- Keep the `description` frontmatter short — it sits in context on every request

## Related

- [[001-vector-store]] — the four datasets this skill queries
- [[010-vector-similarity-and-retrieval]] — how similarity search works under the hood
- PaidUp `prompts/investigative_v1.txt` — journalist voice ported into this skill
- GitHub issue #24
