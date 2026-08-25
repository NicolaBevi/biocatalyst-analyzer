from __future__ import annotations

from typing import Any, ClassVar

import httpx
from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

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


class GeminiProvider(BaseLLMProvider):
    name: ClassVar[LLMProviderName] = LLMProviderName.GEMINI
    default_model: ClassVar[str] = "gemini-2.5-flash"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._client: genai.Client | None = None

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            self._client = genai.Client(
                api_key=self.api_key_value,
                # HttpOptions.timeout è espresso in millisecondi, non secondi.
                http_options=genai_types.HttpOptions(timeout=self.timeout * 1000),
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
        # Gemini chiama "model" il ruolo che gli altri provider chiamano "assistant".
        # list[...] è invariante: va dichiarato con il tipo-elemento esatto che
        # l'SDK si aspetta, altrimenti list[Content] non è assegnabile.
        contents: list[genai_types.ContentUnionDict] = [
            genai_types.Content(
                role="model" if m.role == "assistant" else "user",
                parts=[genai_types.Part(text=m.content)],
            )
            for m in messages
        ]
        config = genai_types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config=config,
            )
        except genai_errors.ClientError as exc:
            raise self._map_client_error(exc) from exc
        except genai_errors.ServerError as exc:
            raise LLMServerError(f"Gemini: errore server ({exc})") from exc
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError(f"Gemini: timeout dopo {self.timeout}s") from exc
        except httpx.TransportError as exc:
            raise LLMConnectionError(f"Gemini: errore di rete ({exc})") from exc
        except genai_errors.APIError as exc:
            raise LLMError(f"Gemini: errore API ({exc})") from exc

        text = response.text
        if text is None or not text.strip():
            raise LLMEmptyResponseError("Gemini: risposta senza testo")
        return text

    @staticmethod
    def _map_client_error(exc: genai_errors.ClientError) -> LLMError:
        code = getattr(exc, "code", None)
        if code in (401, 403):
            return LLMAuthenticationError(f"Gemini: credenziali rifiutate ({exc})")
        if code == 429:
            return LLMRateLimitError(f"Gemini: rate limit ({exc})")
        return LLMBadRequestError(f"Gemini: richiesta rifiutata (codice {code}: {exc})")
