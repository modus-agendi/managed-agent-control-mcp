"""Run targets: stdio, generic HTTP (uvicorn), and AWS Lambda.

`__main__` dispatches to stdio (default) or HTTP (`--http`); `lambda_handler`
imports `build_lambda_handler`.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from .asgi import build_app
from .auth.base import Authenticator
from .auth.factory import build_authenticator


def _env_true(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _require_inbound_auth() -> Authenticator | None:
    """Resolve the inbound authenticator for a network transport, failing closed.

    An HTTP/Lambda endpoint with no inbound auth lets anyone who can reach it
    drive the operator's Anthropic API key (token cost + data exposure). So we
    refuse to start when ``MCP_AUTH_MODE`` is unset — unless the operator
    explicitly accepts the risk with ``MCP_ALLOW_INSECURE_NO_AUTH=true`` (only
    sensible for a localhost bind or a trusted private network).
    """
    authenticator = build_authenticator()
    if authenticator is not None:
        return authenticator
    if _env_true("MCP_ALLOW_INSECURE_NO_AUTH"):
        print(
            "WARNING: running with NO inbound auth (MCP_ALLOW_INSECURE_NO_AUTH=true). "
            "Anyone who can reach this endpoint can drive your Anthropic API key — "
            "only do this on a trusted/private network.",
            file=sys.stderr,
            flush=True,
        )
        return None
    raise SystemExit(
        "Refusing to start a network transport with no inbound auth. Set "
        "MCP_AUTH_MODE=bearer (or oidc/cognito) to require authentication, or set "
        "MCP_ALLOW_INSECURE_NO_AUTH=true to run without it (trusted/private networks only)."
    )


def run_stdio() -> None:
    """Run over stdio (local use, Claude Code, MCP Inspector). No inbound auth."""
    from ..server import mcp

    mcp.run()


def run_http(host: str | None = None, port: int | None = None) -> None:
    """Serve the HTTP/streamable transport with uvicorn (generic container, VPS)."""
    import uvicorn

    from ..server import mcp

    app = build_app(mcp, _require_inbound_auth())
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
    return Mangum(build_app(mcp, _require_inbound_auth()), lifespan="on")
