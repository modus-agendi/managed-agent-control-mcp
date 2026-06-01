"""OAuth discovery + (Cognito) facade routes, hosted alongside the MCP transport.

Two jobs:

1. **Discovery metadata** (`/.well-known/oauth-protected-resource`, and for the
   Cognito facade also `/.well-known/oauth-authorization-server` +
   `/.well-known/openid-configuration`) — tells spec-compliant MCP clients where
   the authorization server is.

2. **Authorization-server facade** (`/authorize`, `/token`, `/register`) — only
   for Cognito, which lacks RFC-8414 discovery + dynamic client registration.
   Claude.ai constructs `<MCP-URL>/authorize` directly; the facade bounces it to
   Cognito's hosted UI. Generic OIDC providers expose these themselves, so we
   only advertise their issuer and skip the facade.

Handlers are built by the authenticators (see `auth/oidc.py`, `auth/cognito.py`).
"""

from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route

from .auth.base import public_base

# Path of the MCP streamable-HTTP endpoint (FastMCP mounts its app at the root;
# the transport lives under /mcp). Advertised as the protected resource.
MCP_RESOURCE_PATH = "/mcp"


def protected_resource_route(authorization_servers: list[str] | None = None) -> Route:
    """RFC 9728 protected-resource metadata. Returned unauthenticated (it's how
    clients discover the auth server *before* they have a token).

    `authorization_servers` lists external AS issuers (generic OIDC). When None,
    this server advertises *itself* as the AS (the Cognito facade case)."""

    async def handler(request: Request) -> JSONResponse:
        base = public_base(request)
        servers = authorization_servers or [base]
        return JSONResponse(
            {
                "resource": f"{base}{MCP_RESOURCE_PATH}",
                "authorization_servers": servers,
                "bearer_methods_supported": ["header"],
                "scopes_supported": ["openid", "email", "profile"],
            }
        )

    return Route("/.well-known/oauth-protected-resource", handler, methods=["GET"])


def authorization_server_routes(jwks_url: str) -> list[Route]:
    """RFC 8414 / OIDC discovery advertising THIS server as the auth server, with
    /authorize + /token facades. Used by the Cognito preset only."""

    async def handler(request: Request) -> JSONResponse:
        base = public_base(request)
        return JSONResponse(
            {
                "issuer": base,
                "authorization_endpoint": f"{base}/authorize",
                "token_endpoint": f"{base}/token",
                "jwks_uri": jwks_url,
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code", "refresh_token"],
                "code_challenge_methods_supported": ["S256"],
                "token_endpoint_auth_methods_supported": [
                    "client_secret_basic",
                    "client_secret_post",
                    "none",
                ],
                "scopes_supported": ["openid", "email", "profile"],
            }
        )

    return [
        Route("/.well-known/oauth-authorization-server", handler, methods=["GET"]),
        Route("/.well-known/openid-configuration", handler, methods=["GET"]),
    ]


def cognito_facade_routes(hosted_ui_url: str) -> list[Route]:
    """`/authorize` 302 + `/token` server-side proxy → Cognito hosted UI, plus a
    501 DCR stub (Cognito has no dynamic client registration)."""
    hosted = hosted_ui_url.rstrip("/")

    async def authorize(request: Request) -> Response:
        qs = request.url.query
        return RedirectResponse(
            f"{hosted}/oauth2/authorize{f'?{qs}' if qs else ''}", status_code=302
        )

    async def token(request: Request) -> Response:
        import httpx  # lazy

        body = await request.body()
        forward = {
            h: v
            for h in ("content-type", "authorization", "accept")
            if (v := request.headers.get(h))
        }
        async with httpx.AsyncClient(timeout=10.0) as http:
            upstream = await http.post(f"{hosted}/oauth2/token", content=body, headers=forward)
        drop = {"transfer-encoding", "connection", "content-encoding", "content-length"}
        out_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in drop}
        return Response(
            content=upstream.content,
            status_code=upstream.status_code,
            headers=out_headers,
            media_type=upstream.headers.get("content-type"),
        )

    async def register(_: Request) -> JSONResponse:
        return JSONResponse({"error": "registration_not_supported"}, status_code=501)

    return [
        Route("/authorize", authorize, methods=["GET"]),
        Route("/token", token, methods=["POST"]),
        Route("/register", register, methods=["POST"]),
    ]
