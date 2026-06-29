---
title: Agent calls tools as in-process functions, not over the MCP wire
status: Accepted
date: 2026-06-29
---

## Context

We built a FastMCP server (`mcp_server.py`) exposing `search_interests` /
`search_party_donations` / `search_votes` (ADR on analysis-as-skill + PR #32). Now the
LangGraph agent (#11) needs to call those tools. There are two ways to wire it:

- **A — in-process functions.** The agent calls LangChain `@tool` wrappers around the
  same `similarity_search()` / `embed_query()` the MCP server uses. One process.
- **B — over the MCP wire.** The agent launches the MCP server as a subprocess and
  calls tools via the MCP protocol (stdio), using `langchain-mcp-adapters`.

## Decision

Use **A — in-process functions** for the agent. Keep the MCP server for *external*
clients (Claude Desktop, Cursor, any MCP host).

`similarity_search()` is the single source of truth. The MCP server and the agent's
LangChain tools are both thin wrappers over it — so we don't duplicate logic, and the
agent stays fast and easy to test.

### Why this matches industry practice

The dominant pattern for an app's *own* agent is in-process tool functions — it's the
primary path in LangChain/LangGraph, OpenAI function calling, and Anthropic tool use.
MCP's genuine win is **cross-application distribution**: you expose an MCP *server* so
LLM apps you don't own (Claude Desktop, IDEs) can reuse your tools — exactly how
GitHub, Sentry, Stripe, and Cloudflare ship official MCP servers. We already have that
covered by `mcp_server.py`.

So we get both: in-process tools for our agent (A), and an MCP server for the outside
world — the same split those vendors use.

| | A — in-process (chosen) | B — wire MCP |
|---|---|---|
| Speed | function call | network round-trip (JSON over stdio) |
| Testability | trivial (mock the function) | fiddly (subprocess / mock session) |
| Failure surface | tiny | subprocess start, handshake, stdio deadlocks |
| Reuse by other apps | via the MCP server (already exists) | native |

## Consequences

**Good:**
- Fast, robust, easy-to-test agent; no subprocess or protocol overhead
- No duplicated search logic — both paths call `similarity_search()`
- The MCP server still serves external clients, so we lose nothing

**Watch out for:**
- If we ever need the agent to call tools across a process/machine boundary (e.g. a
  remote tool server), revisit B via `langchain-mcp-adapters`. The switch is localized
  because the underlying functions are unchanged.
- Two thin tool layers exist (MCP tools + LangChain tools). Keep both pointing at
  `similarity_search()`; don't let logic drift into either wrapper.

## Related

- [[012-analysis-as-skill]] — the analysis method the agent applies
- GitHub issue #11 — the LangGraph agent
- `mcp_server.py` (PR #32) — the MCP server for external clients
