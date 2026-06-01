"""Static bearer-token authenticator.

The simplest inbound auth: a single shared secret in `MCP_BEARER_TOKEN`. Clients
send `Authorization: Bearer <token>`. Zero external dependencies — works
immediately with Claude.ai custom connectors (paste the token) and mcp-remote.
"""

from __future__ import annotations

import hmac
from collections.abc import Mapping

from .base import Authenticator, AuthError, Principal, bearer_token


class StaticBearerAuthenticator(Authenticator):
    def __init__(self, token: str) -> None:
        if not token:
            raise ValueError("StaticBearerAuthenticator requires a non-empty token")
        self._token = token

    def validate(self, headers: Mapping[str, str], query: Mapping[str, str]) -> Principal:
        del query
        token = bearer_token(headers)
        if not token:
            raise AuthError("missing bearer token")
        # Constant-time compare to avoid a timing side-channel on the secret.
        if not hmac.compare_digest(token.encode(), self._token.encode()):
            raise AuthError("invalid bearer token")
        return Principal(subject="static-bearer")
