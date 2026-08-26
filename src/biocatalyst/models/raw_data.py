"""Dati grezzi raccolti dal DataCollectorAgent (yfinance, SEC EDGAR, ClinicalTrials.gov, openFDA).

Ogni campo è opzionale: un valore assente va rappresentato con None e elencato
in CompanyRawData.missing_data, mai stimato silenziosamente.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class PricePoint(BaseModel):
    trade_date: date
    close: float = Field(gt=0)


class MarketData(BaseModel):
    price: float | None = Field(default=None, gt=0)
    market_cap_usd: float | None = Field(default=None, ge=0)
    shares_outstanding: float | None = Field(default=None, ge=0)
    float_shares: float | None = Field(default=None, ge=0)
    shares_short: float | None = Field(default=None, ge=0)
    short_ratio_days: float | None = Field(default=None, ge=0)
    short_percent_of_float: float | None = Field(default=None, ge=0)
    # Data di riferimento dello short interest (campo "dateShortInterest" di
    # yfinance). FINRA liquida e pubblica questo dato solo due volte al mese:
    # senza questa data il numero sembra "live" ma può essere vecchio di settimane.
    short_interest_date: date | None = None
    average_volume: float | None = Field(default=None, ge=0)
    #: Target medio degli analisti, richiesto dall'intestazione del report.
    analyst_target_mean: float | None = Field(default=None, gt=0)
    total_cash_usd: float | None = Field(default=None, ge=0)
    total_debt_usd: float | None = Field(default=None, ge=0)
    price_history: list[PricePoint] = Field(default_factory=list)


class QuarterlyFinancials(BaseModel):
    """Una singola voce XBRL da data.sec.gov/api/xbrl/companyfacts."""

    fiscal_year: int
    # "Q4" non esiste come tag XBRL a sé: va derivato per sottrazione
    # (totale FY meno i 9 mesi year-to-date) e marcato come tale qui.
    fiscal_period: Literal["Q1", "Q2", "Q3", "Q4", "FY"]
    period_end: date
    cash_and_equivalents_usd: float | None = Field(default=None, ge=0)
    rd_expense_usd: float | None = Field(default=None, ge=0)
    # Può essere negativo (perdita): tipico per il biotech clinical-stage.
    net_income_loss_usd: float | None = None
    form_type: Literal["10-Q", "10-K"]
    filed_date: date


class SECFilingSignals(BaseModel):
    """Esito della ricerca full-text EDGAR (efts.sec.gov) su un set di filing."""

    atm_offering_mentioned: bool = False
    warrant_mentioned: bool = False
    matching_accession_numbers: list[str] = Field(default_factory=list)
    as_of: date


class ClinicalTrial(BaseModel):
    """Un trial da ClinicalTrials.gov API v2."""

    nct_id: str
    brief_title: str
    # Array come restituito dall'API: un trial può coprire più fasi (es. "Phase 1/2").
    phase: list[str] = Field(default_factory=list)
    overall_status: str
    enrollment_count: int | None = Field(default=None, ge=0)
    enrollment_type: Literal["ACTUAL", "ESTIMATED"] | None = None
    primary_outcome_measure: str | None = None
    #: Data di avvio: serve a dimensionare un eventuale ritardo rispetto alla
    #: durata pianificata. Un ritardo di 9 mesi su uno studio previsto in 12
    #: è un'altra cosa rispetto allo stesso ritardo su uno previsto in 60.
    start_date: date | None = None
    primary_completion_date: date | None = None
    primary_completion_date_type: Literal["ACTUAL", "ESTIMATED"] | None = None
    condition: list[str] = Field(default_factory=list)
    # query.spons di CT.gov trova anche i collaborator: questo campo va
    # popolato solo con il lead sponsor effettivo, filtrato lato client.
    lead_sponsor: str | None = None


class FDAApproval(BaseModel):
    """Da openFDA /drug/drugsfda.json. Non copre le orphan drug designation
    (vedi CLAUDE.md — omesse dall'MVP, nessuna API le espone)."""

    application_number: str
    sponsor_name: str
    submission_type: str
    approval_date: date | None = None
    product_name: str
    marketing_status: str | None = None


class NewsItem(BaseModel):
    """Da Finnhub (fonte primaria) o Google News RSS (fallback opzionale)."""

    headline: str
    source: str
    url: str
    published_at: datetime
    summary: str | None = None


class SectorSentiment(BaseModel):
    """Andamento di un ETF di settore (XBI/IBB) su una finestra temporale."""

    symbol: str
    period_days: int = Field(gt=0)
    price_change_pct: float
    as_of: date


class CompanyRawData(BaseModel):
    """Output del DataCollectorAgent: tutto ciò che è stato raccolto per un ticker."""

    ticker: str
    company_name: str | None = None
    retrieved_at: datetime
    market_data: MarketData | None = None
    quarterly_financials: list[QuarterlyFinancials] = Field(default_factory=list)
    filing_signals: SECFilingSignals | None = None
    clinical_trials: list[ClinicalTrial] = Field(default_factory=list)
    fda_approvals: list[FDAApproval] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
