"""Agente 1: raccolta dei dati verificabili.

Non usa l'LLM: il suo compito è raccogliere fatti, e un modello linguistico
introdurrebbe solo il rischio di inventarli. Ogni fonte che fallisce diventa
una voce esplicita in `missing_data`, mai una stima silenziosa.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from biocatalyst.agents.base import KEY_RAW_DATA, KEY_TICKER, BaseAgent, append_missing
from biocatalyst.data.base import collect_safely
from biocatalyst.data.factory import DataProviders
from biocatalyst.log import get_logger
from biocatalyst.models.raw_data import CompanyRawData

logger = get_logger(__name__)


class DataCollectorAgent(BaseAgent):
    name: ClassVar[str] = "DataCollector"
    requires: ClassVar[tuple[str, ...]] = (KEY_TICKER,)

    def __init__(self, providers: DataProviders) -> None:
        self.providers = providers

    def _run(self, context: dict[str, Any]) -> dict[str, Any]:
        ticker: str = context[KEY_TICKER]
        missing: list[str] = []
        p = self.providers

        # Il nome ufficiale SEC serve a interrogare ClinicalTrials.gov e openFDA,
        # che indicizzano per ragione sociale e non per ticker.
        company_name = collect_safely(
            "nome società (SEC)", lambda: p.sec.get_company_name(ticker), missing
        )
        if company_name is None:
            company_name = collect_safely(
                "nome società (yfinance)", lambda: p.market.get_company_name(ticker), missing
            )

        market_data = collect_safely(
            "dati di mercato (yfinance)", lambda: p.market.get_market_data(ticker), missing
        )
        financials = collect_safely(
            "bilanci trimestrali (SEC XBRL)",
            lambda: p.sec.get_quarterly_financials(ticker),
            missing,
        )
        filing_signals = collect_safely(
            "segnali ATM/warrant (ricerca full-text SEC)",
            lambda: p.sec.get_filing_signals(ticker),
            missing,
        )

        trials = None
        approvals = None
        if company_name:
            sponsor = _sponsor_query(company_name)
            trials = collect_safely(
                "trial clinici (ClinicalTrials.gov)",
                lambda: p.clinical_trials.get_trials_by_sponsor(sponsor),
                missing,
            )
            approvals = collect_safely(
                "approvazioni farmaci (openFDA)",
                lambda: p.fda.get_approvals_by_sponsor(company_name),
                missing,
            )
        else:
            missing.append(
                "trial clinici e approvazioni FDA: non interrogabili senza la ragione sociale"
            )

        raw = CompanyRawData(
            ticker=ticker.upper(),
            company_name=company_name,
            retrieved_at=datetime.now(UTC),
            market_data=market_data,
            quarterly_financials=financials or [],
            filing_signals=filing_signals,
            clinical_trials=trials or [],
            fda_approvals=approvals or [],
            missing_data=list(missing),
        )

        logger.info(
            "dati_raccolti",
            ticker=raw.ticker,
            trimestri=len(raw.quarterly_financials),
            trial=len(raw.clinical_trials),
            approvazioni=len(raw.fda_approvals),
            dati_mancanti=len(raw.missing_data),
        )

        context[KEY_RAW_DATA] = raw
        append_missing(context, missing)
        return context


def _sponsor_query(company_name: str) -> str:
    """Riduce la ragione sociale al nucleo utile per la ricerca per sponsor.

    Gli enti registrano gli studi con nomi non allineati a quelli SEC
    ("Ensysce Biosciences" contro "Ensysce Biosciences, Inc."): togliere la
    forma societaria allarga la ricerca invece di non trovare nulla.
    """
    cleaned = company_name.split(",")[0].strip()
    for suffix in (" Inc.", " Inc", " Corp.", " Corp", " Ltd.", " Ltd", " LLC", " PLC", " plc"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)].strip()
    return cleaned or company_name
