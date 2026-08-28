"""Output di ClinicalFinancialAnalystAgent e MarketNewsAgent.

Le metriche numeriche (FinancialMetrics) sono calcolate in Python puro in
analysis/ (Fase 4), non dall'LLM — qui viene definita solo la forma del dato.
I campi di testo (ClinicalAssessment, MarketContext.macro_notes) sono invece
la parte qualitativa prodotta dall'LLM.
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from biocatalyst.models.raw_data import DrugSpending, SectorSentiment


class FinancialMetrics(BaseModel):
    """Metriche derivate, calcolate in Python puro (mai chieste all'LLM).

    Gli score sono opzionali: per i micro-cap i dati sullo short interest
    mancano spesso del tutto, e uno zero al posto di un dato assente si
    leggerebbe come "rischio nullo" invece che come "non calcolabile".
    """

    cash_runway_months: float | None = Field(default=None, ge=0)
    quarterly_burn_rate_usd: float | None = Field(default=None, ge=0)
    short_squeeze_score: float | None = Field(default=None, ge=0, le=100)
    dilution_risk_score: float | None = Field(default=None, ge=0, le=100)
    as_of: date


class Catalyst(BaseModel):
    name: str
    catalyst_type: Literal[
        "clinical_readout", "fda_decision", "conference_presentation", "earnings", "other"
    ]
    expected_date: date | None = None
    # Es. "Q2 2026", quando non è nota una data esatta.
    expected_date_window: str | None = None
    source: str
    # Usato per ordinare i catalizzatori per imminenza: 1 = il più vicino.
    imminence_rank: int = Field(ge=1)

    #: Vero se la data stimata è già passata ma lo studio risulta ancora
    #: attivo: la lettura non è avvenuta, è in ritardo. Trattarlo come
    #: concluso farebbe sparire dall'analisi proprio l'asset più atteso.
    is_overdue: bool = False
    overdue_days: int | None = Field(default=None, ge=0)

    #: Vero se l'endpoint primario si misura contando eventi nel tempo
    #: (sopravvivenza globale, sopravvivenza libera da progressione...).
    #: In questi studi la durata non è fissata a calendario: un ritardo può
    #: significare che gli eventi arrivano più lentamente del previsto.
    is_event_driven: bool = False

    #: Fase più avanzata dello studio (0-4), per stabilire quale asset pesa
    #: davvero sul prezzo: una Fase 3 conta più di una Fase 1.
    phase_materiality: int = Field(default=-1, ge=-1, le=4)

    @model_validator(mode="after")
    def _check_has_timing_info(self) -> Self:
        if self.expected_date is None and self.expected_date_window is None:
            raise ValueError(
                "Un catalizzatore deve avere expected_date o expected_date_window: "
                "senza nessuno dei due non è ordinabile per imminenza."
            )
        return self


class ClinicalAssessment(BaseModel):
    """Valutazione qualitativa dell'LLM sul trial con il catalizzatore più vicino."""

    study_design_summary: str
    primary_endpoint_evaluation: str
    population_and_comparator_evaluation: str
    statistical_power_evaluation: str
    historical_precedent_comparison: str


class TAMEstimate(BaseModel):
    indication: str
    prevalence_estimate: str
    pricing_comparable: str
    #: Nome del farmaco comparabile citato dal modello. Serve al sistema per
    #: cercarne il prezzo reale nei dati di spesa Medicare: il modello sceglie
    #: il comparatore (giudizio di dominio), il sistema ne verifica il prezzo.
    comparable_drug_name: str | None = None
    #: Spesa Medicare effettiva per quel farmaco, se reperita. None significa
    #: "non verificabile", e va dichiarato invece di far passare per dato la
    #: cifra del modello.
    verified_pricing: DrugSpending | None = None
    tam_low_usd: float | None = Field(default=None, ge=0)
    tam_high_usd: float | None = Field(default=None, ge=0)
    methodology_notes: str


class TrialAndMarketAssessment(BaseModel):
    """Valutazione clinica e stima del TAM in un unico schema.

    Sono unite di proposito: chiederle in due chiamate separate raddoppierebbe
    il prompt di contesto (identico in entrambe) senza migliorare la qualità
    delle risposte, e i token si pagano.
    """

    clinical: ClinicalAssessment
    tam: TAMEstimate


class AnalysisBundle(BaseModel):
    """Output completo del ClinicalFinancialAnalystAgent.

    Le metriche e i catalizzatori sono deterministici (calcolati in
    `analysis/`); la valutazione clinica e il TAM sono le uniche parti affidate
    all'LLM, e possono mancare se la chiamata fallisce.
    """

    metrics: FinancialMetrics
    catalysts: list[Catalyst] = Field(default_factory=list)
    clinical_assessment: ClinicalAssessment | None = None
    tam: TAMEstimate | None = None
    notes: list[str] = Field(default_factory=list)


class MarketContext(BaseModel):
    """Output del MarketNewsAgent: contesto di mercato, con fatti e speculazione
    tenuti esplicitamente separati."""

    sector_sentiment: list[SectorSentiment] = Field(default_factory=list)
    macro_notes: str
    verified_facts: list[str] = Field(default_factory=list)
    market_speculation: list[str] = Field(default_factory=list)
    acquisition_rumors: list[str] = Field(default_factory=list)
