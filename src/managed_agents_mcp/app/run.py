"""Run targets: stdio, generic HTTP (uvicorn), and AWS Lambda.

`__main__` dispatches to stdio (default) or HTTP (`--http`); `lambda_handler`
imports `build_lambda_handler`.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from .asgi import build_app
from .auth.factory import build_authenticator


def run_stdio() -> None:
    """Run over stdio (local use, Claude Code, MCP Inspector). No inbound auth."""
    from ..server import mcp

    mcp.run()


def run_http(host: str | None = None, port: int | None = None) -> None:
    """Serve the HTTP/streamable transport with uvicorn (generic container, VPS)."""
    import uvicorn

    from ..server import mcp

    authenticator = build_authenticator()
    if authenticator is None:
        print(
            "WARNING: MCP_AUTH_MODE is unset — running HTTP with NO inbound auth. "
            "Do not expose this on a public network. Set MCP_AUTH_MODE=bearer (or oidc/cognito).",
            file=sys.stderr,
            flush=True,
        )
    app = build_app(mcp, authenticator)
    uvicorn.run(
        app,
        host=host or os.environ.get("MCP_HOST", "0.0.0.0"),  # noqa: S104 (containers bind all)
        port=port or int(os.environ.get("MCP_PORT", "8000")),
    )


def build_lambda_handler() -> Any:
    """Build the Mangum handler for AWS Lambda (the `[lambda]` extra)."""
    from .ssm import load_credentials_into_env

    load_credentials_into_env()

    from mangum import Mangum

    from ..server import mcp

    # lifespan="on" is REQUIRED: FastMCP's streamable session manager initializes
    # in the ASGI lifespan startup event; without it every request 500s.
    return Mangum(build_app(mcp, build_authenticator()), lifespan="on")
