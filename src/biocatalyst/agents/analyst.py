"""Agente 2: analisi clinica e finanziaria.

Divisione del lavoro deliberata:
- **codice deterministico** per tutto ciò che è calcolabile (burn rate, cash
  runway, score di rischio, ordinamento dei catalizzatori). Un LLM su questi
  numeri introdurrebbe solo errori non rilevabili;
- **LLM** solo per il giudizio qualitativo: solidità del disegno dello studio
  e stima del mercato potenziale, dove serve conoscenza di dominio.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar

from biocatalyst.agents.base import KEY_ANALYSIS, KEY_RAW_DATA, BaseAgent, append_missing
from biocatalyst.agents.prompts import ANALYST_SYSTEM
from biocatalyst.analysis import catalysts_from_trials, compute_financial_metrics
from biocatalyst.analysis.catalysts import is_event_driven, materiality, overdue_days
from biocatalyst.llm.base import BaseLLMProvider, LLMError, Message
from biocatalyst.llm.structured import complete_structured
from biocatalyst.log import get_logger
from biocatalyst.models.analysis import (
    AnalysisBundle,
    Catalyst,
    TrialAndMarketAssessment,
)
from biocatalyst.models.raw_data import ClinicalTrial, CompanyRawData
from biocatalyst.models.report import ReportLanguage

logger = get_logger(__name__)


class ClinicalFinancialAnalystAgent(BaseAgent):
    name: ClassVar[str] = "ClinicalFinancialAnalyst"
    requires: ClassVar[tuple[str, ...]] = (KEY_RAW_DATA,)

    def __init__(
        self,
        provider: BaseLLMProvider,
        language: ReportLanguage = "it",
        max_tokens: int = 8_000,
    ) -> None:
        self.provider = provider
        self.language = language
        self.max_tokens = max_tokens

    def _run(self, context: dict[str, Any]) -> dict[str, Any]:
        raw: CompanyRawData = context[KEY_RAW_DATA]
        notes: list[str] = []

        metrics, metric_notes = compute_financial_metrics(
            raw.quarterly_financials,
            market_data=raw.market_data,
            filing_signals=raw.filing_signals,
        )
        notes.extend(metric_notes)

        catalysts = catalysts_from_trials(raw.clinical_trials)
        if not catalysts:
            notes.append(
                "nessun catalizzatore futuro identificato dai trial registrati "
                "(nessuno studio attivo con data di completamento primario futura)"
            )

        lead_trial = _lead_trial(raw, catalysts)

        clinical_assessment = None
        tam = None
        if lead_trial is not None:
            # Una sola chiamata per entrambe: il contesto del prompt è identico,
            # sdoppiarlo raddoppierebbe i token senza migliorare le risposte.
            assessment = self._assess(raw, lead_trial, notes)
            if assessment is not None:
                clinical_assessment = assessment.clinical
                tam = assessment.tam
        else:
            notes.append(
                "valutazione clinica e TAM non prodotti: nessuno studio di riferimento disponibile"
            )

        bundle = AnalysisBundle(
            metrics=metrics,
            catalysts=catalysts,
            clinical_assessment=clinical_assessment,
            tam=tam,
            notes=notes,
        )
        context[KEY_ANALYSIS] = bundle
        append_missing(context, notes)
        return context

    def _assess(
        self, raw: CompanyRawData, trial: ClinicalTrial, notes: list[str]
    ) -> TrialAndMarketAssessment | None:
        prompt = (
            f"Azienda: {raw.company_name or raw.ticker}\n\n"
            "Studio di riferimento (quello col catalizzatore più vicino):\n"
            f"- Identificativo: {trial.nct_id}\n"
            f"- Titolo: {trial.brief_title}\n"
            f"- Fase: {', '.join(trial.phase) or 'non specificata'}\n"
            f"- Stato: {trial.overall_status}\n"
            f"- Numerosità: {trial.enrollment_count or 'non disponibile'} "
            f"({trial.enrollment_type or 'tipo non indicato'})\n"
            f"- Endpoint primario: {trial.primary_outcome_measure or 'non disponibile'}\n"
            f"- Completamento atteso: {trial.primary_completion_date or 'non disponibile'}\n"
            f"- Patologia: {', '.join(trial.condition) or 'non specificata'}\n"
            f"{_nota_ritardo(trial)}\n"
            "Valuta criticamente lo studio e stima il mercato potenziale del farmaco."
        )
        try:
            return complete_structured(
                self.provider,
                ANALYST_SYSTEM[self.language],
                [Message(role="user", content=prompt)],
                TrialAndMarketAssessment,
                max_tokens=self.max_tokens,
            )
        except LLMError as exc:
            logger.warning("valutazione_analista_fallita", errore=str(exc)[:300])
            notes.append(f"valutazione clinica e stima del TAM non prodotte: {exc}")
            return None


def _nota_ritardo(trial: ClinicalTrial) -> str:
    """Segnala all'analista che lo studio è in ritardo e cosa può significare."""
    giorni = overdue_days(trial)
    if giorni <= 0:
        return ""
    testo = (
        f"- ATTENZIONE: la data stimata di completamento è superata da {giorni} giorni "
        f"e lo studio risulta ancora attivo: la lettura dei dati è attesa, non avvenuta.\n"
    )
    if is_event_driven(trial):
        testo += (
            "- L'endpoint primario è a eventi: la durata dipende dal numero di eventi "
            "verificatisi, non dal calendario. Valuta entrambe le letture possibili di un "
            "ritardo (eventi più lenti del previsto, oppure difficoltà operative) senza "
            "presentarne una come certa.\n"
        )
    return testo


def _lead_trial(raw: CompanyRawData, catalysts: Sequence[Catalyst]) -> ClinicalTrial | None:
    """Studio su cui concentrare l'analisi approfondita.

    Non semplicemente quello con la data più vicina: **quello che pesa di più
    sul prezzo**. Una Fase 3 con lettura fra sei mesi muove il titolo più di
    una Fase 1 che legge domani, e su SELLAS la prima versione di questa
    funzione sceglieva la Fase 1/2 ignorando lo studio di Fase 3 che è la
    ragione principale della valutazione.

    A parità di fase vince il catalizzatore più imminente.
    """
    if catalysts:
        per_nct = {c.source.split()[-1]: c for c in catalysts}
        candidati = [t for t in raw.clinical_trials if t.nct_id in per_nct]
        if candidati:
            scelto = max(
                candidati,
                key=lambda t: (
                    per_nct[t.nct_id].phase_materiality,
                    -per_nct[t.nct_id].imminence_rank,
                ),
            )
            return scelto

    if not raw.clinical_trials:
        return None
    # Nessun catalizzatore atteso: si descrive comunque l'asset più avanzato.
    return max(raw.clinical_trials, key=materiality)
