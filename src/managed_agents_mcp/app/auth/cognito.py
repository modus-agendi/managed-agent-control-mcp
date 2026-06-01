"""AWS Cognito preset.

Cognito is just an OIDC provider, but its hosted UI lacks RFC-8414 discovery and
dynamic client registration, and Claude.ai's connector builds `<MCP-URL>/authorize`
directly. So the Cognito preset = the generic OIDC verifier (configured to reject
ID tokens, like Cognito access tokens require) PLUS a small facade that advertises
*this* server as the authorization server and proxies `/authorize` + `/token` to
Cognito's hosted UI. Any other OIDC provider should use the plain `oidc` mode.
"""

from __future__ import annotations

from ..oauth_routes import (
    authorization_server_routes,
    cognito_facade_routes,
    protected_resource_route,
)
from .oidc import OIDCAuthenticator


class CognitoAuthenticator(OIDCAuthenticator):
    def __init__(
        self,
        *,
        issuer: str,
        jwks_url: str,
        hosted_ui_url: str,
        audiences: list[str] | None = None,
        allowed_principals: list[str] | None = None,
    ) -> None:
        if not hosted_ui_url:
            raise ValueError("CognitoAuthenticator requires hosted_ui_url")
        # Cognito access tokens carry token_use="access"; ID tokens are not valid
        # API credentials, so reject them at the edge.
        super().__init__(
            issuer=issuer,
            jwks_url=jwks_url,
            audiences=audiences,
            allowed_principals=allowed_principals,
            require_token_use="access",  # noqa: S106 — not a secret; it's the OIDC token_use claim
        )
        self._hosted_ui_url = hosted_ui_url

    def public_paths(self) -> tuple[str, ...]:
        return ("/.well-known/", "/authorize", "/token", "/register")

    def routes(self):
        # Advertise THIS server as the authorization server (authorization_servers
        # defaults to self), then host the facade endpoints Claude.ai will call.
        return [
            protected_resource_route(),
            *authorization_server_routes(self._jwks_url),
            *cognito_facade_routes(self._hosted_ui_url),
        ]
