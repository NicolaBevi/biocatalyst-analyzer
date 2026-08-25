from __future__ import annotations

import pytest

from biocatalyst.config import LLMProviderName, Settings


def test_settings_loads_with_required_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "BioCatalystAnalyzer test@example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("DEFAULT_PROVIDER", "anthropic")

    settings = Settings(_env_file=None)

    assert settings.default_provider is LLMProviderName.ANTHROPIC
    assert settings.sec_edgar_user_agent == "BioCatalystAnalyzer test@example.com"
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-ant-test"


def test_settings_rejects_default_provider_without_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "BioCatalystAnalyzer test@example.com")
    monkeypatch.setenv("DEFAULT_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_resolve_agent_provider_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "BioCatalystAnalyzer test@example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("DEFAULT_PROVIDER", "anthropic")
    monkeypatch.setenv("AGENT_WRITER_PROVIDER", "anthropic")
    monkeypatch.setenv("AGENT_WRITER_MODEL", "claude-sonnet-5")

    settings = Settings(_env_file=None)

    provider, model = settings.resolve_agent_provider("writer")
    assert provider is LLMProviderName.ANTHROPIC
    assert model == "claude-sonnet-5"

    provider, model = settings.resolve_agent_provider("analyst")
    assert provider is LLMProviderName.ANTHROPIC
    assert model is None


def test_secret_values_are_masked_in_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "BioCatalystAnalyzer test@example.com")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-super-secret")
    monkeypatch.setenv("DEFAULT_PROVIDER", "anthropic")

    settings = Settings(_env_file=None)

    assert "sk-ant-super-secret" not in repr(settings.anthropic_api_key)
    assert "sk-ant-super-secret" not in str(settings.anthropic_api_key)
