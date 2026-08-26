"""Provider che parlano il protocollo OpenAI Chat Completions.

DeepSeek e Groq espongono endpoint compatibili con l'SDK OpenAI: cambiano solo
`base_url` e il nome del modello. Tenerli qui evita di triplicare la stessa
logica di traduzione degli errori in tre file quasi identici.
"""

from __future__ import annotations

from typing import Any, ClassVar

import openai
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam

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


class OpenAICompatibleProvider(BaseLLMProvider):
    """Base per qualunque endpoint che implementi /chat/completions in stile OpenAI."""

    #: None = usa l'endpoint di default dell'SDK (OpenAI stesso).
    base_url: ClassVar[str | None] = None

    #: I modelli recenti di OpenAI accettano `max_completion_tokens` al posto
    #: dello storico `max_tokens`; i cloni compatibili (DeepSeek, Groq) invece
    #: accettano `max_tokens`. Il nome del parametro è quindi per-provider.
    max_tokens_param: ClassVar[str] = "max_tokens"

    #: Verificato su DeepSeek: l'endpoint chat/completions accetta
    #: response_format={"type": "json_object"}.
    supports_json_mode: ClassVar[bool] = True

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._client: openai.OpenAI | None = None

    @property
    def client(self) -> openai.OpenAI:
        if self._client is None:
            # max_retries=0: il retry è centralizzato in BaseLLMProvider (tenacity).
            self._client = openai.OpenAI(
                api_key=self.api_key_value,
                base_url=self.base_url,
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
        payload: dict[str, Any] = {self.max_tokens_param: max_tokens, **kwargs}
        if temperature is not None:
            payload["temperature"] = temperature

        # I ruoli vanno distinti esplicitamente: l'SDK tipizza ogni ruolo con una
        # TypedDict diversa, quindi un dict costruito in modo generico non è valido.
        sdk_messages: list[ChatCompletionMessageParam] = [{"role": "system", "content": system}]
        for message in messages:
            if message.role == "user":
                sdk_messages.append({"role": "user", "content": message.content})
            else:
                sdk_messages.append({"role": "assistant", "content": message.content})

        try:
            # Annotazione esplicita: `**payload` è dict[str, Any] e senza di essa
            # il tipo di ritorno collasserebbe ad Any, disattivando i controlli.
            response: ChatCompletion = self.client.chat.completions.create(
                model=self.model,
                messages=sdk_messages,
                **payload,
            )
        except openai.AuthenticationError as exc:
            raise LLMAuthenticationError(
                f"{self.name.value}: credenziali rifiutate ({exc})"
            ) from exc
        except openai.PermissionDeniedError as exc:
            raise LLMAuthenticationError(
                f"{self.name.value}: permessi insufficienti ({exc})"
            ) from exc
        except openai.RateLimitError as exc:
            raise LLMRateLimitError(f"{self.name.value}: rate limit ({exc})") from exc
        except openai.BadRequestError as exc:
            raise LLMBadRequestError(f"{self.name.value}: richiesta rifiutata ({exc})") from exc
        except openai.NotFoundError as exc:
            raise LLMBadRequestError(
                f"{self.name.value}: modello o endpoint inesistente ({exc})"
            ) from exc
        except openai.APITimeoutError as exc:
            raise LLMTimeoutError(f"{self.name.value}: timeout dopo {self.timeout}s") from exc
        except openai.APIConnectionError as exc:
            raise LLMConnectionError(f"{self.name.value}: errore di rete ({exc})") from exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise LLMServerError(f"{self.name.value}: errore server {exc.status_code}") from exc
            raise LLMError(f"{self.name.value}: errore API {exc.status_code} ({exc})") from exc

        if not response.choices:
            raise LLMEmptyResponseError(f"{self.name.value}: risposta senza choices")

        content = response.choices[0].message.content
        if content is None or not content.strip():
            finish_reason = response.choices[0].finish_reason
            if finish_reason == "length":
                # Caso tipico dei modelli di ragionamento: il budget di token si
                # esaurisce nel reasoning interno e non ne resta per la risposta.
                # Ritentare con lo stesso max_tokens fallirebbe allo stesso modo,
                # quindi è un errore definitivo e non ritentabile.
                raise LLMBadRequestError(
                    f"{self.name.value}: nessun testo prodotto, budget di token esaurito "
                    f"(max_tokens={max_tokens}). Con un modello di ragionamento serve un "
                    f"max_tokens più alto."
                )
            raise LLMEmptyResponseError(
                f"{self.name.value}: risposta senza testo (finish_reason={finish_reason})"
            )
        return content


class OpenAIProvider(OpenAICompatibleProvider):
    name: ClassVar[LLMProviderName] = LLMProviderName.OPENAI
    default_model: ClassVar[str] = "gpt-4.1"
    max_tokens_param: ClassVar[str] = "max_completion_tokens"


class DeepSeekProvider(OpenAICompatibleProvider):
    name: ClassVar[LLMProviderName] = LLMProviderName.DEEPSEEK
    default_model: ClassVar[str] = "deepseek-chat"
    base_url: ClassVar[str | None] = "https://api.deepseek.com/v1"


class GroqProvider(OpenAICompatibleProvider):
    name: ClassVar[LLMProviderName] = LLMProviderName.GROQ
    default_model: ClassVar[str] = "llama-3.3-70b-versatile"
    base_url: ClassVar[str | None] = "https://api.groq.com/openai/v1"
