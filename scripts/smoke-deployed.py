#!/usr/bin/env python
"""Post-deploy smoke test against a live deployment.

Connects to a deployed MCP endpoint over streamable-HTTP, lists tools, and calls
one read-only tool — verifying cold start, inbound auth, and transport wiring end
to end. Run after a container/Lambda deploy (e.g. in the release pipeline).

    SMOKE_URL=https://<host>/mcp \
    SMOKE_TOKEN=<bearer-token> \
    SMOKE_TOOL=agent_list \
        uv run python scripts/smoke-deployed.py

Exits 0 on success, 1 on any failure.
"""

from __future__ import annotations

import asyncio
import os
import sys

from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport


async def main() -> int:
    url = os.environ.get("SMOKE_URL")
    if not url:
        print("SMOKE_URL is required (the MCP endpoint, e.g. https://host/mcp)", file=sys.stderr)
        return 1
    token = os.environ.get("SMOKE_TOKEN")
    tool = os.environ.get("SMOKE_TOOL", "agent_list")

    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = StreamableHttpTransport(url=url, headers=headers)

    try:
        async with Client(transport) as client:
            tools = {t.name for t in await client.list_tools()}
            print(f"connected to {url} — {len(tools)} tools")
            if tool not in tools:
                print(f"FAIL: expected tool {tool!r} not advertised", file=sys.stderr)
                return 1
            result = await client.call_tool(tool, {})
            data = getattr(result, "data", None) or getattr(result, "content", None)
            print(f"called {tool!r} OK: {str(data)[:200]}")
    except Exception as e:
        print(f"FAIL: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    print("smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
