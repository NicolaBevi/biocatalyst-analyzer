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
            f"- Patologia: {', '.join(trial.condition) or 'non specificata'}\n\n"
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


def _lead_trial(raw: CompanyRawData, catalysts: Sequence[Catalyst]) -> ClinicalTrial | None:
    """Studio su cui concentrare l'analisi: quello col catalizzatore più vicino.

    Se nessuno studio ha un catalizzatore futuro si ripiega sullo studio in
    fase più avanzata, perché è comunque l'asset più rilevante da descrivere.
    """
    if catalysts:
        first = catalysts[0]
        nct_id = first.source.split()[-1]
        for trial in raw.clinical_trials:
            if trial.nct_id == nct_id:
                return trial

    if not raw.clinical_trials:
        return None
    phase_rank = {"PHASE4": 4, "PHASE3": 3, "PHASE2": 2, "PHASE1": 1, "EARLY_PHASE1": 0}
    return max(
        raw.clinical_trials,
        key=lambda t: max((phase_rank.get(p, -1) for p in t.phase), default=-1),
    )
