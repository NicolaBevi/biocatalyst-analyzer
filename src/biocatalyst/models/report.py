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

Rating = Literal["BUY", "HOLD", "SELL"]

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
    investment_eur: float = Field(gt=0)
    shares_purchasable: float = Field(ge=0)
    expected_value_eur: float
    expected_roi_pct: float


class ExpectedValueAnalysis(BaseModel):
    eur_usd_rate: float = Field(gt=0)
    rate_date: date
    rows: list[ExpectedValueRow]


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


class ReportSections(BaseModel):
    """Prosa in italiano scritta dal ReportWriterAgent."""

    pipeline_and_clinical_results: str
    catalyst_analysis: str
    operational_strategy: str


class Report(BaseModel):
    ticker: str
    company_name: str | None = None
    report_date: date
    current_price: float = Field(gt=0)
    rating: Rating
    average_analyst_target: float | None = Field(default=None, gt=0)
    main_catalyst: str
    sections: ReportSections
    financial_metrics: FinancialMetrics
    catalysts: list[Catalyst]
    scenarios: ScenarioAnalysis
    expected_value: ExpectedValueAnalysis
    acquisition: AcquisitionAssessment
    tam: TAMEstimate
    source_quality: SourceQuality
    disclaimer: str = DEFAULT_DISCLAIMER
