from __future__ import annotations

from biocatalyst.config import LLMProviderName, Settings, get_settings
from biocatalyst.llm.anthropic_provider import AnthropicProvider
from biocatalyst.llm.base import BaseLLMProvider, LLMConfigurationError
from biocatalyst.llm.gemini_provider import GeminiProvider
from biocatalyst.llm.ollama_provider import OllamaProvider
from biocatalyst.llm.openai_compatible import (
    DeepSeekProvider,
    GroqProvider,
    OpenAIProvider,
)
from biocatalyst.log import get_logger

logger = get_logger(__name__)

PROVIDER_REGISTRY: dict[LLMProviderName, type[BaseLLMProvider]] = {
    LLMProviderName.ANTHROPIC: AnthropicProvider,
    LLMProviderName.OPENAI: OpenAIProvider,
    LLMProviderName.DEEPSEEK: DeepSeekProvider,
    LLMProviderName.GROQ: GroqProvider,
    LLMProviderName.GEMINI: GeminiProvider,
    LLMProviderName.OLLAMA: OllamaProvider,
}


def build_provider(
    provider: LLMProviderName,
    model: str | None = None,
    settings: Settings | None = None,
) -> BaseLLMProvider:
    """Istanzia un provider. `model=None` usa il default della classe del provider."""
    settings = settings or get_settings()

    provider_class = PROVIDER_REGISTRY.get(provider)
    if provider_class is None:  # pragma: no cover - irraggiungibile finché l'enum è esaustivo
        raise LLMConfigurationError(f"Provider sconosciuto: {provider}")

    if provider is LLMProviderName.OLLAMA:
        return OllamaProvider(
            model=model,
            base_url=settings.ollama_base_url,
            timeout=settings.llm_request_timeout_seconds,
            max_retries=settings.llm_max_retries,
        )

    api_key = settings.api_key_for(provider)
    if api_key is None:
        raise LLMConfigurationError(
            f"Il provider '{provider.value}' è configurato ma la sua API key non è "
            f"impostata nel file .env."
        )

    return provider_class(
        model=model,
        api_key=api_key,
        timeout=settings.llm_request_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


def provider_for_agent(agent: str, settings: Settings | None = None) -> BaseLLMProvider:
    """Provider da usare per un agente, secondo gli override AGENT_*_PROVIDER del .env."""
    settings = settings or get_settings()
    provider_name, model = settings.resolve_agent_provider(agent)
    instance = build_provider(provider_name, model, settings)
    logger.debug(
        "provider_risolto",
        agente=agent,
        provider=provider_name.value,
        model=instance.model,
    )
    return instance
