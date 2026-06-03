# managed-agent-control-mcp

**Start, observe, and interact with [Claude Managed Agents](https://platform.claude.com/docs/en/managed-agents) from any MCP client** (Claude.ai, Claude Code, Cursor, `mcp-remote`, your own agent, …).

[![CI](https://github.com/modus-agendi/managed-agent-control-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/modus-agendi/managed-agent-control-mcp/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/managed-agent-control-mcp)](https://pypi.org/project/managed-agent-control-mcp/)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Claude Managed Agents run on Anthropic's platform — each is an agent definition
(model, system prompt, tools, skills) that executes inside a sandbox environment.
This MCP server puts a **remote control** on those agents: connect it to **any MCP
client** and you can launch an agent, watch what it does, reply to it, approve the
tools it wants to run, and stop it. Claude.ai is the showcase client (do it all
from a normal conversation), but the same tools work from Claude Code, Cursor,
`mcp-remote`, the MCP Inspector, or a custom MCP client. It is the runtime
companion to the [Terraform provider](https://github.com/modus-agendi/terraform-provider-anthropic-claude-managed-agents)
that *defines* agents declaratively.

It runs as a local **stdio** server, a generic **HTTP container**, or on **AWS
Lambda**, with pluggable inbound auth (static **bearer**, generic **OIDC**, or an
AWS **Cognito** preset).

> [!NOTE]
> This is a community project. It is not maintained by, endorsed by, or affiliated
> with Anthropic. The Managed Agents API is a beta API (`managed-agents-2026-04-01`).

## How it works

```
MCP client ──MCP──▶ managed-agent-control-mcp ──HTTPS (x-api-key)──▶ Managed Agents API
(Claude.ai,         (this server: tools + auth)                     (agents run here)
 Claude Code, …)
```

You drive a loop: **discover** an agent → **start** a session → **observe** by
polling events → **interact** (reply / interrupt / approve tools) → **end**.
Because MCP tool calls are request/response, observation is by polling
(`session_events` / `session_get`) — there is no live stream into the chat.

## Quickstart (local, &lt;2 min)

You need an `ANTHROPIC_API_KEY` with Managed Agents access and
[uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/modus-agendi/managed-agent-control-mcp
cd managed-agent-control-mcp
uv sync

# Run the server over stdio:
ANTHROPIC_API_KEY=sk-ant-... uv run python -m managed_agents_mcp
```

Explore the tools interactively with the MCP Inspector:

```bash
ANTHROPIC_API_KEY=sk-ant-... npx @modelcontextprotocol/inspector \
  uv run python -m managed_agents_mcp
```

Register it with **Claude Code** (a project-scoped `.mcp.json` is included):

```bash
claude mcp add managed-agent-control -- uv run python -m managed_agents_mcp
```

Once published to PyPI, you can skip the clone: `uvx managed-agent-control-mcp`.

## Tools

| Tier | Tool | Does |
|------|------|------|
| Discover | `agent_list` / `agent_get` | Find an agent and inspect its config |
| | `environment_list` / `environment_get` | Find a sandbox environment |
| Start | `session_start` | Create a session and (optionally) send the first instruction |
| Observe | `session_get` | Status (`idle`/`running`/…) + token usage |
| | `session_list` | List sessions |
| | `session_events` | Poll the agent's output/activity (cursor + type filter) |
| Interact | `session_message` | Send a message / continue a turn |
| | `session_interrupt` | Stop or redirect a running agent |
| | `session_respond` | Approve/deny a tool the agent is waiting on |
| Destructive 🔒 | `session_archive` / `session_delete` | Archive (keep history) or delete |

See [`docs/tools.md`](docs/tools.md) for every argument and return shape.

## Configuration

Only `ANTHROPIC_API_KEY` is required for local use. Full reference in
[`docs/configuration.md`](docs/configuration.md).

| Env var | Purpose |
|---|---|
| `ANTHROPIC_API_KEY` | **Required.** Operator key the server acts with. |
| `ANTHROPIC_BASE_URL` | Override the API base URL (gateways/testing). |
| `MCP_AUTH_MODE` | Inbound auth for HTTP: `bearer`, `oidc`, `cognito` (comma-separated to combine). |
| `MCP_BEARER_TOKEN` | Shared token for `bearer` mode. |
| `MCP_OIDC_ISSUER` / `MCP_OIDC_JWKS_URL` / `MCP_OIDC_AUDIENCE` | JWT verification for `oidc`/`cognito`. |
| `MCP_ALLOWED_AGENT_IDS` | Optional allowlist of agents `session_start` may launch. |
| `MCP_ALLOW_DESTRUCTIVE` | `false` disables archive/delete. |

## Authentication

There are **two** auth layers (kept separate by design):

- **Outbound** — how this server calls Anthropic: your `ANTHROPIC_API_KEY`.
- **Inbound** — how MCP clients authenticate *to this server*. Pluggable and
  required for any HTTP deployment:
  - **bearer** — a shared static token. Simplest; works with Claude.ai connectors and `mcp-remote`.
  - **oidc** — verify JWTs from any OIDC provider (Auth0, Okta, Keycloak, Entra, Cognito).
  - **cognito** — the OIDC verifier plus the hosted-UI OAuth facade Cognito needs.

Setup and Claude.ai connector onboarding: [`docs/authentication.md`](docs/authentication.md).

> [!WARNING]
> Never expose an HTTP deployment without an inbound auth mode set. Anyone who
> passes inbound auth can drive your Anthropic key — scope the key and use the
> [guardrails](docs/configuration.md#guardrails).

## Deployment

| Target | How |
|---|---|
| Local (stdio) | `uv run python -m managed_agents_mcp` |
| Container (HTTP) | `docker build -f deploy/Dockerfile -t macmcp . && docker run -p 8000:8000 …` |
| AWS Lambda | Self-contained Terraform module in [`deploy/aws-lambda/`](deploy/aws-lambda/) |

Details: [`docs/deployment.md`](docs/deployment.md).

## Documentation

- [Configuration](docs/configuration.md) — every env var + guardrails
- [Authentication](docs/authentication.md) — bearer / OIDC / Cognito + Claude.ai setup
- [Deployment](docs/deployment.md) — local, container, Lambda
- [Architecture](docs/architecture.md) — module map, the two auth layers, the polling model
- [Tools](docs/tools.md) — full tool reference
- [Examples](examples/) — end-to-end deployment walkthroughs (host + OAuth provider)

## Contributing

Contributions welcome — see [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md). Found a security issue? See
[SECURITY.md](SECURITY.md).

## License

MIT — see [LICENSE](LICENSE). Maintained by Andrei Svirida.
