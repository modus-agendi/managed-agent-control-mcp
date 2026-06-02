"""L4 scenario tests — does a real model use our tools correctly?

A real Claude is given our MCP tools and a natural task. Tool calls are executed
against the in-memory fake backend (so the agent side spends no tokens and stays
deterministic); only the driving model + judge calls bill tokens. We then assert
the model followed the intended loop (start → observe → report) both structurally
and via an LLM judge.

Opt-in:  RUN_SCENARIOS=1 ANTHROPIC_API_KEY=sk-ant-... uv run pytest -m scenarios
Model override: SCENARIO_MODEL (default claude-sonnet-4-6).
"""

from __future__ import annotations

import json
import os
import re

import pytest
from fastmcp import Client

from managed_agents_mcp import server

pytestmark = [
    pytest.mark.scenarios,
    pytest.mark.skipif(
        not (os.environ.get("RUN_SCENARIOS") and os.environ.get("ANTHROPIC_API_KEY")),
        reason="scenario tier: set RUN_SCENARIOS=1 and ANTHROPIC_API_KEY",
    ),
]

MODEL = os.environ.get("SCENARIO_MODEL", "claude-sonnet-4-6")
MAX_TURNS = 12

TASK = (
    "You control Claude Managed Agents with the provided tools. "
    "Start the agent with id 'agent_demo' in the environment with id 'env_demo' and "
    "instruct it to greet the user. Then observe the session until it is finished "
    "(poll its events / status), and tell me exactly what the agent said. "
    "Finally, delete the session to clean up."
)


def _text_blocks(blocks) -> str:
    return "".join(getattr(b, "text", "") for b in blocks if getattr(b, "type", None) == "text")


def _tool_result_text(result) -> str:
    content = getattr(result, "content", None) or []
    text = "".join(getattr(b, "text", "") for b in content if getattr(b, "type", None) == "text")
    return text or json.dumps(getattr(result, "data", None) or {})


async def _run_agent_loop(anthropic_client, tools) -> tuple[list[str], str]:
    """Drive the model's tool-use loop against the fake; return (tools_called, final_text)."""
    messages: list[dict] = [{"role": "user", "content": TASK}]
    called: list[str] = []
    final_text = ""

    async with Client(server.mcp) as mcp_client:
        for _ in range(MAX_TURNS):
            resp = anthropic_client.messages.create(
                model=MODEL, max_tokens=1024, tools=tools, messages=messages
            )
            final_text += _text_blocks(resp.content)
            messages.append(
                {"role": "assistant", "content": [b.model_dump() for b in resp.content]}
            )

            if resp.stop_reason != "tool_use":
                break

            results = []
            for block in resp.content:
                if getattr(block, "type", None) != "tool_use":
                    continue
                called.append(block.name)
                try:
                    out = await mcp_client.call_tool(block.name, block.input)
                    body = _tool_result_text(out)
                except Exception as e:
                    body = f"ERROR: {e}"
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": body})
            messages.append({"role": "user", "content": results})

    return called, final_text


def _judge(anthropic_client, called: list[str], final_text: str) -> dict:
    prompt = (
        "Grade whether an assistant correctly controlled a managed agent. It should "
        "have (1) started a session, (2) observed/polled the session until done, and "
        "(3) reported what the agent said.\n\n"
        f"Tools called, in order: {called}\n"
        f"Final answer to the user:\n{final_text}\n\n"
        'Respond with ONLY JSON: {"pass": true|false, "reason": "..."}'
    )
    resp = anthropic_client.messages.create(
        model=MODEL, max_tokens=300, messages=[{"role": "user", "content": prompt}]
    )
    text = _text_blocks(resp.content)
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return json.loads(match.group(0)) if match else {"pass": False, "reason": text}


async def test_start_observe_report_scenario(fake_state):
    anthropic = pytest.importorskip("anthropic")
    anthropic_client = anthropic.Anthropic()

    async with Client(server.mcp) as mcp_client:
        tools = [
            {"name": t.name, "description": t.description or "", "input_schema": t.inputSchema}
            for t in await mcp_client.list_tools()
        ]

    called, final_text = await _run_agent_loop(anthropic_client, tools)

    # Structural expectations: started a session and observed it.
    assert "session_start" in called, f"never started a session; called={called}"
    assert {"session_events", "session_get"} & set(called), f"never observed; called={called}"
    # The fake echoes the instruction back as "echo: <message>".
    assert "echo" in final_text.lower(), f"did not report the agent's reply: {final_text!r}"

    # LLM judge as the final gate.
    verdict = _judge(anthropic_client, called, final_text)
    assert verdict.get("pass") is True, f"judge failed: {verdict.get('reason')}"
