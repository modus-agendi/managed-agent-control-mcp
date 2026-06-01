"""Build the inbound authenticator(s) from environment configuration.

`MCP_AUTH_MODE` is a comma-separated list (modes coexist, tried in order):

    bearer    static shared token        → MCP_BEARER_TOKEN
    oidc      any OIDC provider (JWT)     → MCP_OIDC_ISSUER, MCP_OIDC_JWKS_URL,
                                            MCP_OIDC_AUDIENCE, MCP_OIDC_ALLOWED_PRINCIPALS,
                                            MCP_OIDC_REQUIRE_TOKEN_USE
    cognito   OIDC + Cognito hosted-UI    → the OIDC vars + MCP_COGNITO_HOSTED_UI

Unset → returns None (no inbound auth). The transport layer decides what to do
with that: stdio needs none; HTTP warns loudly and should not be exposed publicly.
"""

from __future__ import annotations

import os

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


def _build_one(mode: str) -> Authenticator:
    if mode == "bearer":
        return StaticBearerAuthenticator(_require("MCP_BEARER_TOKEN"))
    if mode == "oidc":
        return OIDCAuthenticator(
            issuer=_require("MCP_OIDC_ISSUER"),
            jwks_url=_require("MCP_OIDC_JWKS_URL"),
            audiences=_csv("MCP_OIDC_AUDIENCE"),
            allowed_principals=_csv("MCP_OIDC_ALLOWED_PRINCIPALS"),
            require_token_use=os.environ.get("MCP_OIDC_REQUIRE_TOKEN_USE") or None,
        )
    if mode == "cognito":
        return CognitoAuthenticator(
            issuer=_require("MCP_OIDC_ISSUER"),
            jwks_url=_require("MCP_OIDC_JWKS_URL"),
            hosted_ui_url=_require("MCP_COGNITO_HOSTED_UI"),
            audiences=_csv("MCP_OIDC_AUDIENCE"),
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
