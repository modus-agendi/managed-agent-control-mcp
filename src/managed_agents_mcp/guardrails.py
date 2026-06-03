"""Optional guardrails + structured audit logging.

These are the open-source analog of the imap server's send-allowlist: opt-in
limits that bound what a caller (or a prompt-injected MCP client) can do with
the operator's API key.

All guardrails are **off by default** — every agent is allowed unless you opt in.
Operators who expose this server to less-trusted callers can switch them on:

    MCP_ALLOWLIST_AGENTS_ACTIVE  "true" activates the agent allowlist (default off
                                 → every agent is allowed)
    MCP_ALLOWED_AGENT_IDS        comma-separated agent_* ids allowed WHEN the
                                 allowlist is active
    MCP_ALLOWED_ENVIRONMENT_IDS  comma-separated env_* ids sessions may use
                                 (enforced whenever set)
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
def _agent_allowlist_active() -> bool:
    # Off by default: the agent allowlist is only consulted when explicitly turned on.
    raw = os.environ.get("MCP_ALLOWLIST_AGENTS_ACTIVE", "").strip().lower()
    return raw in {"true", "1", "yes", "on"}


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
    """Allow every agent by default; enforce the allowlist only when it's active.

    Activate with ``MCP_ALLOWLIST_AGENTS_ACTIVE=true``; then ``agent_id`` must be in
    ``MCP_ALLOWED_AGENT_IDS``.
    """
    if not _agent_allowlist_active():
        return
    if agent_id not in _allowed_agents():
        raise GuardrailError(
            f"agent {agent_id!r} is not in MCP_ALLOWED_AGENT_IDS. The agent allowlist "
            "is active (MCP_ALLOWLIST_AGENTS_ACTIVE=true) — add this agent to the list, "
            "or unset MCP_ALLOWLIST_AGENTS_ACTIVE to allow all agents."
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
    _agent_allowlist_active.cache_clear()
    _allowed_agents.cache_clear()
    _allowed_environments.cache_clear()
    _destructive_allowed.cache_clear()
