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
from biocatalyst.analysis.base_rates import base_rate_for
from biocatalyst.analysis.catalysts import is_event_driven, materiality, overdue_days
from biocatalyst.data.base import DataProviderError
from biocatalyst.data.factory import DataProviders
from biocatalyst.i18n import t
from biocatalyst.llm.base import BaseLLMProvider, LLMError, Message
from biocatalyst.llm.structured import complete_structured
from biocatalyst.log import get_logger
from biocatalyst.models.analysis import (
    AnalysisBundle,
    Catalyst,
    TAMDraft,
    TAMEstimate,
    TrialAndMarketAssessment,
)
from biocatalyst.models.raw_data import (
    ClinicalTrial,
    CompanyRawData,
    TrialScheduleHistory,
)
from biocatalyst.models.report import ReportLanguage

logger = get_logger(__name__)


class ClinicalFinancialAnalystAgent(BaseAgent):
    name: ClassVar[str] = "ClinicalFinancialAnalyst"
    requires: ClassVar[tuple[str, ...]] = (KEY_RAW_DATA,)

    def __init__(
        self,
        provider: BaseLLMProvider,
        providers: DataProviders | None = None,
        language: ReportLanguage = "en",
        max_tokens: int = 8_000,
        temperature: float | None = 0.0,
        seed: int | None = 1,
    ) -> None:
        self.provider = provider
        self.providers = providers
        self.language = language
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.seed = seed

    def _run(self, context: dict[str, Any]) -> dict[str, Any]:
        raw: CompanyRawData = context[KEY_RAW_DATA]
        notes: list[str] = []

        metrics, metric_notes = compute_financial_metrics(
            raw.quarterly_financials,
            market_data=raw.market_data,
            filing_signals=raw.filing_signals,
            language=self.language,
        )
        notes.extend(metric_notes)

        catalysts = catalysts_from_trials(raw.clinical_trials, language=self.language)
        if not catalysts:
            notes.append(t(self.language, "cat.none_found"))

        lead_trial = _lead_trial(raw, catalysts)

        clinical_assessment = None
        tam = None
        storia = self._schedule_history(lead_trial)
        if lead_trial is not None:
            # Una sola chiamata per entrambe: il contesto del prompt è identico,
            # sdoppiarlo raddoppierebbe i token senza migliorare le risposte.
            assessment = self._assess(raw, lead_trial, notes, storia)
            if assessment is not None:
                clinical_assessment = assessment.clinical
                tam = self._verify_pricing(assessment.tam)
        else:
            notes.append(t(self.language, "agent.no_lead_trial"))

        base_rate = (
            base_rate_for(lead_trial.phase, lead_trial.condition)
            if lead_trial is not None
            else None
        )

        bundle = AnalysisBundle(
            metrics=metrics,
            catalysts=catalysts,
            clinical_assessment=clinical_assessment,
            tam=tam,
            schedule_history=storia,
            base_rate=base_rate,
            notes=notes,
        )
        context[KEY_ANALYSIS] = bundle
        append_missing(context, notes)
        return context

    def _schedule_history(self, trial: ClinicalTrial | None) -> TrialScheduleHistory | None:
        """Storico dei rinvii della data di lettura per lo studio di riferimento.

        Si scarica solo per questo studio, non per l'intera pipeline: sono
        alcune richieste per studio e servono a rispondere a una domanda sola,
        quella sull'asset che pesa davvero sul prezzo.
        """
        if self.providers is None or trial is None:
            return None
        try:
            return self.providers.clinical_trials.get_schedule_history(trial.nct_id)
        except DataProviderError as exc:
            logger.info("storico_date_non_recuperato", errore=str(exc)[:200])
            return None

    def _assess(
        self,
        raw: CompanyRawData,
        trial: ClinicalTrial,
        notes: list[str],
        storia: TrialScheduleHistory | None = None,
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
            f"{_nota_ritardo(trial)}"
            f"{_nota_storico(storia)}\n"
            "Valuta criticamente lo studio e stima il mercato potenziale del farmaco.\n"
            "Nel campo comparable_drug_name indica il NOME COMMERCIALE di un solo "
            "farmaco già approvato e commercializzato negli Stati Uniti che serva da "
            "riferimento di prezzo per questa indicazione."
        )
        try:
            return complete_structured(
                self.provider,
                ANALYST_SYSTEM[self.language],
                [Message(role="user", content=prompt)],
                TrialAndMarketAssessment,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                seed=self.seed,
            )
        except LLMError as exc:
            logger.warning("valutazione_analista_fallita", errore=str(exc)[:300])
            notes.append(t(self.language, "agent.assessment_failed", error=exc))
            return None

    def _verify_pricing(self, bozza: TAMDraft) -> TAMEstimate:
        """Cerca il prezzo reale del comparatore citato dal modello.

        Il modello sceglie quale farmaco sia il comparatore giusto — è un
        giudizio di dominio — ma la cifra la mette il sistema, prendendola dai
        dati di spesa Medicare. Se il farmaco non compare, `verified_pricing`
        resta nullo e il report lo dichiara invece di far passare per dato la
        stima del modello.
        """
        tam = TAMEstimate.model_validate(bozza.model_dump())
        if self.providers is None or not bozza.comparable_drug_name:
            return tam
        try:
            spesa = self.providers.drug_pricing.get_spending(bozza.comparable_drug_name)
        except DataProviderError as exc:
            logger.warning("verifica_prezzo_fallita", errore=str(exc)[:200])
            return tam
        if spesa is None:
            return tam
        logger.info(
            "prezzo_comparatore_verificato",
            farmaco=spesa.brand_name,
            spesa_per_beneficiario=round(spesa.avg_spend_per_beneficiary_usd),
            anno=spesa.year,
        )
        return tam.model_copy(update={"verified_pricing": spesa})


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


def _nota_storico(storia: TrialScheduleHistory | None) -> str:
    """Espone quante volte la data di lettura è già stata spostata.

    È la differenza fra un episodio e un andamento: un rinvio isolato è
    rumore, tre rinvii in cinque anni descrivono uno studio che procede più
    lentamente del previsto fin dall'inizio. Il dato è misurato dal registro,
    non dedotto — al modello si chiede solo di interpretarlo.
    """
    if storia is None or not storia.changes:
        return ""
    righe = "; ".join(
        f"il {c.revised_on} da {c.previous_date} a {c.new_date}" for c in storia.changes
    )
    mesi = storia.total_slip_months
    testo = (
        f"- STORICO DELLE DATE (fonte: registro CT.gov, dato misurato): la data di "
        f"completamento è stata modificata {len(storia.changes)} volte — {righe}."
    )
    if mesi is not None and mesi > 0:
        testo += (
            f" Dalla prima data annunciata ({storia.first_declared_date}) a quella "
            f"attuale ({storia.current_declared_date}) sono {mesi:.0f} mesi di slittamento."
        )
    testo += (
        " Tieni conto di questo andamento nel valutare il ritardo: un rinvio isolato "
        "e una serie di rinvii ripetuti non hanno lo stesso significato.\n"
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
