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
from biocatalyst.i18n import t
from biocatalyst.log import get_logger
from biocatalyst.models.raw_data import CompanyRawData
from biocatalyst.models.report import ReportLanguage

logger = get_logger(__name__)


class DataCollectorAgent(BaseAgent):
    name: ClassVar[str] = "DataCollector"
    requires: ClassVar[tuple[str, ...]] = (KEY_TICKER,)

    def __init__(self, providers: DataProviders, language: ReportLanguage = "en") -> None:
        self.providers = providers
        self.language = language

    def _retrieved_at(self) -> datetime:
        """Momento a cui i dati si riferiscono davvero.

        Se qualcosa è arrivato dalla cache, il report non deve dichiararsi
        fresco: si prende il più vecchio fra i dati serviti. È la data che il
        lettore vede accanto al report, e deve poterci contare.
        """
        adesso = datetime.now(UTC)
        piu_vecchio = getattr(self.providers.cache, "oldest_hit_at", None)
        if not isinstance(piu_vecchio, datetime):
            return adesso
        return min(adesso, piu_vecchio)

    def _run(self, context: dict[str, Any]) -> dict[str, Any]:
        ticker: str = context[KEY_TICKER]
        missing: list[str] = []
        p = self.providers

        # Il nome ufficiale SEC serve a interrogare ClinicalTrials.gov e openFDA,
        # che indicizzano per ragione sociale e non per ticker.
        company_name = collect_safely(
            t(self.language, "src.company_name_sec"),
            lambda: p.sec.get_company_name(ticker),
            missing,
        )
        if company_name is None:
            company_name = collect_safely(
                t(self.language, "src.company_name_yf"),
                lambda: p.market.get_company_name(ticker),
                missing,
            )

        market_data = collect_safely(
            t(self.language, "src.market_data"), lambda: p.market.get_market_data(ticker), missing
        )
        financials = collect_safely(
            t(self.language, "src.financials"),
            lambda: p.sec.get_quarterly_financials(ticker),
            missing,
        )
        filing_signals = collect_safely(
            t(self.language, "src.filing_signals"),
            lambda: p.sec.get_filing_signals(ticker),
            missing,
        )

        trials = None
        approvals = None
        if company_name:
            sponsor = _sponsor_query(company_name)
            trials = collect_safely(
                t(self.language, "src.trials"),
                lambda: p.clinical_trials.get_trials_by_sponsor(sponsor),
                missing,
            )
            approvals = collect_safely(
                t(self.language, "src.approvals"),
                lambda: p.fda.get_approvals_by_sponsor(company_name),
                missing,
            )
        else:
            missing.append(t(self.language, "collect.no_company_name"))

        raw = CompanyRawData(
            ticker=ticker.upper(),
            company_name=company_name,
            retrieved_at=self._retrieved_at(),
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
