"""managed-agent-control-mcp — control Claude Managed Agents over MCP.

Exposes the Claude Managed Agents API (sessions + read-only agent/environment
discovery) as MCP tools so a Claude.ai user — or any MCP client — can start a
managed agent, observe its progress, and interact with it (steer, interrupt,
approve tool calls).

Runs locally over stdio, as a generic HTTP container, or on AWS Lambda. See the
README for transports and the pluggable inbound-auth modes (bearer / OIDC /
Cognito).
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
