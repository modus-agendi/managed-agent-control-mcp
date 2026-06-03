# Configuration

All configuration is via environment variables (locally from your shell or a
`.env` file; in the cloud from your platform's secret store / SSM). See
[`.env.example`](../.env.example) for a copy-paste starting point.

## Outbound (calling the Managed Agents API)

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — (**required**) | Operator key the server acts with. Single-tenant: every authenticated caller shares this key's workspace. |
| `ANTHROPIC_BASE_URL` | `https://api.anthropic.com` | Override for gateways / a local test server. |
| `ANTHROPIC_VERSION` | `2023-06-01` | `anthropic-version` header. |
| `MANAGED_AGENTS_BETA` | `managed-agents-2026-04-01` | `anthropic-beta` header. |

## Inbound auth (HTTP only)

Stdio needs none of these. See [authentication.md](authentication.md) for full
setup. `MCP_AUTH_MODE` is a comma-separated list — modes coexist.

| Variable | Used by | Description |
|---|---|---|
| `MCP_AUTH_MODE` | all | `bearer`, `oidc`, `cognito` (e.g. `oidc,bearer`). Unset = no auth. |
| `MCP_BEARER_TOKEN` | bearer | Shared static token. |
| `MCP_OIDC_ISSUER` | oidc, cognito | Token issuer (`iss`). |
| `MCP_OIDC_JWKS_URL` | oidc, cognito | JWKS endpoint for signature verification. |
| `MCP_OIDC_AUDIENCE` | oidc, cognito | Accepted audience(s) / client id(s), comma-separated. |
| `MCP_OIDC_ALLOWED_PRINCIPALS` | oidc, cognito | Optional allow-list of `sub`/`email`/`username`. |
| `MCP_OIDC_REQUIRE_TOKEN_USE` | oidc | Require a `token_use` claim value (e.g. `access`). |
| `MCP_COGNITO_HOSTED_UI` | cognito | Cognito hosted-UI base URL (for the OAuth facade). |
| `MCP_PUBLIC_URL` | oidc, cognito | Public base URL to advertise in OAuth discovery when a proxy/CDN/custom domain fronts the server. |

## HTTP server

| Variable | Default | Description |
|---|---|---|
| `MCP_HOST` | `0.0.0.0` | Bind host for `--http` / the container. |
| `MCP_PORT` | `8000` | Bind port. |

## Guardrails

Optional limits that bound what a caller (or a prompt-injected MCP client) can
do with your key. All **off by default** (unset = no restriction).

| Variable | Description |
|---|---|
| `MCP_ALLOWLIST_AGENTS_ACTIVE` | `true` activates the agent allowlist. **Default off → every agent is allowed**, and `MCP_ALLOWED_AGENT_IDS` is ignored. |
| `MCP_ALLOWED_AGENT_IDS` | Comma-separated `agent_*` ids `session_start` may launch — **only when the allowlist is active**. Others are then rejected. |
| `MCP_ALLOWED_ENVIRONMENT_IDS` | Comma-separated `env_*` ids sessions may use (enforced whenever set). |
| `MCP_ALLOW_DESTRUCTIVE` | `false` makes `session_archive` and `session_delete` refuse. |

Every tool call also emits a structured JSON audit line to stdout (tool,
relevant ids, status — never secrets) for monitoring.

## AWS Lambda only

| Variable | Description |
|---|---|
| `SSM_PARAM_PREFIX` | When set, the cold-start loader reads SSM SecureStrings under this prefix into the environment (uppercased: `anthropic-api-key` → `ANTHROPIC_API_KEY`). Set automatically by the Terraform module. |
