from __future__ import annotations

import pytest

from managed_agents_mcp import guardrails


def test_agent_allowlist_empty_allows_all():
    guardrails.check_agent_allowed("agent_anything")  # no raise


def test_agent_allowlist_enforced(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MCP_ALLOWED_AGENT_IDS", "agent_ok, agent_also")
    guardrails.reset_cache()
    guardrails.check_agent_allowed("agent_ok")  # no raise
    with pytest.raises(guardrails.GuardrailError):
        guardrails.check_agent_allowed("agent_nope")


def test_environment_allowlist_enforced(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MCP_ALLOWED_ENVIRONMENT_IDS", "env_ok")
    guardrails.reset_cache()
    with pytest.raises(guardrails.GuardrailError):
        guardrails.check_environment_allowed("env_other")


def test_destructive_default_allowed():
    guardrails.check_destructive_allowed("session_delete")  # no raise


def test_destructive_can_be_disabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MCP_ALLOW_DESTRUCTIVE", "false")
    guardrails.reset_cache()
    with pytest.raises(guardrails.GuardrailError):
        guardrails.check_destructive_allowed("session_archive")


def test_audit_emits_json(capsys: pytest.CaptureFixture[str]):
    guardrails.audit("session_start", session_id="sesn_1")
    line = capsys.readouterr().out.strip()
    assert '"audit": "session_start"' in line
    assert '"session_id": "sesn_1"' in line
