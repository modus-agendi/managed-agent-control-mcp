"""Transport-level tests.

Two angles:
  - In-process FastMCP client → exercises real MCP tool dispatch (list + call),
    with the upstream Managed Agents API mocked by respx.
  - The exact shipped ASGI app (`build_app`) → exercises the auth middleware and
    OAuth discovery routes that the in-process path bypasses.
"""

from __future__ import annotations

import json

import httpx
import respx
from asgi_lifespan import LifespanManager
from fastmcp import Client

from managed_agents_mcp.app.asgi import build_app
from managed_agents_mcp.app.auth.bearer import StaticBearerAuthenticator
from managed_agents_mcp.app.auth.oidc import OIDCAuthenticator
from managed_agents_mcp.server import mcp

BASE = "https://api.anthropic.com"

EXPECTED_TOOLS = {
    "agent_list",
    "agent_get",
    "environment_list",
    "environment_get",
    "vault_list",
    "vault_get",
    "memory_store_list",
    "memory_store_get",
    "session_start",
    "session_get",
    "session_list",
    "session_events",
    "session_message",
    "session_interrupt",
    "session_respond",
    "session_archive",
    "session_delete",
}


def _data(result) -> dict:
    if getattr(result, "data", None) is not None:
        return result.data
    if getattr(result, "structured_content", None):
        return result.structured_content
    return json.loads(result.content[0].text)


async def test_lists_all_tools():
    async with Client(mcp) as client:
        names = {t.name for t in await client.list_tools()}
    assert names >= EXPECTED_TOOLS


async def test_agent_list_tool_shapes_summaries():
    async with respx.mock(base_url=BASE) as router:
        router.get("/v1/agents").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": [
                        {"id": "agent_1", "name": "A", "model": "claude-opus-4-7", "system": "x"}
                    ],
                    "has_more": False,
                },
            )
        )
        async with Client(mcp) as client:
            result = await client.call_tool("agent_list", {})

    data = _data(result)
    assert data["count"] == 1
    assert data["agents"][0]["id"] == "agent_1"
    # The heavy `system` field is dropped from list summaries.
    assert "system" not in data["agents"][0]


async def test_session_start_creates_and_sends_message():
    async with respx.mock(base_url=BASE) as router:
        create = router.post("/v1/sessions").mock(
            return_value=httpx.Response(200, json={"id": "sesn_1", "status": "idle"})
        )
        events = router.post("/v1/sessions/sesn_1/events").mock(
            return_value=httpx.Response(200, json={})
        )
        async with Client(mcp) as client:
            result = await client.call_tool(
                "session_start",
                {"agent_id": "agent_1", "environment_id": "env_1", "message": "go"},
            )

    data = _data(result)
    assert data["session_id"] == "sesn_1"
    assert data["message_sent"] is True
    assert create.called and events.called


# ---- ASGI app: auth middleware + OAuth discovery -----------------------------


async def test_oidc_discovery_is_public_and_protects_mcp():
    authenticator = OIDCAuthenticator(
        issuer="https://issuer.example.com", jwks_url="https://issuer.example.com/jwks"
    )
    app = build_app(mcp, authenticator)
    transport = httpx.ASGITransport(app=app)
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as http,
    ):
        meta = await http.get("/.well-known/oauth-protected-resource")
        unauthorized = await http.get("/mcp")

    assert meta.status_code == 200
    assert meta.json()["authorization_servers"] == ["https://issuer.example.com"]
    assert unauthorized.status_code == 401
    assert "resource_metadata=" in unauthorized.headers.get("www-authenticate", "")


async def test_bearer_blocks_then_allows():
    app = build_app(mcp, StaticBearerAuthenticator("s3cret"))
    transport = httpx.ASGITransport(app=app)
    async with (
        LifespanManager(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as http,
    ):
        denied = await http.get("/mcp")
        allowed = await http.get("/mcp", headers={"Authorization": "Bearer s3cret"})

    assert denied.status_code == 401
    # A correct token passes the auth boundary (the MCP layer may then 4xx the
    # bare GET, but it is no longer a 401).
    assert allowed.status_code != 401
