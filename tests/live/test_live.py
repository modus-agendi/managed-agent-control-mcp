"""L3 live tests — hit the real Managed Agents API. Opt-in.

Enable with `RUN_LIVE=1` and a real `ANTHROPIC_API_KEY`. The session round-trip
additionally needs `MAC_TEST_AGENT_ID` + `MAC_TEST_ENVIRONMENT_ID` pointing at a
throwaway agent/environment. The test always deletes the session it creates.

    RUN_LIVE=1 ANTHROPIC_API_KEY=sk-ant-... \
      MAC_TEST_AGENT_ID=agent_... MAC_TEST_ENVIRONMENT_ID=env_... \
      uv run pytest -m live
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

from managed_agents_mcp.client import ManagedAgentsClient

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not (os.environ.get("RUN_LIVE") and os.environ.get("ANTHROPIC_API_KEY")),
        reason="live tier: set RUN_LIVE=1 and ANTHROPIC_API_KEY",
    ),
]

AGENT_ID = os.environ.get("MAC_TEST_AGENT_ID")
ENVIRONMENT_ID = os.environ.get("MAC_TEST_ENVIRONMENT_ID")


async def test_discovery_reachable():
    client = ManagedAgentsClient()
    try:
        agents = await client.agents_list(limit=1)
        environments = await client.environments_list(limit=1)
    finally:
        await client.aclose()
    assert "data" in agents
    assert "data" in environments


@pytest.mark.skipif(
    not (AGENT_ID and ENVIRONMENT_ID),
    reason="set MAC_TEST_AGENT_ID + MAC_TEST_ENVIRONMENT_ID for the session round-trip",
)
async def test_session_roundtrip():
    assert AGENT_ID and ENVIRONMENT_ID  # narrowed for the type checker; guarded by skipif
    client = ManagedAgentsClient()
    session = await client.session_create(AGENT_ID, ENVIRONMENT_ID)
    sid = session["id"]
    try:
        await client.events_send(
            sid,
            [
                {
                    "type": "user.message",
                    "content": [{"type": "text", "text": "Reply with the single word READY."}],
                }
            ],
        )
        deadline = time.time() + 180
        got_message = False
        while time.time() < deadline:
            current = await client.session_get(sid)
            if current.get("status") == "idle":
                events = await client.events_list(sid, types=["agent.message"])
                got_message = any(e.get("type") == "agent.message" for e in events.get("data", []))
                break
            if current.get("status") == "terminated":
                pytest.fail("session terminated before responding")
            await asyncio.sleep(3)
        assert got_message, "agent produced no message before the deadline"
    finally:
        await client.session_delete(sid)
        await client.aclose()
