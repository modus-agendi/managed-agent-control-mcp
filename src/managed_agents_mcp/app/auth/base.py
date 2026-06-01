"""Inbound-auth abstraction: how MCP clients authenticate to this server.

`Authenticator` is the pluggable contract. Concrete modules:
  - `bearer.StaticBearerAuthenticator` — a shared static token.
  - `oidc.OIDCAuthenticator` — JWT verification against any OIDC provider.
  - `cognito.CognitoAuthenticator` — OIDC preset + AWS Cognito hosted-UI facade.

`CompositeAuthenticator` lets modes coexist (try each in order; first success
wins), so e.g. `oidc,bearer` accepts JWTs from real connectors AND a static
token from CLI tools. `AuthMiddleware` enforces it for every HTTP request,
bypassing the public OAuth-discovery paths.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route


class AuthError(Exception):
    """Raised when an inbound request fails authentication."""


@dataclass(frozen=True)
class Principal:
    """The authenticated caller's identity, surfaced to tools / the key resolver."""

    subject: str
    email: str | None = None
    raw: dict = field(default_factory=dict)


class Authenticator:
    """Base inbound authenticator. Subclasses implement `validate`."""

    def validate(self, headers: Mapping[str, str], query: Mapping[str, str]) -> Principal:
        """Return a Principal or raise AuthError. Must not mutate inputs."""
        raise NotImplementedError

    def public_paths(self) -> tuple[str, ...]:
        """Paths that bypass auth (entries ending in '/' are prefix matches)."""
        return ()

    def routes(self) -> list[Route]:
        """Provider-specific routes to mount (OAuth discovery / facade). Default none."""
        return []

    def advertises_oauth(self) -> bool:
        """Whether to point 401s at OAuth discovery metadata (RFC 9728)."""
        return bool(self.routes())


class CompositeAuthenticator(Authenticator):
    """Try each authenticator in order; the first to return a Principal wins."""

    def __init__(self, authenticators: list[Authenticator]) -> None:
        if not authenticators:
            raise ValueError("CompositeAuthenticator requires at least one authenticator")
        self._authenticators = authenticators

    def validate(self, headers: Mapping[str, str], query: Mapping[str, str]) -> Principal:
        last: AuthError | None = None
        for auth in self._authenticators:
            try:
                return auth.validate(headers, query)
            except AuthError as e:
                last = e
        raise last or AuthError("no authenticator accepted the request")

    def public_paths(self) -> tuple[str, ...]:
        paths: tuple[str, ...] = ()
        for auth in self._authenticators:
            paths += auth.public_paths()
        return tuple(dict.fromkeys(paths))  # de-dupe, preserve order

    def routes(self) -> list[Route]:
        seen: dict[tuple[str, str], Route] = {}
        for auth in self._authenticators:
            for r in auth.routes():
                seen.setdefault((r.path, ",".join(sorted(r.methods or []))), r)
        return list(seen.values())


def public_base(request: Request) -> str:
    """Externally-visible base URL (scheme + host) for discovery/facade links.

    Prefers `MCP_PUBLIC_URL` (set when a proxy/CDN/custom domain fronts this
    server, so its own hostname is not what clients reach) over the request host.
    """
    override = os.environ.get("MCP_PUBLIC_URL")
    if override:
        return override.rstrip("/")
    return f"{request.url.scheme}://{request.url.netloc}"


def bearer_token(headers: Mapping[str, str]) -> str | None:
    """Extract a bearer token from the Authorization header, if present."""
    auth = headers.get("authorization") or headers.get("Authorization")
    if not auth:
        return None
    parts = auth.split(None, 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


class AuthMiddleware(BaseHTTPMiddleware):
    """Reject requests that fail the configured authenticator, bypassing public paths."""

    def __init__(self, app, authenticator: Authenticator) -> None:
        super().__init__(app)
        self._auth = authenticator
        self._public = authenticator.public_paths()

    def _is_public(self, path: str) -> bool:
        # Entries ending in "/" are PREFIX matches; the rest are EXACT, so
        # "/authorizeX" cannot slip past to the protected mount.
        return any(path == p or (p.endswith("/") and path.startswith(p)) for p in self._public)

    async def dispatch(self, request: Request, call_next) -> Response:
        if self._is_public(request.url.path):
            return await call_next(request)
        try:
            principal = self._auth.validate(dict(request.headers), dict(request.query_params))
        except AuthError as e:
            client = request.client.host if request.client else "?"
            # Stdout → log aggregator. "auth:" prefix is a stable hook for alarms.
            print(f"auth: {e} (client={client} path={request.url.path})", flush=True)
            headers = {"WWW-Authenticate": _www_authenticate(request, self._auth)}
            return JSONResponse({"error": "unauthorized"}, status_code=401, headers=headers)
        request.state.principal = principal
        return await call_next(request)


def _www_authenticate(request: Request, auth: Authenticator) -> str:
    """RFC 6750 + RFC 9728 challenge; advertises discovery when OAuth is configured."""
    if auth.advertises_oauth():
        meta = f"{public_base(request)}/.well-known/oauth-protected-resource"
        return f'Bearer realm="mcp", resource_metadata="{meta}"'
    return 'Bearer realm="mcp"'
