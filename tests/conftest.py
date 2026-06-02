"""Shared test fixtures.

`_clean_env` (autouse) gives non-live tests a dummy ANTHROPIC_API_KEY and a clean,
cache-reset config/guardrails state, with host MCP_* env removed so a developer's
shell can't leak configuration in. Live/scenario tiers opt out (they use the real
environment).

`fake_state` wires the server's API client at the in-memory fake Managed Agents
API (via ASGITransport), so acceptance + scenario tests drive real tool dispatch
without touching the network.
"""

from __future__ import annotations

import httpx
import pytest

from fakes.managed_agents import build_fake
from managed_agents_mcp import config, guardrails, server
from managed_agents_mcp.client import ManagedAgentsClient

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
def _clean_env(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch):
    # Live / scenario tiers talk to the real API — leave the real environment
    # (real ANTHROPIC_API_KEY, real endpoints) untouched.
    if request.node.get_closest_marker("live") or request.node.get_closest_marker("scenarios"):
        yield
        return
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    for name in _CLEARED_ENV:
        monkeypatch.delenv(name, raising=False)
    config.reset_cache()
    guardrails.reset_cache()
    yield
    config.reset_cache()
    guardrails.reset_cache()


@pytest.fixture
def fake_state():
    """Point the server's API client at the in-memory fake; yield its state."""
    app, state = build_fake()
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://fake.local")
    original = server._CLIENT
    server._CLIENT = ManagedAgentsClient(http=http)
    try:
        yield state
    finally:
        server._CLIENT = original
