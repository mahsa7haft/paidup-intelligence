---
title: Railway platform attack — environment secrets exposed
status: Open
date: 2026-10-23
---

## What happened

Railway reported an attack on its platform in which the attacker went after
environment variables, specifically AI provider API keys. This project keeps every
secret in Railway service variables, so all of them are treated as compromised.

The repo itself was checked: a full git-history search found only placeholders
(`.env.example`) and local-dev Docker credentials (`localdev`). `.env` has always
been gitignored. Nothing needs purging from GitHub.

## Exposure

| Secret | Grants | Rotated | Usage reviewed |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Billable Claude API calls | ☐ | ☐ |
| `OPENAI_API_KEY` | Billable OpenAI calls (embeddings) | ☐ | ☐ |
| `DATABASE_URL` | Write/owner on intelligence-postgres | ☐ | ☐ |
| `DATABASE_URL_READONLY` | SELECT on intelligence-postgres | ☐ | ☐ |
| `PAIDUP_DATABASE_URL` | PaidUp DB (`donor_company_links`, `donor_tags`) | ☐ | ☐ |
| `THEYWORKFORYOU_API_KEY` | TWFY API quota | ☐ | n/a |
| `REDIS_URL` | L1 query cache | ☐ | n/a |

## Response checklist

1. **API keys** — revoke (delete, not disable) the Anthropic and OpenAI keys, issue
   new ones, set them in Railway, redeploy. Check each provider's usage page for
   spend since the attack window. Set a monthly spend limit and turn off
   auto-reload. Report fraudulent usage to the provider's support.
2. **Databases** — run `docs/security-rotate-credentials.sql` on both
   intelligence-postgres and paidup-postgres: audit (roles, sessions, tables,
   functions, triggers, row counts), rotate passwords, then terminate old sessions.
3. **Other keys** — regenerate the TheyWorkForYou key and Redis password.
4. **Elsewhere** — update any other place the old keys were copied (PaidUp's
   Railway service, local `.env` files).
5. **Accounts** — confirm 2FA on Railway, Anthropic, OpenAI, GitHub.
6. **Close out** — once Railway publishes its exposure window, re-check usage logs
   for exactly that window, then fill in the timeline below and set status to
   Resolved.

## Timeline

| When (UTC) | Event |
|---|---|
| | Railway attack window (per Railway notice) |
| 2026-10-23 | Incident noticed; repo history audited — clean |
| | Anthropic key revoked + reissued |
| | OpenAI key revoked + reissued |
| | DB passwords rotated, old sessions terminated |
| | Remaining keys rotated |

## Findings

_Record anything the audit turned up: unexpected usage, roles, tables, row-count drops._

## Lessons

- Every secret lived in one place with one blast radius. Least-privilege roles
  (ADR 013) limited what the read-only URL could do, but the write URL and both AI
  keys were exposed together.
- Spend limits on AI provider accounts are the cheapest cap on a leaked key's damage
  and should be on by default.
