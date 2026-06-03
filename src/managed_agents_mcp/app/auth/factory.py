"""Build the inbound authenticator(s) from environment configuration.

`MCP_AUTH_MODE` is a comma-separated list (modes coexist, tried in order):

    bearer    static shared token        → MCP_BEARER_TOKEN
    oidc      any OIDC provider (JWT)     → MCP_OIDC_ISSUER, MCP_OIDC_JWKS_URL,
                                            MCP_OIDC_AUDIENCE, MCP_OIDC_ALLOWED_PRINCIPALS,
                                            MCP_OIDC_REQUIRE_TOKEN_USE,
                                            MCP_OIDC_REQUIRE_AUDIENCE (default true)
    cognito   OIDC + Cognito hosted-UI    → the OIDC vars + MCP_COGNITO_HOSTED_UI

Unset → returns None (no inbound auth). The transport layer decides what to do
with that: stdio needs none; network transports (HTTP/Lambda) fail closed unless
MCP_ALLOW_INSECURE_NO_AUTH=true.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from .base import Authenticator, CompositeAuthenticator
from .bearer import StaticBearerAuthenticator
from .cognito import CognitoAuthenticator
from .oidc import OIDCAuthenticator


class AuthConfigError(RuntimeError):
    """Raised when an auth mode is selected but its required env vars are missing."""


def _csv(name: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, "").split(",") if v.strip()]


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise AuthConfigError(f"{name} is required for the selected MCP_AUTH_MODE")
    return value


_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _require_https(name: str) -> str:
    """Like ``_require``, but reject non-HTTPS URLs (http allowed only for localhost).

    The JWKS URL is fetched to obtain the token-signing keys, and the issuer is the
    discovery trust anchor — over plain http a network attacker could swap the keys
    and forge accepted tokens. So both must be https in production; an http URL is
    tolerated only for a localhost IdP in local dev.
    """
    value = _require(name)
    parsed = urlparse(value)
    if parsed.scheme == "https":
        return value
    if parsed.scheme == "http" and (parsed.hostname or "").lower() in _LOCALHOST_HOSTS:
        return value
    raise AuthConfigError(
        f"{name} must use https (got {value!r}); http is allowed only for localhost."
    )


def _bool_env(name: str, *, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _audiences() -> list[str]:
    """Audiences to accept, requiring at least one for JWT modes by default.

    Without an audience check, *any* token the issuer mints (for any app on the
    same IdP) is accepted — a token-confusion gap. So we require
    ``MCP_OIDC_AUDIENCE`` for oidc/cognito unless the operator explicitly opts
    out with ``MCP_OIDC_REQUIRE_AUDIENCE=false``.
    """
    auds = _csv("MCP_OIDC_AUDIENCE")
    if auds or not _bool_env("MCP_OIDC_REQUIRE_AUDIENCE", default=True):
        return auds
    raise AuthConfigError(
        "MCP_OIDC_AUDIENCE is required for this MCP_AUTH_MODE: without it, any token from the "
        "issuer is accepted (token confusion across apps sharing the IdP). Set it to your MCP "
        "server's resource identifier / OAuth client id, or set MCP_OIDC_REQUIRE_AUDIENCE=false "
        "to explicitly accept the risk."
    )


def _build_one(mode: str) -> Authenticator:
    if mode == "bearer":
        return StaticBearerAuthenticator(_require("MCP_BEARER_TOKEN"))
    if mode == "oidc":
        return OIDCAuthenticator(
            issuer=_require_https("MCP_OIDC_ISSUER"),
            jwks_url=_require_https("MCP_OIDC_JWKS_URL"),
            audiences=_audiences(),
            allowed_principals=_csv("MCP_OIDC_ALLOWED_PRINCIPALS"),
            require_token_use=os.environ.get("MCP_OIDC_REQUIRE_TOKEN_USE") or None,
        )
    if mode == "cognito":
        return CognitoAuthenticator(
            issuer=_require_https("MCP_OIDC_ISSUER"),
            jwks_url=_require_https("MCP_OIDC_JWKS_URL"),
            hosted_ui_url=_require_https("MCP_COGNITO_HOSTED_UI"),
            audiences=_audiences(),
            allowed_principals=_csv("MCP_OIDC_ALLOWED_PRINCIPALS"),
        )
    raise AuthConfigError(f"unknown MCP_AUTH_MODE {mode!r} (expected: bearer, oidc, cognito)")


def build_authenticator() -> Authenticator | None:
    """Construct the configured authenticator, or None if MCP_AUTH_MODE is unset."""
    modes = _csv("MCP_AUTH_MODE")
    if not modes:
        return None
    built = [_build_one(m) for m in modes]
    return built[0] if len(built) == 1 else CompositeAuthenticator(built)
