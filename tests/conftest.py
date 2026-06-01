"""Shared test fixtures.

Every test runs with a dummy ANTHROPIC_API_KEY and a clean, cache-reset config /
guardrails state, with any host MCP_* env removed so a developer's shell can't
leak configuration into the suite.
"""

from __future__ import annotations

import pytest

from managed_agents_mcp import config, guardrails

_CLEARED_ENV = (
    "ANTHROPIC_BASE_URL",
    "ANTHROPIC_VERSION",
    "MANAGED_AGENTS_BETA",
    "MCP_AUTH_MODE",
    "MCP_BEARER_TOKEN",
    "MCP_OIDC_ISSUER",
    "MCP_OIDC_JWKS_URL",
    "MCP_OIDC_AUDIENCE",
    "MCP_OIDC_ALLOWED_PRINCIPALS",
    "MCP_OIDC_REQUIRE_TOKEN_USE",
    "MCP_COGNITO_HOSTED_UI",
    "MCP_PUBLIC_URL",
    "MCP_ALLOWED_AGENT_IDS",
    "MCP_ALLOWED_ENVIRONMENT_IDS",
    "MCP_ALLOW_DESTRUCTIVE",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    for name in _CLEARED_ENV:
        monkeypatch.delenv(name, raising=False)
    config.reset_cache()
    guardrails.reset_cache()
    yield
    config.reset_cache()
    guardrails.reset_cache()
