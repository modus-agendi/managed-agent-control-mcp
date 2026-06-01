"""Outbound configuration — how this server talks to the Managed Agents API.

This is the *outbound* half of the server's two auth layers (the *inbound* half,
how MCP clients authenticate to us, lives in ``app/auth``). Here we hold the
Anthropic API key and the API/beta version headers.

Single-tenant by default: one operator ``ANTHROPIC_API_KEY`` per deployment.
``resolve_api_key`` takes the authenticated principal so a future multi-tenant
deployment can map each caller to its own key without touching tool code — the
default implementation ignores the principal and returns the one operator key.

Everything is read from environment variables (populated locally from ``.env`` /
your shell, and in the cloud from your platform's secret store). Values are
cached so repeated tool calls don't re-read the environment.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

# Defaults track the Managed Agents docs. Override via env only if Anthropic
# bumps the API or beta version.
_DEFAULT_BASE_URL = "https://api.anthropic.com"
_DEFAULT_API_VERSION = "2023-06-01"
_DEFAULT_BETA = "managed-agents-2026-04-01"


class ConfigError(RuntimeError):
    """Raised when required outbound configuration is missing or invalid."""


@dataclass(frozen=True)
class Settings:
    """Resolved outbound settings (no secrets in here — the key is fetched separately)."""

    base_url: str
    api_version: str
    beta: str


@lru_cache(maxsize=1)
def settings() -> Settings:
    """Resolve and cache outbound settings from the environment."""
    return Settings(
        base_url=os.environ.get("ANTHROPIC_BASE_URL", _DEFAULT_BASE_URL).rstrip("/"),
        api_version=os.environ.get("ANTHROPIC_VERSION", _DEFAULT_API_VERSION).strip(),
        beta=os.environ.get("MANAGED_AGENTS_BETA", _DEFAULT_BETA).strip(),
    )


def resolve_api_key(principal: Any = None) -> str:
    """Return the Anthropic API key to use for this caller.

    Default (single-tenant) implementation returns the operator key from
    ``ANTHROPIC_API_KEY`` and ignores ``principal``. To go multi-tenant, replace
    the body with a per-principal lookup (e.g. ``principal.subject`` → a secret
    store) — the call sites in ``client.py`` already thread the principal through.
    """
    del principal  # single-tenant: every authenticated caller shares the operator key
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise ConfigError(
            "ANTHROPIC_API_KEY is unset. Set it in the environment (or your "
            "platform's secret store) so the server can call the Managed Agents API."
        )
    return key


def auth_headers(principal: Any = None) -> dict[str, str]:
    """Build the request headers the Managed Agents API requires.

    The SDK sets ``anthropic-beta`` automatically; since we speak the REST API
    directly we set it (and ``anthropic-version``) ourselves on every request.
    """
    s = settings()
    return {
        "x-api-key": resolve_api_key(principal),
        "anthropic-version": s.api_version,
        "anthropic-beta": s.beta,
        "content-type": "application/json",
    }


def reset_cache() -> None:
    """Drop cached settings (tests mutate the environment between cases)."""
    settings.cache_clear()
