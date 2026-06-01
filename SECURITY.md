# Security Policy

## Supported versions

This project is pre-1.0. Security fixes are applied to the latest released
version on `main`. Pin a version and watch releases for security updates.

## Reporting a vulnerability

**Please do not open public issues for security problems.**

Report privately via GitHub's
[private vulnerability reporting](https://github.com/modus-agendi/managed-agent-control-mcp/security/advisories/new)
(Security → Report a vulnerability). If that is unavailable, email
**asvirida123@gmail.com** with the details.

Please include:

- A description of the issue and its impact.
- Steps to reproduce (a proof of concept if you have one).
- Affected version / commit.

You can expect an acknowledgement within a few days and a coordinated
disclosure once a fix is available.

## Security model (what to keep in mind)

This server sits between an MCP client and the Anthropic Managed Agents API, and
has **two distinct auth boundaries**:

- **Inbound** — how MCP clients authenticate *to this server*. On HTTP
  deployments this is enforced by the configured auth mode (static bearer token
  or OIDC/Cognito JWT). **Never run an HTTP deployment with auth disabled on a
  public network.** Local stdio has no network boundary.
- **Outbound** — this server holds an `ANTHROPIC_API_KEY` and acts within that
  key's workspace. Anyone who passes the inbound auth check can drive that key,
  so scope the key and use the optional guardrails (allowed-agent allowlist,
  destructive-action gate) to bound blast radius.

Hardening notes:

- Secrets come from environment variables / your platform's secret store —
  never commit them. `.env` is gitignored.
- The static bearer token is compared in constant time.
- Tool calls emit a structured audit log line (no secrets) for monitoring.
- Keep dependencies current; Dependabot is enabled.
