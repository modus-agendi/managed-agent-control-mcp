"""Optional guardrails + structured audit logging.

These are the open-source analog of the imap server's send-allowlist: opt-in
limits that bound what a caller (or a prompt-injected MCP client) can do with
the operator's API key.

All guardrails are **off by default** — unset env vars mean "no restriction".
Operators who expose this server to less-trusted callers can switch them on:

    MCP_ALLOWED_AGENT_IDS        comma-separated agent_* ids session_start may launch
    MCP_ALLOWED_ENVIRONMENT_IDS  comma-separated env_* ids sessions may use
    MCP_ALLOW_DESTRUCTIVE        "false" makes session_archive/session_delete refuse

Every tool also emits a one-line JSON audit record to stdout (never secrets), so
the operator can monitor session creation / spend and alarm on anomalies.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache


class GuardrailError(ValueError):
    """Raised when a guardrail rejects an action. Surfaces as a clean tool error."""


@lru_cache(maxsize=1)
def _allowed_agents() -> frozenset[str]:
    raw = os.environ.get("MCP_ALLOWED_AGENT_IDS", "")
    return frozenset(a.strip() for a in raw.split(",") if a.strip())


@lru_cache(maxsize=1)
def _allowed_environments() -> frozenset[str]:
    raw = os.environ.get("MCP_ALLOWED_ENVIRONMENT_IDS", "")
    return frozenset(e.strip() for e in raw.split(",") if e.strip())


@lru_cache(maxsize=1)
def _destructive_allowed() -> bool:
    # Default true; only an explicit "false"/"0"/"no" disables destructive tools.
    raw = os.environ.get("MCP_ALLOW_DESTRUCTIVE", "true").strip().lower()
    return raw not in {"false", "0", "no", "off"}


def check_agent_allowed(agent_id: str) -> None:
    """Reject ``agent_id`` unless it is on the allowlist (or the allowlist is empty)."""
    allowed = _allowed_agents()
    if allowed and agent_id not in allowed:
        raise GuardrailError(
            f"agent {agent_id!r} is not in MCP_ALLOWED_AGENT_IDS. Add it to the "
            "allowlist to permit starting sessions for this agent."
        )


def check_environment_allowed(environment_id: str) -> None:
    """Reject ``environment_id`` unless allowlisted (or the allowlist is empty)."""
    allowed = _allowed_environments()
    if allowed and environment_id not in allowed:
        raise GuardrailError(
            f"environment {environment_id!r} is not in MCP_ALLOWED_ENVIRONMENT_IDS."
        )


def check_destructive_allowed(action: str) -> None:
    """Reject a destructive action (archive/delete) when they are disabled."""
    if not _destructive_allowed():
        raise GuardrailError(
            f"{action} is disabled on this deployment (MCP_ALLOW_DESTRUCTIVE=false)."
        )


def audit(event: str, **fields: object) -> None:
    """Emit a structured audit line to stdout — metadata only, never secrets.

    A log metric filter on ``"audit"`` can alarm on session-creation volume, so a
    leaked inbound credential that starts spawning agents is detectable.
    """
    print(json.dumps({"audit": event, **fields}), flush=True)


def reset_cache() -> None:
    """Drop cached env reads (tests mutate the environment between cases)."""
    _allowed_agents.cache_clear()
    _allowed_environments.cache_clear()
    _destructive_allowed.cache_clear()
