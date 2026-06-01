# Authentication

This server has **two** independent auth layers — don't conflate them:

- **Outbound** — how the server calls Anthropic. Always your `ANTHROPIC_API_KEY`.
- **Inbound** — how MCP clients authenticate *to the server*. The rest of this
  page. Required for any HTTP deployment; stdio has no network boundary.

Set `MCP_AUTH_MODE` to one or more of `bearer`, `oidc`, `cognito` (comma-separated).
When multiple are set they coexist: a JWT-shaped token is tried against OIDC,
otherwise the static bearer token is checked.

## bearer — a shared static token

The simplest option. Generate a long random token and hand it to clients.

```bash
export MCP_AUTH_MODE=bearer
export MCP_BEARER_TOKEN=$(openssl rand -hex 32)
```

Clients send `Authorization: Bearer <token>`. In Claude.ai, add a custom
connector pointing at `https://<host>/mcp` and paste the token as a bearer
header; with `mcp-remote`, pass `--header "Authorization: Bearer <token>"`.

## oidc — any OIDC provider (JWT)

Verifies `Authorization: Bearer <jwt>` against your provider's JWKS, checking
signature, issuer, audience, and expiry. Works with Auth0, Okta, Keycloak,
Microsoft Entra, AWS Cognito, etc.

```bash
export MCP_AUTH_MODE=oidc
export MCP_OIDC_ISSUER=https://your-tenant.us.auth0.com/
export MCP_OIDC_JWKS_URL=https://your-tenant.us.auth0.com/.well-known/jwks.json
export MCP_OIDC_AUDIENCE=your-api-identifier        # comma-separated for several
# Optional hardening:
export MCP_OIDC_ALLOWED_PRINCIPALS=alice@example.com,bob@example.com
export MCP_OIDC_REQUIRE_TOKEN_USE=access            # reject ID tokens
```

The server publishes `/.well-known/oauth-protected-resource` advertising your
provider as the authorization server, so spec-compliant MCP clients discover and
complete the OAuth flow against the provider directly.

## cognito — OIDC + hosted-UI facade

AWS Cognito is an OIDC provider, but its hosted UI lacks RFC-8414 discovery and
dynamic client registration, and Claude.ai builds `<MCP-URL>/authorize` directly.
The `cognito` preset adds a small facade that advertises *this* server as the
authorization server and proxies `/authorize` + `/token` to Cognito's hosted UI.
It also requires `token_use == "access"` (rejecting ID tokens).

```bash
export MCP_AUTH_MODE=cognito
export MCP_OIDC_ISSUER=https://cognito-idp.<region>.amazonaws.com/<user-pool-id>
export MCP_OIDC_JWKS_URL=$MCP_OIDC_ISSUER/.well-known/jwks.json
export MCP_OIDC_AUDIENCE=<app-client-id>            # comma-separated for several
export MCP_COGNITO_HOSTED_UI=https://<prefix>.auth.<region>.amazoncognito.com
# When a CDN/custom domain fronts the server:
export MCP_PUBLIC_URL=https://mcp.example.com
```

Use plain `oidc` for any provider that *does* support discovery + DCR — you don't
need the facade.

## Connecting Claude.ai (custom connector)

1. Deploy with HTTP (container or Lambda) and an inbound auth mode set.
2. In Claude.ai → **Settings → Connectors → Add custom connector**, enter the MCP
   URL: `https://<host>/mcp`.
3. For **bearer**: add the `Authorization: Bearer <token>` header.
   For **oidc/cognito**: complete the OAuth login flow Claude.ai initiates
   (for Cognito, paste the app client id/secret in the connector's Advanced
   section if prompted — Cognito has no dynamic client registration).

## Discovery endpoints

When an OAuth mode is active, the server serves (unauthenticated):

- `/.well-known/oauth-protected-resource` (RFC 9728) — always.
- `/.well-known/oauth-authorization-server` + `/.well-known/openid-configuration`
  (RFC 8414) and `/authorize`, `/token`, `/register` — Cognito facade only.
