from __future__ import annotations

from typing import Any, ClassVar

import httpx
import ollama

from biocatalyst.config import LLMProviderName
from biocatalyst.llm.base import (
    BaseLLMProvider,
    LLMBadRequestError,
    LLMConnectionError,
    LLMEmptyResponseError,
    LLMServerError,
    LLMTimeoutError,
    Message,
)


class OllamaProvider(BaseLLMProvider):
    """Modelli eseguiti in locale via Ollama: nessuna API key, nessun costo per token.

    `api_key_value` non viene mai invocato da questo provider, quindi il controllo
    sulla chiave mancante ereditato dalla base non si attiva.
    """

    name: ClassVar[LLMProviderName] = LLMProviderName.OLLAMA
    default_model: ClassVar[str] = "llama3.1"

    def __init__(self, *, base_url: str = "http://localhost:11434", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.base_url = base_url
        self._client: ollama.Client | None = None

    @property
    def client(self) -> ollama.Client:
        if self._client is None:
            self._client = ollama.Client(host=self.base_url, timeout=self.timeout)
        return self._client

    def _complete(
        self,
        system: str,
        messages: list[Message],
        *,
        max_tokens: int,
        temperature: float | None,
        **kwargs: Any,
    ) -> str:
        # Ollama accetta il system prompt come primo messaggio con ruolo "system".
        payload = [
            {"role": "system", "content": system},
            *({"role": m.role, "content": m.content} for m in messages),
        ]
        # In Ollama il tetto di token generati si chiama "num_predict".
        options: dict[str, Any] = {"num_predict": max_tokens, **kwargs}
        if temperature is not None:
            options["temperature"] = temperature

        try:
            response = self.client.chat(model=self.model, messages=payload, options=options)
        except ollama.ResponseError as exc:
            status = getattr(exc, "status_code", None)
            if status is not None and status >= 500:
                raise LLMServerError(f"Ollama: errore server {status} ({exc})") from exc
            raise LLMBadRequestError(
                f"Ollama: richiesta rifiutata ({exc}). "
                f"Il modello '{self.model}' è stato scaricato con 'ollama pull'?"
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"Ollama: timeout dopo {self.timeout}s") from exc
        except (httpx.TransportError, ConnectionError) as exc:
            raise LLMConnectionError(
                f"Ollama: impossibile raggiungere il server su {self.base_url} ({exc}). "
                f"È in esecuzione?"
            ) from exc

        content = response.message.content if response.message else None
        if content is None or not content.strip():
            raise LLMEmptyResponseError("Ollama: risposta senza testo")
        return content
