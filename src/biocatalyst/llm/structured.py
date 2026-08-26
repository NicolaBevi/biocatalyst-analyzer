"""Output strutturato: dalla risposta testuale di un LLM a un modello Pydantic.

Gli agenti hanno bisogno di campi tipizzati, non di prosa da interpretare.
Questo modulo chiede il JSON, lo estrae in modo difensivo e lo valida; se la
validazione fallisce ritenta una volta rimandando al modello l'errore, che è
molto più efficace di ripetere la stessa richiesta identica.
"""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from biocatalyst.llm.base import BaseLLMProvider, LLMError, Message
from biocatalyst.log import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

#: I modelli incapsulano spesso il JSON in un blocco markdown nonostante le
#: istruzioni contrarie: si estrae il contenuto invece di fallire.
_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class LLMStructuredOutputError(LLMError):
    """Il modello non ha prodotto un JSON conforme allo schema richiesto."""


def extract_json(raw: str) -> str:
    """Isola il JSON da una risposta che può contenere fence o testo attorno."""
    fenced = _FENCE_PATTERN.search(raw)
    if fenced:
        return fenced.group(1).strip()

    # Nessun fence: si prende dalla prima graffa aperta all'ultima chiusa.
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end > start:
        return raw[start : end + 1].strip()
    return raw.strip()


def _schema_instructions(schema: type[BaseModel]) -> str:
    return (
        "Rispondi ESCLUSIVAMENTE con un oggetto JSON valido conforme a questo "
        "JSON Schema, senza testo prima o dopo e senza blocchi markdown:\n"
        f"{json.dumps(schema.model_json_schema(), ensure_ascii=False, indent=2)}"
    )


def complete_structured(
    provider: BaseLLMProvider,
    system: str,
    messages: list[Message],
    schema: type[T],
    max_tokens: int = 8_000,
    temperature: float | None = None,
    parse_attempts: int = 2,
) -> T:
    """Ottiene una risposta validata contro `schema`.

    `parse_attempts` conta i tentativi di *parsing*: sono distinti dai retry di
    rete gestiti da `BaseLLMProvider`, perché un JSON malformato non è un
    problema transitorio e va corretto rimandando l'errore al modello.
    """
    full_system = f"{system}\n\n{_schema_instructions(schema)}"
    conversation = list(messages)
    last_error: Exception | None = None

    for attempt in range(1, max(1, parse_attempts) + 1):
        kwargs: dict[str, Any] = {}
        if provider.supports_json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        raw = provider.complete(
            full_system,
            conversation,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs,
        )

        try:
            return schema.model_validate_json(extract_json(raw))
        except (ValidationError, ValueError) as exc:
            last_error = exc
            logger.warning(
                "output_strutturato_non_valido",
                schema=schema.__name__,
                tentativo=attempt,
                tentativi_totali=parse_attempts,
                errore=str(exc)[:300],
            )
            if attempt >= parse_attempts:
                break
            # Si rimanda al modello la sua risposta e l'errore: ripetere la
            # richiesta identica produrrebbe con ogni probabilità lo stesso esito.
            conversation = [
                *messages,
                Message(role="assistant", content=raw[:4000]),
                Message(
                    role="user",
                    content=(
                        "La risposta precedente non è conforme allo schema. "
                        f"Errore di validazione:\n{str(exc)[:1000]}\n\n"
                        "Correggi e restituisci solo il JSON valido."
                    ),
                ),
            ]

    raise LLMStructuredOutputError(
        f"{provider.name.value}: nessun JSON conforme a {schema.__name__} "
        f"dopo {parse_attempts} tentativi. Ultimo errore: {last_error}"
    )
