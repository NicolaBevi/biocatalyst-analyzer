from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import MagicMock

import anthropic
import httpx
import httpx2
import ollama
import openai
import pytest
from google.genai import errors as genai_errors
from pydantic import SecretStr

from biocatalyst.config import LLMProviderName, Settings
from biocatalyst.data.cache import DataCache
from biocatalyst.llm import (
    PROVIDER_REGISTRY,
    AnthropicProvider,
    BaseLLMProvider,
    DeepSeekProvider,
    GeminiProvider,
    GroqProvider,
    LLMAuthenticationError,
    LLMBadRequestError,
    LLMConfigurationError,
    LLMConnectionError,
    LLMEmptyResponseError,
    LLMError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
    Message,
    OllamaProvider,
    OpenAIProvider,
    build_provider,
    provider_for_agent,
)


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "BioCatalystAnalyzer test@example.com")
    monkeypatch.setenv("DEFAULT_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")
    return Settings(_env_file=None)


# --- Doppio di test per la logica della classe base --------------------------


class FakeProvider(BaseLLMProvider):
    """Provider finto: non fa rete, conta le chiamate e solleva errori su richiesta."""

    name: ClassVar[LLMProviderName] = LLMProviderName.DEEPSEEK
    default_model: ClassVar[str] = "fake-model"
    retry_initial_wait: ClassVar[float] = 0.0
    retry_max_wait: ClassVar[float] = 0.0

    def __init__(self, errors: list[Exception] | None = None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.errors = errors or []
        self.calls = 0
        self.last_temperature: float | None = None
        self.last_kwargs: dict[str, Any] = {}

    def _complete(
        self,
        system: str,
        messages: list[Message],
        *,
        max_tokens: int,
        temperature: float | None,
        **kwargs: Any,
    ) -> str:
        self.calls += 1
        self.last_temperature = temperature
        self.last_kwargs = dict(kwargs)
        if self.errors:
            raise self.errors.pop(0)
        return "risposta ok"


# --- Retry / backoff ----------------------------------------------------------


def test_retry_su_errore_transitorio_poi_successo() -> None:
    provider = FakeProvider(
        errors=[LLMRateLimitError("429"), LLMRateLimitError("429")],
        api_key=SecretStr("k"),
        max_retries=3,
    )

    result = provider.complete("sys", [Message(role="user", content="ciao")])

    assert result == "risposta ok"
    assert provider.calls == 3


def test_nessun_retry_su_errore_di_autenticazione() -> None:
    provider = FakeProvider(
        errors=[LLMAuthenticationError("401")],
        api_key=SecretStr("k"),
        max_retries=3,
    )

    with pytest.raises(LLMAuthenticationError):
        provider.complete("sys", [Message(role="user", content="ciao")])

    # Un solo tentativo: ritentare con credenziali sbagliate è solo spreco.
    assert provider.calls == 1


def test_retry_esaurito_rilancia_ultimo_errore() -> None:
    provider = FakeProvider(
        errors=[LLMRateLimitError("a"), LLMRateLimitError("b"), LLMRateLimitError("c")],
        api_key=SecretStr("k"),
        max_retries=3,
    )

    with pytest.raises(LLMRateLimitError):
        provider.complete("sys", [Message(role="user", content="ciao")])

    assert provider.calls == 3


def test_max_retries_minimo_uno() -> None:
    provider = FakeProvider(api_key=SecretStr("k"), max_retries=0)
    assert provider.max_retries == 1


# --- Gestione temperature -----------------------------------------------------


def test_temperature_passata_ai_provider_che_la_supportano() -> None:
    provider = FakeProvider(api_key=SecretStr("k"))
    provider.complete("sys", [Message(role="user", content="x")], temperature=0.3)
    assert provider.last_temperature == 0.3


def test_temperature_scartata_se_non_supportata() -> None:
    class NoTempProvider(FakeProvider):
        supports_temperature: ClassVar[bool] = False

    provider = NoTempProvider(api_key=SecretStr("k"))
    provider.complete("sys", [Message(role="user", content="x")], temperature=0.3)

    # Non deve sollevare: il parametro va scartato, non propagato all'SDK.
    assert provider.last_temperature is None


def test_anthropic_dichiara_di_non_supportare_temperature() -> None:
    # L'SDK anthropic 1.x ha rimosso temperature da messages.create().
    assert AnthropicProvider.supports_temperature is False


# --- Riproducibilità: seed ----------------------------------------------------


def test_seed_propagato_a_chi_lo_supporta() -> None:
    class SeedProvider(FakeProvider):
        supports_seed: ClassVar[bool] = True

    provider = SeedProvider(api_key=SecretStr("k"))
    provider.complete("sys", [Message(role="user", content="x")], seed=42)
    assert provider.last_kwargs.get("seed") == 42


def test_seed_scartato_da_chi_non_lo_supporta() -> None:
    """Solo il protocollo OpenAI prevede `seed`: altrove esploderebbe."""
    provider = FakeProvider(api_key=SecretStr("k"))
    provider.complete("sys", [Message(role="user", content="x")], seed=42)
    assert "seed" not in provider.last_kwargs


def test_i_provider_openai_compatibili_dichiarano_il_seed() -> None:
    from biocatalyst.llm.openai_compatible import OpenAICompatibleProvider

    assert OpenAICompatibleProvider.supports_seed is True
    assert AnthropicProvider.supports_seed is False


# --- Sicurezza: nessun segreto nei log ----------------------------------------


def test_repr_non_espone_la_api_key() -> None:
    provider = FakeProvider(api_key=SecretStr("sk-super-segreta"), model="m")
    assert "sk-super-segreta" not in repr(provider)


def test_api_key_mancante_solleva_errore_esplicito() -> None:
    provider = FakeProvider(api_key=None)
    with pytest.raises(LLMConfigurationError, match="API key"):
        _ = provider.api_key_value


# --- Factory ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("provider_name", "expected_class"),
    [
        (LLMProviderName.ANTHROPIC, AnthropicProvider),
        (LLMProviderName.OPENAI, OpenAIProvider),
        (LLMProviderName.DEEPSEEK, DeepSeekProvider),
        (LLMProviderName.GROQ, GroqProvider),
        (LLMProviderName.GEMINI, GeminiProvider),
        (LLMProviderName.OLLAMA, OllamaProvider),
    ],
)
def test_registry_copre_ogni_provider(
    provider_name: LLMProviderName, expected_class: type[BaseLLMProvider]
) -> None:
    assert PROVIDER_REGISTRY[provider_name] is expected_class


def test_registry_copre_tutti_i_valori_dell_enum() -> None:
    assert set(PROVIDER_REGISTRY) == set(LLMProviderName)


def test_build_provider_istanzia_la_classe_giusta(settings: Settings) -> None:
    provider = build_provider(LLMProviderName.DEEPSEEK, "deepseek-chat", settings)
    assert isinstance(provider, DeepSeekProvider)
    assert provider.model == "deepseek-chat"


def test_build_provider_usa_il_modello_di_default_se_non_specificato(settings: Settings) -> None:
    provider = build_provider(LLMProviderName.ANTHROPIC, None, settings)
    assert provider.model == AnthropicProvider.default_model


def test_build_provider_fallisce_se_manca_la_api_key(settings: Settings) -> None:
    with pytest.raises(LLMConfigurationError, match="API key"):
        build_provider(LLMProviderName.GROQ, None, settings)


def test_ollama_non_richiede_api_key(settings: Settings) -> None:
    provider = build_provider(LLMProviderName.OLLAMA, None, settings)
    assert isinstance(provider, OllamaProvider)
    assert provider.base_url == settings.ollama_base_url


def test_provider_for_agent_rispetta_gli_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "BioCatalystAnalyzer test@example.com")
    monkeypatch.setenv("DEFAULT_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-test")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("AGENT_WRITER_PROVIDER", "anthropic")
    monkeypatch.setenv("AGENT_WRITER_MODEL", "claude-opus-5")
    settings = Settings(_env_file=None)

    writer = provider_for_agent("writer", settings)
    analyst = provider_for_agent("analyst", settings)

    assert isinstance(writer, AnthropicProvider)
    assert writer.model == "claude-opus-5"
    # L'analista non ha override: ricade sul provider di default.
    assert isinstance(analyst, DeepSeekProvider)


# --- Traduzione errori: Anthropic --------------------------------------------


def _anthropic_provider() -> AnthropicProvider:
    provider = AnthropicProvider(api_key=SecretStr("k"), max_retries=1)
    provider.retry_initial_wait = 0.0
    return provider


def _text_response(text: str, stop_reason: str = "end_turn") -> MagicMock:
    block = MagicMock()
    block.type = "text"
    block.text = text
    response = MagicMock()
    response.content = [block]
    response.stop_reason = stop_reason
    return response


def test_anthropic_estrae_solo_i_blocchi_di_testo() -> None:
    provider = _anthropic_provider()
    thinking_block = MagicMock()
    thinking_block.type = "thinking"
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = "il report"
    response = MagicMock()
    response.content = [thinking_block, text_block]
    response.stop_reason = "end_turn"

    client = MagicMock()
    client.messages.create.return_value = response
    provider._client = client

    assert provider.complete("sys", [Message(role="user", content="x")]) == "il report"


def test_anthropic_non_passa_temperature_allo_sdk() -> None:
    provider = _anthropic_provider()
    client = MagicMock()
    client.messages.create.return_value = _text_response("ok")
    provider._client = client

    provider.complete("sys", [Message(role="user", content="x")], temperature=0.7)

    # Passare temperature all'SDK anthropic 1.x solleverebbe TypeError.
    assert "temperature" not in client.messages.create.call_args.kwargs


def test_anthropic_rifiuto_per_policy_diventa_errore_esplicito() -> None:
    provider = _anthropic_provider()
    response = _text_response("", stop_reason="refusal")
    response.stop_details.category = "cyber"
    client = MagicMock()
    client.messages.create.return_value = response
    provider._client = client

    with pytest.raises(LLMBadRequestError, match="rifiutata"):
        provider.complete("sys", [Message(role="user", content="x")])


def test_anthropic_risposta_vuota_solleva_errore() -> None:
    provider = _anthropic_provider()
    client = MagicMock()
    client.messages.create.return_value = _text_response("   ")
    provider._client = client

    with pytest.raises(LLMEmptyResponseError):
        provider.complete("sys", [Message(role="user", content="x")])


# --- Traduzione errori: OpenAI-compatibili -----------------------------------


def test_openai_compatibile_antepone_il_system_prompt() -> None:
    provider = DeepSeekProvider(api_key=SecretStr("k"), max_retries=1)
    choice = MagicMock()
    choice.message.content = "risposta"
    response = MagicMock()
    response.choices = [choice]
    client = MagicMock()
    client.chat.completions.create.return_value = response
    provider._client = client

    provider.complete("istruzioni di sistema", [Message(role="user", content="domanda")])

    sent = client.chat.completions.create.call_args.kwargs["messages"]
    assert sent[0] == {"role": "system", "content": "istruzioni di sistema"}
    assert sent[1] == {"role": "user", "content": "domanda"}


def test_openai_usa_max_completion_tokens_e_i_cloni_no() -> None:
    assert OpenAIProvider.max_tokens_param == "max_completion_tokens"
    assert DeepSeekProvider.max_tokens_param == "max_tokens"
    assert GroqProvider.max_tokens_param == "max_tokens"


# --- Gemini: mappatura dei ruoli ---------------------------------------------


def test_gemini_traduce_il_ruolo_assistant_in_model() -> None:
    provider = GeminiProvider(api_key=SecretStr("k"), max_retries=1)
    response = MagicMock()
    response.text = "risposta"
    client = MagicMock()
    client.models.generate_content.return_value = response
    provider._client = client

    provider.complete(
        "sys",
        [
            Message(role="user", content="domanda"),
            Message(role="assistant", content="risposta precedente"),
        ],
    )

    contents = client.models.generate_content.call_args.kwargs["contents"]
    assert [c.role for c in contents] == ["user", "model"]


# --- Traduzione degli errori SDK nella gerarchia comune ----------------------
# È il cuore dell'astrazione: qualunque provider sia configurato, il chiamante
# vede sempre gli stessi tipi di errore e la stessa policy di retry.


def _http2_response(status: int) -> httpx2.Response:
    return httpx2.Response(status, request=httpx2.Request("POST", "https://example.invalid"))


def _failing_anthropic(exc: Exception) -> AnthropicProvider:
    provider = AnthropicProvider(api_key=SecretStr("k"), max_retries=1)
    client = MagicMock()
    client.messages.create.side_effect = exc
    provider._client = client
    return provider


@pytest.mark.parametrize(
    ("sdk_error", "expected"),
    [
        (
            anthropic.AuthenticationError("no", response=_http2_response(401), body=None),
            LLMAuthenticationError,
        ),
        (
            anthropic.PermissionDeniedError("no", response=_http2_response(403), body=None),
            LLMAuthenticationError,
        ),
        (
            anthropic.RateLimitError("slow", response=_http2_response(429), body=None),
            LLMRateLimitError,
        ),
        (
            anthropic.BadRequestError("bad", response=_http2_response(400), body=None),
            LLMBadRequestError,
        ),
        (
            anthropic.NotFoundError("gone", response=_http2_response(404), body=None),
            LLMBadRequestError,
        ),
        (
            anthropic.InternalServerError("boom", response=_http2_response(500), body=None),
            LLMServerError,
        ),
        (
            anthropic.APITimeoutError(request=httpx2.Request("POST", "https://example.invalid")),
            LLMTimeoutError,
        ),
    ],
)
def test_anthropic_traduce_gli_errori_sdk(sdk_error: Exception, expected: type[LLMError]) -> None:
    provider = _failing_anthropic(sdk_error)
    with pytest.raises(expected):
        provider.complete("sys", [Message(role="user", content="x")])


def _failing_openai_compatible(exc: Exception) -> DeepSeekProvider:
    provider = DeepSeekProvider(api_key=SecretStr("k"), max_retries=1)
    client = MagicMock()
    client.chat.completions.create.side_effect = exc
    provider._client = client
    return provider


@pytest.mark.parametrize(
    ("sdk_error", "expected"),
    [
        (
            openai.AuthenticationError("no", response=_http2_response(401), body=None),
            LLMAuthenticationError,
        ),
        (
            openai.RateLimitError("slow", response=_http2_response(429), body=None),
            LLMRateLimitError,
        ),
        (
            openai.BadRequestError("bad", response=_http2_response(400), body=None),
            LLMBadRequestError,
        ),
        (
            openai.InternalServerError("boom", response=_http2_response(500), body=None),
            LLMServerError,
        ),
        (
            openai.APITimeoutError(request=httpx2.Request("POST", "https://example.invalid")),
            LLMTimeoutError,
        ),
    ],
)
def test_openai_compatibile_traduce_gli_errori_sdk(
    sdk_error: Exception, expected: type[LLMError]
) -> None:
    provider = _failing_openai_compatible(sdk_error)
    with pytest.raises(expected):
        provider.complete("sys", [Message(role="user", content="x")])


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (401, LLMAuthenticationError),
        (403, LLMAuthenticationError),
        (429, LLMRateLimitError),
        (400, LLMBadRequestError),
    ],
)
def test_gemini_traduce_gli_errori_per_codice(code: int, expected: type[LLMError]) -> None:
    provider = GeminiProvider(api_key=SecretStr("k"), max_retries=1)
    client = MagicMock()
    client.models.generate_content.side_effect = genai_errors.ClientError(
        code, {"error": {"message": "errore di test"}}
    )
    provider._client = client

    with pytest.raises(expected):
        provider.complete("sys", [Message(role="user", content="x")])


def test_gemini_timeout_e_ritentabile() -> None:
    provider = GeminiProvider(api_key=SecretStr("k"), max_retries=1)
    client = MagicMock()
    client.models.generate_content.side_effect = httpx.ReadTimeout("troppo lento")
    provider._client = client

    with pytest.raises(LLMTimeoutError):
        provider.complete("sys", [Message(role="user", content="x")])


def test_ollama_server_irraggiungibile_da_errore_leggibile() -> None:
    provider = OllamaProvider(max_retries=1)
    client = MagicMock()
    client.chat.side_effect = httpx.ConnectError("connection refused")
    provider._client = client

    with pytest.raises(LLMConnectionError, match="in esecuzione"):
        provider.complete("sys", [Message(role="user", content="x")])


def test_ollama_modello_mancante_suggerisce_il_pull() -> None:
    provider = OllamaProvider(max_retries=1)
    client = MagicMock()
    client.chat.side_effect = ollama.ResponseError("model not found", 404)
    provider._client = client

    with pytest.raises(LLMBadRequestError, match="ollama pull"):
        provider.complete("sys", [Message(role="user", content="x")])


def test_ollama_estrae_il_contenuto_e_usa_num_predict() -> None:
    provider = OllamaProvider(max_retries=1)
    response = MagicMock()
    response.message.content = "risposta locale"
    client = MagicMock()
    client.chat.return_value = response
    provider._client = client

    result = provider.complete("sys", [Message(role="user", content="x")], max_tokens=512)

    assert result == "risposta locale"
    assert client.chat.call_args.kwargs["options"]["num_predict"] == 512


def test_ogni_errore_ritentabile_e_sottoclasse_di_llm_error() -> None:
    from biocatalyst.llm import RETRYABLE_ERRORS

    assert all(issubclass(e, LLMError) for e in RETRYABLE_ERRORS)
    # Autenticazione e richieste malformate non devono mai essere ritentate.
    assert LLMAuthenticationError not in RETRYABLE_ERRORS
    assert LLMBadRequestError not in RETRYABLE_ERRORS
    assert LLMConfigurationError not in RETRYABLE_ERRORS


def test_openai_compatibile_token_esauriti_non_e_ritentabile() -> None:
    """Un modello di ragionamento può esaurire i token prima di produrre testo:
    ritentare con lo stesso max_tokens fallirebbe identicamente, a pagamento."""
    provider = DeepSeekProvider(api_key=SecretStr("k"), max_retries=3)
    provider.retry_initial_wait = 0.0
    choice = MagicMock()
    choice.message.content = ""
    choice.finish_reason = "length"
    response = MagicMock()
    response.choices = [choice]
    client = MagicMock()
    client.chat.completions.create.return_value = response
    provider._client = client

    with pytest.raises(LLMBadRequestError, match="budget di token esaurito"):
        provider.complete("sys", [Message(role="user", content="x")], max_tokens=20)

    # Una sola chiamata: l'errore è definitivo, non transitorio.
    assert client.chat.completions.create.call_count == 1


def test_anthropic_token_esauriti_non_e_ritentabile() -> None:
    provider = AnthropicProvider(api_key=SecretStr("k"), max_retries=3)
    provider.retry_initial_wait = 0.0
    response = _text_response("", stop_reason="max_tokens")
    client = MagicMock()
    client.messages.create.return_value = response
    provider._client = client

    with pytest.raises(LLMBadRequestError, match="budget di token esaurito"):
        provider.complete("sys", [Message(role="user", content="x")], max_tokens=20)

    assert client.messages.create.call_count == 1


# --- Ripetibilità: cache delle risposte ---------------------------------------


def test_stesso_prompt_stessa_risposta_senza_richiamare_il_modello(tmp_path: Path) -> None:
    """È il rimedio vero alla varianza fra due esecuzioni.

    Misurato sull'API DeepSeek: `temperature=0` e `seed` vengono accettati ma
    non rendono deterministici i modelli di ragionamento (su tre chiamate
    identiche la probabilità bull è uscita 0,70 / 0,15 / 0,55). Riusare la
    risposta a parità di prompt lo garantisce invece per costruzione.
    """
    cache = DataCache(tmp_path / "llm")
    provider = FakeProvider(api_key=SecretStr("k"), cache=cache)
    messaggi = [Message(role="user", content="analizza SLS")]

    prima = provider.complete("sys", messaggi)
    seconda = provider.complete("sys", messaggi)

    assert prima == seconda
    assert provider.calls == 1, "la seconda risposta deve venire dalla cache"


def test_un_prompt_diverso_non_riusa_la_risposta(tmp_path: Path) -> None:
    """Il prompt contiene i dati raccolti: se cambiano, il report si rifà."""
    cache = DataCache(tmp_path / "llm")
    provider = FakeProvider(api_key=SecretStr("k"), cache=cache)

    provider.complete("sys", [Message(role="user", content="prezzo 13.85")])
    provider.complete("sys", [Message(role="user", content="prezzo 14.20")])

    assert provider.calls == 2


def test_la_chiave_distingue_modello_e_parametri(tmp_path: Path) -> None:
    """Due modelli diversi non devono condividere una risposta."""
    cache = DataCache(tmp_path / "llm")
    uno = FakeProvider(api_key=SecretStr("k"), model="a", cache=cache)
    due = FakeProvider(api_key=SecretStr("k"), model="b", cache=cache)
    messaggi = [Message(role="user", content="x")]

    chiave_uno = uno._cache_key("sys", messaggi, 100, 0.0, {})
    chiave_due = due._cache_key("sys", messaggi, 100, 0.0, {})
    assert chiave_uno != chiave_due

    # E nemmeno max_tokens o temperature diversi.
    assert uno._cache_key("sys", messaggi, 100, 0.0, {}) != uno._cache_key(
        "sys", messaggi, 200, 0.0, {}
    )
    assert uno._cache_key("sys", messaggi, 100, 0.0, {}) != uno._cache_key(
        "sys", messaggi, 100, 0.7, {}
    )


def test_senza_cache_il_modello_viene_richiamato() -> None:
    provider = FakeProvider(api_key=SecretStr("k"))
    provider.complete("sys", [Message(role="user", content="x")])
    provider.complete("sys", [Message(role="user", content="x")])
    assert provider.calls == 2


def test_un_errore_non_viene_messo_in_cache(tmp_path: Path) -> None:
    """Un guasto transitorio non deve restare congelato per un giorno."""
    cache = DataCache(tmp_path / "llm")
    provider = FakeProvider(
        errors=[LLMRateLimitError("429")], api_key=SecretStr("k"), cache=cache, max_retries=1
    )
    with pytest.raises(LLMRateLimitError):
        provider.complete("sys", [Message(role="user", content="x")])

    provider.errors = []
    assert provider.complete("sys", [Message(role="user", content="x")]) is not None


def test_ttl_non_positivo_disattiva_la_cache_delle_risposte(tmp_path: Path) -> None:
    """È il modo documentato per forzare una risposta nuova (CACHE_TTL_LLM_SECONDS=0)."""
    cache = DataCache(tmp_path / "llm")
    provider = FakeProvider(api_key=SecretStr("k"), cache=cache, cache_ttl_seconds=0)

    provider.complete("sys", [Message(role="user", content="x")])
    provider.complete("sys", [Message(role="user", content="x")])

    assert provider.calls == 2
