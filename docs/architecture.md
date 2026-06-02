# Architecture

## Request flow

```
MCP client (Claude.ai / Claude Code / mcp-remote)
      │  MCP over stdio or streamable-HTTP
      ▼
┌──────────────────────────────────────────────────────────┐
│ managed-agent-control-mcp                                  │
│                                                            │
│  app/asgi.py        Starlette app (HTTP transports)        │
│   ├─ AuthMiddleware  ── inbound auth (app/auth/*)           │
│   ├─ OAuth routes    ── discovery + Cognito facade          │
│   └─ Mount("/")      ── FastMCP streamable-HTTP app         │
│                                                            │
│  server.py          FastMCP tools (discover/start/observe/ │
│                      interact/destructive) + guardrails     │
│  client.py          async REST client → Managed Agents API │
│  config.py          outbound key + version/beta headers     │
└──────────────────────────────────────────────────────────┘
      │  HTTPS  x-api-key + anthropic-version + anthropic-beta
      ▼
Anthropic Managed Agents API  (/v1/agents, /v1/environments, /v1/sessions, …)
```

## Two auth layers (kept separate)

- **Inbound** (`app/auth/`) — authenticates the MCP *client* to this server.
  Pluggable: `bearer`, `oidc`, `cognito`. Enforced by `AuthMiddleware` on every
  HTTP request (stdio has no network boundary, so no inbound auth).
- **Outbound** (`config.py`) — authenticates *this server* to Anthropic with the
  operator's `ANTHROPIC_API_KEY`. `resolve_api_key(principal)` is the seam for a
  future multi-tenant (per-caller key) deployment; today it returns the one key.

## The polling model

MCP tool calls are request/response. The Managed Agents API offers an SSE event
stream, but there is no way to push that stream into an MCP client's reasoning.
So **observation is by polling**: the model calls `session_get` for status and
`session_events` for new output, passing the previous `next_since` as `since` to
fetch only newer events (pagination is page-token based via `next_page`). No
server-side blocking waits — they
would hit Lambda / tool timeouts. Tool descriptions and the server `instructions`
teach the model this loop.

## Module map

| Module | Responsibility |
|---|---|
| `server.py` | FastMCP instance, all `@mcp.tool` definitions, response shaping/truncation |
| `client.py` | Async `httpx` client for the Managed Agents REST API; typed errors |
| `config.py` | Outbound settings + `resolve_api_key` + request headers |
| `guardrails.py` | Optional allowlists / destructive gate + structured audit log |
| `app/asgi.py` | `build_app(mcp, authenticator)` — the shipped Starlette shape |
| `app/run.py` | `run_stdio`, `run_http` (uvicorn), `build_lambda_handler` (Mangum) |
| `app/oauth_routes.py` | RFC 9728/8414 discovery + Cognito hosted-UI facade |
| `app/auth/` | `Authenticator` contract + `bearer` / `oidc` / `cognito` + `factory` |
| `app/ssm.py` | Optional AWS SSM SecureString → env loader (Lambda only) |

## Design choices

- **Direct REST via `httpx`, not the SDK** — pins the beta-API contract here and
  keeps the client trivially mockable (respx) and the dependency surface small.
  `client.py` is the single seam to swap in the official `anthropic` SDK later.
- **Stateless** — `build_app` uses FastMCP `stateless_http=True` + `json_response=True`
  so each request is self-contained and survives serverless/multi-worker hosts.
- **Read-only control plane** — agent/environment *definitions* are managed by the
  [Terraform provider](https://github.com/modus-agendi/terraform-provider-anthropic-claude-managed-agents);
  this server only reads them and operates sessions, avoiding two sources of truth.
