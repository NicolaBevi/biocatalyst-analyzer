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

from biocatalyst.models.raw_data import SectorSentiment


class FinancialMetrics(BaseModel):
    cash_runway_months: float | None = Field(default=None, ge=0)
    quarterly_burn_rate_usd: float | None = Field(default=None, ge=0)
    short_squeeze_score: float = Field(ge=0, le=100)
    dilution_risk_score: float = Field(ge=0, le=100)
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
    tam_low_usd: float | None = Field(default=None, ge=0)
    tam_high_usd: float | None = Field(default=None, ge=0)
    methodology_notes: str


class MarketContext(BaseModel):
    """Output del MarketNewsAgent: contesto di mercato, con fatti e speculazione
    tenuti esplicitamente separati."""

    sector_sentiment: list[SectorSentiment] = Field(default_factory=list)
    macro_notes: str
    verified_facts: list[str] = Field(default_factory=list)
    market_speculation: list[str] = Field(default_factory=list)
    acquisition_rumors: list[str] = Field(default_factory=list)
