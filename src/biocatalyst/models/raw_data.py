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


class ScheduleRevision(BaseModel):
    """Una modifica della data di completamento primario dichiarata a CT.gov."""

    revised_on: date
    previous_date: date | None = None
    new_date: date | None = None

    @property
    def is_postponement(self) -> bool:
        if self.previous_date is None or self.new_date is None:
            return False
        return self.new_date > self.previous_date


class TrialScheduleHistory(BaseModel):
    """Storico delle date di completamento dichiarate per uno studio.

    Sapere che uno studio è "in ritardo di 268 giorni" non dice se è la prima
    volta o la quarta: sono due storie diverse. Uno slittamento isolato è
    rumore, tre rinvii in cinque anni sono un andamento. CT.gov conserva ogni
    revisione del record, quindi la differenza è **misurabile** invece che
    lasciata all'interpretazione del modello.

    Verificato su REGAL (NCT04229979): la data è passata da 2021-12 a 2025-12
    in tre rinvii, quattro anni complessivi.
    """

    nct_id: str
    #: Versioni totali del record, comprese quelle che non toccano le date.
    revisions_total: int = Field(ge=0)
    first_declared_date: date | None = None
    current_declared_date: date | None = None
    changes: list[ScheduleRevision] = Field(default_factory=list)

    @property
    def times_postponed(self) -> int:
        return sum(1 for c in self.changes if c.is_postponement)

    @property
    def total_slip_days(self) -> int | None:
        """Scarto fra la prima data annunciata e quella attuale."""
        if self.first_declared_date is None or self.current_declared_date is None:
            return None
        return (self.current_declared_date - self.first_declared_date).days

    @property
    def total_slip_months(self) -> float | None:
        giorni = self.total_slip_days
        return None if giorni is None else giorni / 30.44


class FDAApproval(BaseModel):
    """Da openFDA /drug/drugsfda.json. Non copre le orphan drug designation
    (vedi CLAUDE.md — omesse dall'MVP, nessuna API le espone)."""

    application_number: str
    sponsor_name: str
    submission_type: str
    approval_date: date | None = None
    product_name: str
    marketing_status: str | None = None


class DrugSpending(BaseModel):
    """Spesa Medicare effettiva per un farmaco (fonte: CMS).

    Serve ad ancorare la stima del TAM a un prezzo reale invece che alla
    memoria del modello. Copre la sola popolazione Medicare, quindi è un
    ordine di grandezza, non un prezzo di listino.
    """

    brand_name: str
    generic_name: str | None = None
    year: int
    avg_spend_per_beneficiary_usd: float = Field(gt=0)
    total_spend_usd: float | None = Field(default=None, ge=0)
    beneficiaries: int | None = Field(default=None, ge=0)
    medicare_part: Literal["B", "D"]


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
