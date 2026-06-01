"""Pluggable inbound authentication for the MCP server.

Public surface: the `Authenticator` contract, the `Principal` it yields, the
`AuthError` it raises, the `AuthMiddleware` that enforces it, and the
`build_authenticator` factory that constructs one from environment config.
"""

from .base import (
    Authenticator,
    AuthError,
    AuthMiddleware,
    CompositeAuthenticator,
    Principal,
)
from .factory import AuthConfigError, build_authenticator

__all__ = [
    "AuthConfigError",
    "AuthError",
    "AuthMiddleware",
    "Authenticator",
    "CompositeAuthenticator",
    "Principal",
    "build_authenticator",
]
