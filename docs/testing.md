# Testing

The suite is layered as a pyramid: fast, deterministic, no-network tests run on
every PR; token-spending tests that hit the real platform are opt-in and run
nightly.

| Tier | Path | What it proves | Network | When |
|---|---|---|---|---|
| **L1 Unit** | `tests/unit/` | Per-module logic: config, guardrails, the API client's request-building (respx), auth verifiers, truncation/pagination | none | every PR |
| **L1.5 Transport** | `tests/transport/` | Real `fastmcp.Client` dispatch + the shipped `build_app` ASGI shape (auth middleware, OAuth discovery) | in-process | every PR |
| **L2 Acceptance** | `tests/acceptance/` | The whole `tool → client → API` path against a **stateful fake** Managed Agents API — full start→observe→interact→respond→end loop, polling, pagination, truncation, guardrails, error mapping | in-process fake | every PR |
| **Security** | `tests/security/` | JWT attack/failure matrix (alg=none, key confusion, tampering, expiry, wrong issuer/aud/key, allowlist) + the middleware public-path boundary and discovery docs | in-process | every PR |
| **L3 Live** | `tests/live/` | Real `api.anthropic.com`: discovery reachable; create→drive→delete a real session | real | nightly / opt-in |
| **L4 Scenario** | `tests/scenarios/` | A real model drives the MCP tools (backed by the fake) and an LLM judge grades correct usage — validates the tool descriptions as activation prompts | real (model only) | nightly / opt-in |
| **Post-deploy smoke** | `scripts/smoke-deployed.py` | A deployed URL: connect → list tools → call a read tool with real auth | real | after deploy |

## Running

```bash
uv sync --all-extras

# Everything that runs on a PR (no network, no tokens):
uv run pytest                       # L1 + L1.5 + L2 + security; live/scenarios auto-skip

# Just one tier:
uv run pytest tests/acceptance
uv run pytest tests/security

# Live tier (real API; opt-in):
RUN_LIVE=1 ANTHROPIC_API_KEY=sk-ant-... \
  MAC_TEST_AGENT_ID=agent_... MAC_TEST_ENVIRONMENT_ID=env_... \
  uv run pytest -m live

# Scenario tier (real model; bills tokens; opt-in):
RUN_SCENARIOS=1 ANTHROPIC_API_KEY=sk-ant-... uv run pytest -m scenarios

# Post-deploy smoke:
SMOKE_URL=https://<host>/mcp SMOKE_TOKEN=<bearer> uv run python scripts/smoke-deployed.py
```

## The stateful fake

`tests/fakes/managed_agents.py` is an in-memory Starlette app that emulates the
Managed Agents API, including the session state machine. The `fake_state` fixture
(in `tests/conftest.py`) points the server's HTTP client at it via
`httpx.ASGITransport`, so acceptance and scenario tests exercise real tool
dispatch with zero network calls. Agent behavior is scripted by keywords in the
user message (`[approve]`, `[big]`, `[multi:N]`, `[running]`) so a test can
provoke a specific server-observable outcome (tool confirmation, truncation,
pagination, a stuck-running session).

## CI

- `ci.yml` runs lint + type-check + the PR tiers across Python 3.11–3.13.
- `nightly.yml` runs the `live` and `scenarios` tiers from repository secrets
  (`ANTHROPIC_API_KEY`, `MAC_TEST_AGENT_ID`, `MAC_TEST_ENVIRONMENT_ID`); each tier
  self-skips if its secrets are absent.
