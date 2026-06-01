from __future__ import annotations

import pytest

from managed_agents_mcp import config


def test_defaults():
    s = config.settings()
    assert s.base_url == "https://api.anthropic.com"
    assert s.api_version == "2023-06-01"
    assert s.beta == "managed-agents-2026-04-01"


def test_base_url_override(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.com/")
    config.reset_cache()
    assert config.settings().base_url == "https://gateway.example.com"  # trailing slash stripped


def test_auth_headers():
    headers = config.auth_headers()
    assert headers["x-api-key"] == "sk-ant-test"
    assert headers["anthropic-version"] == "2023-06-01"
    assert headers["anthropic-beta"] == "managed-agents-2026-04-01"


def test_missing_key_raises(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(config.ConfigError):
        config.resolve_api_key()
