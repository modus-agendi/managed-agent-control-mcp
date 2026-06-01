"""Build the production ASGI app: FastMCP transport + pluggable auth + OAuth routes.

The same `build_app` shape is used by every HTTP transport (uvicorn container and
AWS Lambda) and by the in-process transport tests, so what tests exercise is
exactly what ships.
"""

from __future__ import annotations

from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.routing import BaseRoute, Mount

from .auth.base import Authenticator, AuthMiddleware


def build_app(mcp: Any, authenticator: Authenticator | None = None) -> Starlette:
    """Wrap a FastMCP instance in a Starlette app with auth + OAuth discovery.

    Critical FastMCP settings (same rationale as a stateless serverless host):
      - stateless_http=True — each request is self-contained, so it survives
        landing on a fresh worker/container (no in-memory session affinity).
      - json_response=True — plain JSON round-trips cleanly without sticky SSE
        connections.

    When `authenticator` is None there is NO auth (local/dev only). Provider
    routes (`.well-known/*`, and the Cognito `/authorize` + `/token` facade) are
    mounted ahead of the MCP app and bypassed by `AuthMiddleware`.
    """
    mcp_app = mcp.http_app(stateless_http=True, json_response=True)

    routes: list[BaseRoute] = list(authenticator.routes()) if authenticator else []
    routes.append(Mount("/", app=mcp_app))

    middleware = [Middleware(AuthMiddleware, authenticator=authenticator)] if authenticator else []

    return Starlette(
        routes=routes,
        middleware=middleware,
        # Delegate lifespan to the inner FastMCP app so its streamable-HTTP
        # session manager task group initializes.
        lifespan=mcp_app.router.lifespan_context,
    )
