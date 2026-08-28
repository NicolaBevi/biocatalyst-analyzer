from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMProviderName(StrEnum):
    ANTHROPIC = "anthropic"
    OPENAI = "openai"
    DEEPSEEK = "deepseek"
    GROQ = "groq"
    GEMINI = "gemini"
    OLLAMA = "ollama"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Selezione provider ---------------------------------------------------
    default_provider: LLMProviderName = LLMProviderName.ANTHROPIC
    default_model: str | None = None

    # --- API key per provider. SecretStr evita che finiscano in log/repr. -----
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    deepseek_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    gemini_api_key: SecretStr | None = None
    ollama_base_url: str = "http://localhost:11434"

    # --- Override provider/modello per agente (fallback su default_*) ---------
    agent_analyst_provider: LLMProviderName | None = None
    agent_analyst_model: str | None = None
    agent_news_provider: LLMProviderName | None = None
    agent_news_model: str | None = None
    agent_writer_provider: LLMProviderName | None = None
    agent_writer_model: str | None = None

    # --- Data provider esterni --------------------------------------------------
    sec_edgar_user_agent: str = Field(
        description=(
            "Richiesto dalla fair-access policy SEC: senza uno User-Agent "
            'identificativo (es. "BioCatalystAnalyzer nome@email.it") le '
            "chiamate a data.sec.gov ricevono 403."
        ),
    )
    finnhub_api_key: SecretStr | None = None

    # --- Cache su disco ------------------------------------------------------------
    cache_dir: Path = Path(".cache/biocatalyst")
    cache_ttl_price_seconds: int = 900
    cache_ttl_filing_seconds: int = 86_400
    cache_ttl_trial_seconds: int = 86_400
    #: TTL delle risposte dell'LLM. È ciò che rende ripetibile un report:
    #: stesso prompt (quindi stessi dati) entro questo intervallo, stessa
    #: risposta. Zero disattiva la cache delle risposte.
    cache_ttl_llm_seconds: int = 86_400

    # --- Riproducibilità del report -------------------------------------------
    #: Temperatura di campionamento. **Zero per default**: due analisi dello
    #: stesso titolo nello stesso giorno devono dare lo stesso report. Lasciata
    #: al default dell'API (tipicamente 1,0) le probabilità degli scenari
    #: ballavano fra un'esecuzione e l'altra, e con loro l'expected value —
    #: misurato su SLS: +19,1% e -27,8% a poche ore di distanza, stessi dati.
    llm_temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    #: Seme del campionamento, dove il provider lo accetta (protocollo OpenAI).
    #: Non garantisce l'identità bit a bit — nessun provider la promette — ma
    #: toglie una fonte di dispersione. `None` per lasciar fare all'API.
    llm_seed: int | None = 1

    # --- Resilienza di rete -----------------------------------------------------------
    llm_request_timeout_seconds: int = 60
    llm_max_retries: int = 3
    http_request_timeout_seconds: int = 30

    #: Streaming delle risposte LLM. Attivo per default perché è l'unico modo
    #: di far passare le risposte lunghe dietro i proxy che chiudono le
    #: connessioni inattive: Streamlit Community Cloud taglia a ~60s e
    #: l'agente scrittore impiega più del doppio.
    llm_use_streaming: bool = True

    #: Lingua di default dei report ("it" o "en"), sovrascrivibile per singola analisi.
    report_language: Literal["en", "it"] = "en"

    # --- Logging -------------------------------------------------------------------------
    log_level: str = "INFO"

    @model_validator(mode="after")
    def _check_default_provider_has_key(self) -> Self:
        key_by_provider: dict[LLMProviderName, SecretStr | None] = {
            LLMProviderName.ANTHROPIC: self.anthropic_api_key,
            LLMProviderName.OPENAI: self.openai_api_key,
            LLMProviderName.DEEPSEEK: self.deepseek_api_key,
            LLMProviderName.GROQ: self.groq_api_key,
            LLMProviderName.GEMINI: self.gemini_api_key,
        }
        provider_needs_key = self.default_provider in key_by_provider
        if provider_needs_key and key_by_provider[self.default_provider] is None:
            raise ValueError(
                f"DEFAULT_PROVIDER è '{self.default_provider.value}' ma la relativa "
                f"API key non è impostata nel .env."
            )
        return self

    def resolve_agent_provider(self, agent: str) -> tuple[LLMProviderName, str | None]:
        """Provider e modello effettivi per un agente, con fallback al default globale."""
        overrides: dict[str, tuple[LLMProviderName | None, str | None]] = {
            "analyst": (self.agent_analyst_provider, self.agent_analyst_model),
            "news": (self.agent_news_provider, self.agent_news_model),
            "writer": (self.agent_writer_provider, self.agent_writer_model),
        }
        provider_override, model_override = overrides.get(agent, (None, None))
        provider = provider_override or self.default_provider
        model = model_override or self.default_model
        return provider, model

    def api_key_for(self, provider: LLMProviderName) -> SecretStr | None:
        return {
            LLMProviderName.ANTHROPIC: self.anthropic_api_key,
            LLMProviderName.OPENAI: self.openai_api_key,
            LLMProviderName.DEEPSEEK: self.deepseek_api_key,
            LLMProviderName.GROQ: self.groq_api_key,
            LLMProviderName.GEMINI: self.gemini_api_key,
            LLMProviderName.OLLAMA: None,
        }[provider]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]  # popolato da .env / variabili d'ambiente
