---
title: Railway platform attack — environment secrets exposed
status: Open
date: 2026-10-23
---

## What happened

Railway disclosed a security incident on 2026-10-21. The attacker searched customer
environment variables for AI and cloud provider API keys. Railway's follow-up email
says this workspace ("Mahsa Clinton's Projects") has variables matching the
attacker's search pattern. Railway cannot confirm whether the secrets were
decrypted. The attack ended by 2026-10-22 03:32 UTC. This project keeps every
secret in Railway service variables, so all of them are treated as compromised.

Two Railway projects are affected: **paidup-intelligence** and **PaidUp**. Both repos
were checked: a full git-history search found only placeholders
(`.env.example`) and local-dev Docker credentials (`localdev`). `.env` has always
been gitignored. PaidUp's full history (147 commits) is likewise clean. Nothing needs
purging from GitHub.

## Exposure

### paidup-intelligence

| Secret | Grants | Rotated | Usage reviewed |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Billable Claude API calls | ☑ disabled (delete pending) | ☐ |
| `OPENAI_API_KEY` | Billable OpenAI calls (embeddings) | ☑ revoked | ☐ |
| `DATABASE_URL` | Write/owner on intelligence-postgres | ☐ | ☐ |
| `DATABASE_URL_READONLY` | SELECT on intelligence-postgres | ☐ | ☐ |
| `PAIDUP_DATABASE_URL` | PaidUp DB (`donor_company_links`, `donor_tags`) | ☐ | ☐ |
| `THEYWORKFORYOU_API_KEY` | TWFY API quota | ☐ | n/a |
| `REDIS_URL` | L1 query cache | ☐ | n/a |
| GitHub (Railway deploy integration) | Repo read/deploy | n/a | ☐ |

### PaidUp

| Secret | Grants | Rotated | Usage reviewed |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Billable Claude API calls (may be the same key as above) | ☑ disabled (delete pending) | ☐ |
| `DATABASE_URL` | paidup-postgres owner (same DB as `PAIDUP_DATABASE_URL` above) | ☐ | ☐ |
| `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` | Cloudflare R2 bucket read/write | ☐ | ☐ |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Langfuse traces (contain prompts and responses) | ☐ | ☐ |
| `FLASK_SECRET_KEY` | Signs session cookies; rotating logs everyone out | ☐ | n/a |
| `THEYWORKFORYOU_API_KEY` | TWFY API quota | ☐ | n/a |
| `REDIS_URL` | Cache | ☐ | n/a |

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
5. **GitHub** — Railway's notice asks for this. Review the security log
   (Settings → Security log), authorized OAuth/GitHub Apps, deploy keys, and recent
   pushes to both repos. No Docker Hub images are published (the Dockerfile only
   pulls `ghcr.io/astral-sh/uv`), so there are no registry credentials to check.
6. **Accounts** — confirm 2FA on Railway, Anthropic, OpenAI, GitHub.
7. **Close out** — re-check usage logs for the whole window (start unknown, so go
   back at least to 2026-10-01, through today, since a copied key can be used later), then fill in the timeline below and set status to
   Resolved.

## Timeline

| When (UTC) | Event |
|---|---|
| unknown → 2026-10-22 03:32 | Railway attack window (Railway: "no longer under direct attack" as of 03:32) |
| 2026-10-21 | Railway publishes preliminary disclosure |
| 2026-10-23 | Railway emails: workspace matches attacker's search pattern; decryption unconfirmed |
| 2026-10-23 | Repo history audited — clean |
| 2026-10-23 | Anthropic keys disabled (not reissued; nothing needs deploying) |
| 2026-10-23 | OpenAI key revoked (not reissued) |
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
