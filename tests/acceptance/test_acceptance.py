"""L2 acceptance: the full start → observe → interact → respond → end loop driven
through real MCP tool dispatch against the stateful fake Managed Agents API."""

from __future__ import annotations

import json

import pytest
from fastmcp import Client

from managed_agents_mcp import guardrails, server

pytestmark = pytest.mark.usefixtures("fake_state")


def _data(result) -> dict:
    if getattr(result, "data", None) is not None:
        return result.data
    if getattr(result, "structured_content", None):
        return result.structured_content
    return json.loads(result.content[0].text)


async def _call(name: str, args: dict | None = None) -> dict:
    async with Client(server.mcp) as client:
        return _data(await client.call_tool(name, args or {}))


# ---- discovery + happy-path lifecycle ----------------------------------------


async def test_discovery_lists_seeded_resources():
    agents = await _call("agent_list")
    envs = await _call("environment_list")
    assert any(a["id"] == "agent_demo" for a in agents["agents"])
    assert any(e["id"] == "env_demo" for e in envs["environments"])


async def test_full_loop_start_observe_interact_end():
    started = await _call(
        "session_start",
        {"agent_id": "agent_demo", "environment_id": "env_demo", "message": "hello"},
    )
    sid = started["session_id"]
    assert started["message_sent"] is True

    events = await _call("session_events", {"session_id": sid})
    texts = [
        b["text"]
        for e in events["events"]
        if e["type"] == "agent.message"
        for b in e.get("content", [])
    ]
    assert "echo: hello" in texts
    assert events["next_since"]

    status = await _call("session_get", {"session_id": sid})
    assert status["status"] == "idle"

    # Continue the conversation, then fetch only newer events via the `since` cursor.
    await _call("session_message", {"session_id": sid, "text": "again"})
    more = await _call("session_events", {"session_id": sid, "since": events["next_since"]})
    new_texts = [
        b["text"]
        for e in more["events"]
        if e["type"] == "agent.message"
        for b in e.get("content", [])
    ]
    assert new_texts == ["echo: again"]

    deleted = await _call("session_delete", {"session_id": sid})
    assert deleted["deleted"] is True


async def test_requires_action_then_respond():
    started = await _call(
        "session_start",
        {"agent_id": "agent_demo", "environment_id": "env_demo", "message": "[approve] run it"},
    )
    sid = started["session_id"]

    status = await _call("session_get", {"session_id": sid})
    assert status["stop_reason"]["type"] == "requires_action"
    tool_use_id = status["stop_reason"]["event_ids"][0]

    await _call(
        "session_respond", {"session_id": sid, "tool_use_id": tool_use_id, "result": "allow"}
    )
    after = await _call("session_get", {"session_id": sid})
    assert after["stop_reason"]["type"] == "end_turn"

    events = await _call("session_events", {"session_id": sid, "types": ["agent.tool_result"]})
    assert events["count"] == 1


# ---- observation shaping -----------------------------------------------------


async def test_large_event_payload_is_truncated():
    started = await _call(
        "session_start",
        {"agent_id": "agent_demo", "environment_id": "env_demo", "message": "[big]"},
    )
    events = await _call("session_events", {"session_id": started["session_id"]})
    text = next(
        b["text"]
        for e in events["events"]
        if e["type"] == "agent.message"
        for b in e.get("content", [])
    )
    assert "truncated" in text
    assert len(text) < 7000  # original was 7000; cap is 6000 + marker


async def test_event_pagination_and_type_filter():
    started = await _call(
        "session_start",
        {"agent_id": "agent_demo", "environment_id": "env_demo", "message": "[multi:5]"},
    )
    sid = started["session_id"]

    page1 = await _call("session_events", {"session_id": sid, "limit": 2})
    assert page1["count"] == 2
    assert page1["has_more"] is True

    page2 = await _call(
        "session_events", {"session_id": sid, "limit": 2, "page": page1["next_page"]}
    )
    assert page2["count"] == 2
    assert {e["id"] for e in page1["events"]}.isdisjoint({e["id"] for e in page2["events"]})

    only_msgs = await _call("session_events", {"session_id": sid, "types": ["agent.message"]})
    assert all(e["type"] == "agent.message" for e in only_msgs["events"])
    assert only_msgs["count"] == 5


async def test_session_list_filters_by_agent():
    a = await _call(
        "session_start", {"agent_id": "agent_demo", "environment_id": "env_demo", "message": "one"}
    )
    listed = await _call("session_list", {"agent_id": "agent_demo"})
    assert a["session_id"] in {s["id"] for s in listed["sessions"]}


# ---- interrupt ---------------------------------------------------------------


async def test_interrupt_then_redirect():
    started = await _call(
        "session_start",
        {"agent_id": "agent_demo", "environment_id": "env_demo", "message": "[running] work"},
    )
    sid = started["session_id"]
    assert (await _call("session_get", {"session_id": sid}))["status"] == "running"

    await _call("session_interrupt", {"session_id": sid, "then_message": "do this instead"})
    after = await _call("session_get", {"session_id": sid})
    assert after["status"] == "idle"


# ---- error + guardrail paths -------------------------------------------------


async def test_delete_running_session_errors():
    started = await _call(
        "session_start",
        {"agent_id": "agent_demo", "environment_id": "env_demo", "message": "[running]"},
    )
    with pytest.raises(Exception) as exc:  # fastmcp surfaces the tool error
        await _call("session_delete", {"session_id": started["session_id"]})
    assert "409" in str(exc.value)


async def test_rate_limit_error_surfaces():
    with pytest.raises(Exception) as exc:
        await _call("agent_get", {"agent_id": "agent_rate_limited"})
    assert "429" in str(exc.value)


async def test_guardrail_blocks_disallowed_agent(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MCP_ALLOWED_AGENT_IDS", "agent_other")
    guardrails.reset_cache()
    with pytest.raises(Exception) as exc:
        await _call(
            "session_start",
            {"agent_id": "agent_demo", "environment_id": "env_demo", "message": "hi"},
        )
    assert "allowlist" in str(exc.value).lower() or "MCP_ALLOWED_AGENT_IDS" in str(exc.value)
