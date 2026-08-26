from __future__ import annotations

from typing import Any, ClassVar

import anthropic

from biocatalyst.config import LLMProviderName
from biocatalyst.llm.base import (
    BaseLLMProvider,
    LLMAuthenticationError,
    LLMBadRequestError,
    LLMConnectionError,
    LLMEmptyResponseError,
    LLMError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
    Message,
)


class AnthropicProvider(BaseLLMProvider):
    name: ClassVar[LLMProviderName] = LLMProviderName.ANTHROPIC
    default_model: ClassVar[str] = "claude-opus-5"

    #: L'SDK anthropic 1.x ha rimosso temperature/top_p/top_k dalla signature di
    #: messages.create(): passarli solleva TypeError lato client (e i modelli
    #: recenti rispondono comunque 400).
    supports_temperature: ClassVar[bool] = False

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._client: anthropic.Anthropic | None = None

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:
            # max_retries=0: la policy di retry è centralizzata in BaseLLMProvider
            # (tenacity). Lasciare attivo anche il retry interno dell'SDK
            # moltiplicherebbe i tentativi (3 x 2 = 6) e i costi.
            self._client = anthropic.Anthropic(
                api_key=self.api_key_value,
                timeout=float(self.timeout),
                max_retries=0,
            )
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
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": m.role, "content": m.content} for m in messages],
                **kwargs,
            )
        except anthropic.AuthenticationError as exc:
            raise LLMAuthenticationError(f"Anthropic: credenziali rifiutate ({exc})") from exc
        except anthropic.PermissionDeniedError as exc:
            raise LLMAuthenticationError(f"Anthropic: permessi insufficienti ({exc})") from exc
        except anthropic.RateLimitError as exc:
            raise LLMRateLimitError(f"Anthropic: rate limit ({exc})") from exc
        except anthropic.BadRequestError as exc:
            raise LLMBadRequestError(f"Anthropic: richiesta rifiutata ({exc})") from exc
        except anthropic.NotFoundError as exc:
            raise LLMBadRequestError(f"Anthropic: modello o endpoint inesistente ({exc})") from exc
        except anthropic.APITimeoutError as exc:
            raise LLMTimeoutError(f"Anthropic: timeout dopo {self.timeout}s") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMConnectionError(f"Anthropic: errore di rete ({exc})") from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise LLMServerError(f"Anthropic: errore server {exc.status_code}") from exc
            raise LLMError(f"Anthropic: errore API {exc.status_code} ({exc})") from exc

        # Un rifiuto per policy arriva come HTTP 200 con stop_reason="refusal":
        # senza questo controllo si leggerebbe un content vuoto senza capire perché.
        if response.stop_reason == "refusal":
            category = getattr(response.stop_details, "category", None)
            raise LLMBadRequestError(
                f"Anthropic: richiesta rifiutata dai filtri di sicurezza (categoria: {category})"
            )

        text = "".join(block.text for block in response.content if block.type == "text")
        if not text.strip():
            if response.stop_reason == "max_tokens":
                # Budget esaurito prima di produrre testo: ritentare identicamente
                # fallirebbe allo stesso modo, quindi non è un errore transitorio.
                raise LLMBadRequestError(
                    f"Anthropic: nessun testo prodotto, budget di token esaurito "
                    f"(max_tokens={max_tokens}). Serve un max_tokens più alto."
                )
            raise LLMEmptyResponseError(
                f"Anthropic: risposta senza testo (stop_reason={response.stop_reason})"
            )
        return text
