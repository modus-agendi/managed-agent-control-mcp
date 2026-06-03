from __future__ import annotations

import json

import httpx
import pytest
import respx

from managed_agents_mcp.client import ManagedAgentsAPIError, ManagedAgentsClient

BASE = "https://api.anthropic.com"


async def test_agents_list_sends_required_headers():
    async with respx.mock(base_url=BASE) as router:
        route = router.get("/v1/agents").mock(
            return_value=httpx.Response(200, json={"data": [{"id": "agent_1"}], "has_more": False})
        )
        client = ManagedAgentsClient()
        out = await client.agents_list()
        await client.aclose()

    assert out["data"][0]["id"] == "agent_1"
    req = route.calls.last.request
    assert req.headers["x-api-key"] == "sk-ant-test"
    assert req.headers["anthropic-beta"] == "managed-agents-2026-04-01"
    assert req.headers["anthropic-version"] == "2023-06-01"


async def test_session_create_latest_version_sends_bare_string():
    async with respx.mock(base_url=BASE) as router:
        route = router.post("/v1/sessions").mock(
            return_value=httpx.Response(200, json={"id": "sesn_1", "status": "idle"})
        )
        client = ManagedAgentsClient()
        await client.session_create("agent_1", "env_1")
        await client.aclose()

    body = json.loads(route.calls.last.request.content)
    assert body == {"agent": "agent_1", "environment_id": "env_1"}


async def test_session_create_pinned_version_sends_object():
    async with respx.mock(base_url=BASE) as router:
        route = router.post("/v1/sessions").mock(
            return_value=httpx.Response(200, json={"id": "sesn_1"})
        )
        client = ManagedAgentsClient()
        await client.session_create("agent_1", "env_1", agent_version=3, vault_ids=["vlt_1"])
        await client.aclose()

    body = json.loads(route.calls.last.request.content)
    assert body["agent"] == {"type": "agent", "id": "agent_1", "version": 3}
    assert body["vault_ids"] == ["vlt_1"]


async def test_events_list_repeats_types_query_param():
    async with respx.mock(base_url=BASE) as router:
        route = router.get(url__regex=r".*/v1/sessions/sesn_1/events.*").mock(
            return_value=httpx.Response(200, json={"data": []})
        )
        client = ManagedAgentsClient()
        await client.events_list("sesn_1", types=["agent.message", "agent.tool_use"], limit=10)
        await client.aclose()

    url = str(route.calls.last.request.url)
    assert "types%5B%5D=agent.message" in url
    assert "types%5B%5D=agent.tool_use" in url
    assert "limit=10" in url


async def test_delete_returns_marker_on_empty_body():
    async with respx.mock(base_url=BASE) as router:
        router.delete("/v1/sessions/sesn_1").mock(return_value=httpx.Response(204))
        client = ManagedAgentsClient()
        out = await client.session_delete("sesn_1")
        await client.aclose()
    assert out == {}


async def test_path_ids_are_percent_encoded():
    # A crafted id must not break out of /v1/sessions/{id} onto another endpoint:
    # its slashes are percent-encoded, so it stays a single path segment.
    async with respx.mock(base_url=BASE) as router:
        route = router.route(method="GET").mock(return_value=httpx.Response(200, json={}))
        client = ManagedAgentsClient()
        await client.session_get("sesn_1/../../v1/agents")
        await client.aclose()

    raw_path = route.calls.last.request.url.raw_path  # bytes actually sent on the wire
    assert b"%2F" in raw_path
    assert raw_path.startswith(b"/v1/sessions/sesn_1%2F")


async def test_api_error_is_parsed():
    async with respx.mock(base_url=BASE) as router:
        router.get("/v1/agents/agent_x").mock(
            return_value=httpx.Response(
                404, json={"type": "error", "error": {"type": "not_found_error", "message": "nope"}}
            )
        )
        client = ManagedAgentsClient()
        with pytest.raises(ManagedAgentsAPIError) as exc:
            await client.agent_get("agent_x")
        await client.aclose()

    assert exc.value.status_code == 404
    assert exc.value.error_type == "not_found_error"
    assert "nope" in exc.value.message
