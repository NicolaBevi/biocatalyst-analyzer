"""Interfaccia comune dei quattro agenti.

Ogni agente riceve e restituisce un dizionario di contesto che si arricchisce
lungo la pipeline: l'agente N legge ciò che hanno prodotto i precedenti. I
valori sono modelli Pydantic, quindi tipizzati e validati; è il contenitore a
essere un dict, per permettere alla pipeline di crescere senza cambiare
l'interfaccia.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, ClassVar

from biocatalyst.log import get_logger

logger = get_logger(__name__)

#: Chiavi del contesto condiviso, centralizzate per non disseminare stringhe.
KEY_TICKER = "ticker"
KEY_RAW_DATA = "raw_data"
KEY_ANALYSIS = "analysis"
KEY_MARKET_CONTEXT = "market_context"
KEY_REPORT = "report"
KEY_MISSING_DATA = "missing_data"


class AgentError(Exception):
    """Fallimento non recuperabile di un agente."""


class BaseAgent(ABC):
    """Base di tutti gli agenti: logging, cronometraggio, contratto uniforme."""

    name: ClassVar[str]
    #: Chiavi che devono essere già presenti nel contesto quando l'agente parte.
    requires: ClassVar[tuple[str, ...]] = ()

    def run(self, context: dict[str, Any]) -> dict[str, Any]:
        """Esegue l'agente e restituisce il contesto arricchito.

        Il contesto in ingresso non viene mutato: ogni agente lavora su una
        copia, così un fallimento a metà pipeline non lascia stati parziali
        confusi nel dizionario del chiamante.
        """
        missing = [key for key in self.requires if key not in context]
        if missing:
            raise AgentError(
                f"L'agente '{self.name}' richiede nel contesto le chiavi {missing}, "
                f"che non sono presenti: la pipeline è stata eseguita fuori ordine?"
            )

        logger.info("agente_avviato", agente=self.name)
        started = time.monotonic()
        try:
            updated = self._run(dict(context))
        except Exception as exc:
            logger.error(
                "agente_fallito",
                agente=self.name,
                errore=type(exc).__name__,
                dettaglio=str(exc)[:500],
                durata_s=round(time.monotonic() - started, 2),
            )
            raise
        logger.info(
            "agente_completato",
            agente=self.name,
            durata_s=round(time.monotonic() - started, 2),
        )
        return updated

    @abstractmethod
    def _run(self, context: dict[str, Any]) -> dict[str, Any]:
        """Logica dell'agente. Riceve una copia del contesto e la restituisce arricchita."""


def append_missing(context: dict[str, Any], entries: list[str]) -> None:
    """Accumula nel contesto i dati non reperiti, senza perdere quelli precedenti."""
    if not entries:
        return
    existing: list[str] = context.setdefault(KEY_MISSING_DATA, [])
    existing.extend(entries)
