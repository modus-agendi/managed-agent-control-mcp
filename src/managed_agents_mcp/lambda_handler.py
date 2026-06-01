"""AWS Lambda entry point.

Lambda discovers `managed_agents_mcp.lambda_handler.handler`. The whole transport
shape (Mangum + Starlette + FastMCP + pluggable auth + optional SSM loader) lives
in `app/`; this module is just the handler binding.
"""

from __future__ import annotations

from .app.run import build_lambda_handler

handler = build_lambda_handler()
