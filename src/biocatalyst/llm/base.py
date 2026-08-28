from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, SecretStr
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from biocatalyst.config import LLMProviderName
from biocatalyst.data.cache import DataCache
from biocatalyst.log import get_logger

logger = get_logger(__name__)

DEFAULT_MAX_TOKENS = 16_000


class Message(BaseModel):
    """Un turno di conversazione. Il system prompt viaggia separato, non qui dentro."""

    role: Literal["user", "assistant"]
    content: str


# --- Gerarchia errori ---------------------------------------------------------
# Ogni provider traduce le eccezioni del proprio SDK in queste, così il codice
# chiamante (e la policy di retry) non dipende da quale provider è configurato.


class LLMError(Exception):
    """Errore generico del layer LLM."""


class LLMConfigurationError(LLMError):
    """Configurazione non valida: API key mancante, provider sconosciuto. Non ritentabile."""


class LLMAuthenticationError(LLMError):
    """Credenziali rifiutate (401/403). Non ritentabile: ritentare non cambia l'esito."""


class LLMBadRequestError(LLMError):
    """Richiesta malformata o rifiutata (400). Non ritentabile."""


class LLMRateLimitError(LLMError):
    """Rate limit raggiunto (429). Ritentabile con backoff."""


class LLMTimeoutError(LLMError):
    """Timeout della richiesta. Ritentabile."""


class LLMConnectionError(LLMError):
    """Errore di rete. Ritentabile."""


class LLMServerError(LLMError):
    """Errore lato provider (5xx). Ritentabile."""


class LLMEmptyResponseError(LLMError):
    """Il modello ha risposto senza contenuto testuale. Ritentabile."""


RETRYABLE_ERRORS: tuple[type[LLMError], ...] = (
    LLMRateLimitError,
    LLMTimeoutError,
    LLMConnectionError,
    LLMServerError,
    LLMEmptyResponseError,
)


class BaseLLMProvider(ABC):
    """Interfaccia comune a tutti i provider.

    Le sottoclassi implementano solo `_complete`: retry, backoff e logging sono
    gestiti qui una volta sola, così ogni provider si comporta allo stesso modo.
    """

    name: ClassVar[LLMProviderName]
    default_model: ClassVar[str]

    #: Anthropic ha rimosso temperature/top_p/top_k da messages.create() nella
    #: release 1.x dell'SDK (passarli solleva TypeError). I provider che non lo
    #: supportano lo dichiarano qui e il parametro viene scartato con un warning
    #: invece di far esplodere la chiamata.
    supports_temperature: ClassVar[bool] = True

    #: Se il provider accetta un `seed` per rendere ripetibile il
    #: campionamento. Lo espone solo chi parla il protocollo OpenAI; sugli
    #: altri il parametro viene scartato con un warning, come `temperature`.
    #: Nemmeno dove è accettato garantisce output identici — riduce la
    #: dispersione, non la azzera.
    supports_seed: ClassVar[bool] = False

    #: Se il provider accetta `response_format={"type": "json_object"}`,
    #: che rende molto più affidabile l'output strutturato.
    supports_json_mode: ClassVar[bool] = False

    #: Se il provider sa rispondere in streaming. Serve a non far scadere le
    #: risposte lunghe dietro i proxy che chiudono le connessioni inattive
    #: (Streamlit Community Cloud taglia a ~60s): in streaming i byte
    #: continuano ad arrivare e il timeout di lettura non scatta mai.
    supports_streaming: ClassVar[bool] = False

    #: Parametri del backoff esponenziale. Sono attributi di classe (e non
    #: costanti inline) per poterli azzerare nei test senza attese reali.
    retry_initial_wait: ClassVar[float] = 1.0
    retry_max_wait: ClassVar[float] = 30.0

    def __init__(
        self,
        *,
        model: str | None = None,
        api_key: SecretStr | None = None,
        timeout: int = 60,
        max_retries: int = 3,
        stream: bool = False,
        cache: DataCache | None = None,
        cache_ttl_seconds: int = 86_400,
    ) -> None:
        self.model = model or self.default_model
        self._api_key = api_key
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.stream = stream and self.supports_streaming
        self.cache = cache
        self.cache_ttl_seconds = cache_ttl_seconds

    def __repr__(self) -> str:
        # Nessuna API key nel repr: questo oggetto può finire in un log o in un traceback.
        return f"{type(self).__name__}(model={self.model!r}, timeout={self.timeout})"

    @property
    def api_key_value(self) -> str:
        """Valore della API key. Solleva se assente, invece di chiamare l'API senza credenziali."""
        if self._api_key is None:
            raise LLMConfigurationError(
                f"Provider '{self.name.value}' richiede una API key ma non è configurata. "
                f"Impostala nel file .env."
            )
        return self._api_key.get_secret_value()

    def complete(
        self,
        system: str,
        messages: list[Message],
        *,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float | None = None,
        seed: int | None = None,
        **kwargs: Any,
    ) -> str:
        """Esegue una completion, con retry automatico sugli errori transitori."""
        if seed is not None:
            if self.supports_seed:
                kwargs["seed"] = seed
            else:
                logger.warning(
                    "seed_non_supportato_ignorato",
                    provider=self.name.value,
                    model=self.model,
                )
        if temperature is not None and not self.supports_temperature:
            logger.warning(
                "temperature_non_supportata_ignorata",
                provider=self.name.value,
                model=self.model,
                motivo="il provider non accetta questo parametro",
            )
            temperature = None

        def esegui() -> str:
            retryer: Retrying = Retrying(
                stop=stop_after_attempt(self.max_retries),
                wait=wait_exponential_jitter(
                    initial=self.retry_initial_wait, max=self.retry_max_wait
                ),
                retry=retry_if_exception_type(RETRYABLE_ERRORS),
                before_sleep=self._log_retry,
                reraise=True,
            )
            risposta: str = retryer(
                self._complete,
                system,
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
                **kwargs,
            )
            return risposta

        # TTL non positivo = cache disattivata: è il modo documentato per
        # forzare una risposta nuova senza toccare il resto della cache.
        if self.cache is None or self.cache_ttl_seconds <= 0:
            return esegui()
        return self.cache.get_or_fetch(
            self._cache_key(system, messages, max_tokens, temperature, kwargs),
            self.cache_ttl_seconds,
            esegui,
        )

    def _cache_key(
        self,
        system: str,
        messages: list[Message],
        max_tokens: int,
        temperature: float | None,
        kwargs: dict[str, Any],
    ) -> str:
        """Impronta della richiesta: identifica una risposta riutilizzabile.

        Comprende il prompt per intero, e il prompt contiene i dati raccolti:
        cambiando il prezzo o arrivando un nuovo filing la chiave cambia da
        sola e il report si rigenera. Finché i dati sono gli stessi, invece, la
        risposta è la stessa — che è precisamente ciò che serve perché due
        esecuzioni ravvicinate non diano numeri diversi.
        """
        impronta = json.dumps(
            {
                "provider": self.name.value,
                "model": self.model,
                "system": system,
                "messages": [(m.role, m.content) for m in messages],
                "max_tokens": max_tokens,
                "temperature": temperature,
                "kwargs": {k: str(v) for k, v in sorted(kwargs.items())},
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return f"llm:{hashlib.sha256(impronta.encode()).hexdigest()[:32]}"

    def _log_retry(self, retry_state: RetryCallState) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        logger.warning(
            "llm_retry",
            provider=self.name.value,
            model=self.model,
            tentativo=retry_state.attempt_number,
            tentativi_totali=self.max_retries,
            errore=type(exc).__name__ if exc else None,
            dettaglio=str(exc) if exc else None,
        )

    @abstractmethod
    def _complete(
        self,
        system: str,
        messages: list[Message],
        *,
        max_tokens: int,
        temperature: float | None,
        **kwargs: Any,
    ) -> str:
        """Singolo tentativo di completion. Deve tradurre gli errori dell'SDK in LLMError."""
