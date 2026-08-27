"""Report finale (ReportWriterAgent), modalità analyze.

Le sezioni narrative (ReportSections) sono testo libero in italiano scritto
dall'LLM. Expected value e variazione percentuale dei target sono invece
sempre calcolati in Python (analysis/, Fase 4): l'LLM fornisce solo
probabilità e target price grezzi, mai l'aritmetica finale.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Self

from pydantic import BaseModel, Field, model_validator

from biocatalyst.models.analysis import Catalyst, FinancialMetrics, TAMEstimate
from biocatalyst.models.raw_data import MarketData

Rating = Literal["BUY", "HOLD", "SELL"]

#: Lingua del report, scelta dall'utente. Riguarda solo i testi prodotti:
#: i dati numerici e le fonti restano identici.
ReportLanguage = Literal["en", "it"]

DEFAULT_DISCLAIMER = (
    "Questo report ha finalità puramente informative. È generato in parte da "
    "modelli linguistici e da dati di fonti pubbliche e non costituisce "
    "consulenza finanziaria, raccomandazione di investimento o invito a "
    "investire. Verifica sempre i dati con le fonti primarie prima di "
    "qualsiasi decisione."
)


class Scenario(BaseModel):
    probability: float = Field(ge=0, le=1)
    target_price: float = Field(gt=0)
    # Calcolata in Python da current_price, mai chiesta all'LLM.
    target_price_change_pct: float
    conditions: str


class ScenarioAnalysis(BaseModel):
    bull: Scenario
    base: Scenario
    bear: Scenario

    @model_validator(mode="after")
    def _check_probabilities_sum_to_one(self) -> Self:
        total = self.bull.probability + self.base.probability + self.bear.probability
        if abs(total - 1.0) > 0.01:
            raise ValueError(
                f"Le probabilità di bull+base+bear devono sommare a 1.0, non {total:.3f}"
            )
        return self


class ExpectedValueRow(BaseModel):
    """Una riga della tabella del valore atteso, in dollari.

    Il titolo quota in dollari: calcolare in quella valuta evita di introdurre
    un'assunzione sul cambio dentro il risultato dell'investimento.
    """

    investment_usd: float = Field(gt=0)
    shares_purchasable: float = Field(ge=0)
    expected_value_usd: float
    expected_roi_pct: float


class ExpectedValueAnalysis(BaseModel):
    rows: list[ExpectedValueRow]
    #: Cambio di riferimento, puramente informativo: serve a un lettore in area
    #: euro per sapere quanto vale l'importo in dollari, non entra nel calcolo.
    eur_usd_rate: float | None = Field(default=None, gt=0)
    rate_date: date | None = None


class AcquisitionAssessment(BaseModel):
    probability_pct: float = Field(ge=0, le=100)
    potential_acquirers: list[str] = Field(default_factory=list)
    comparable_deals: list[str] = Field(default_factory=list)


class SourceEntry(BaseModel):
    name: str
    retrieved_at: datetime


class SourceQuality(BaseModel):
    sources_consulted: list[SourceEntry] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    #: Dati presenti ma sospetti (es. un target analisti incoerente col
    #: prezzo). Distinti dai dati mancanti: qui il numero c'è, ma non va
    #: preso per buono senza verificarlo.
    warnings: list[str] = Field(default_factory=list)


class ReportSections(BaseModel):
    """Prosa in italiano scritta dal ReportWriterAgent."""

    pipeline_and_clinical_results: str
    catalyst_analysis: str
    operational_strategy: str


class Report(BaseModel):
    ticker: str
    company_name: str | None = None
    report_date: date
    #: Momento esatto in cui i dati sono stati interrogati. Distinto da
    #: `report_date`: un report rigenerato da cache può avere dati più vecchi
    #: della data di redazione, e il lettore deve poterlo vedere.
    generated_at: datetime
    language: ReportLanguage = "en"
    current_price: float = Field(gt=0)
    rating: Rating
    average_analyst_target: float | None = Field(default=None, gt=0)
    main_catalyst: str
    sections: ReportSections
    financial_metrics: FinancialMetrics
    #: Capitalizzazione, flottante e short interest: il formato del report li
    #: richiede esplicitamente, quindi viaggiano col report invece di restare
    #: nei soli dati grezzi.
    market_snapshot: MarketData | None = None
    catalysts: list[Catalyst]
    scenarios: ScenarioAnalysis
    expected_value: ExpectedValueAnalysis
    acquisition: AcquisitionAssessment
    tam: TAMEstimate
    source_quality: SourceQuality
    disclaimer: str = DEFAULT_DISCLAIMER
