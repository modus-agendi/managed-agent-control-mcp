"""Transport + inbound-auth layer.

Wraps the FastMCP server (`server.mcp`) in a Starlette ASGI app with pluggable
inbound authentication, and provides the three run targets: stdio, a generic
HTTP server (uvicorn), and an AWS Lambda handler.

This is the generalized, open-source descendant of the imap server's vendored
`_lambda_kit` — but here auth is a first-class pluggable abstraction (bearer /
OIDC / Cognito) rather than Cognito-hardcoded, and the transport is host-agnostic
rather than Lambda-only.
"""
