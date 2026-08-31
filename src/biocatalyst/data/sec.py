"""SEC EDGAR: mappatura ticker->CIK, dati XBRL strutturati, ricerca full-text.

Usa le API XBRL (`data.sec.gov/api/xbrl/companyfacts`) invece di parsare l'HTML
dei 10-Q/10-K: i valori arrivano già numerici e datati.

Tre insidie di questa fonte, verificate sui dati reali e gestite qui:
1. Per uno stesso `fp` (es. "Q2") coesistono il fatto trimestrale (3 mesi) e
   quello cumulato year-to-date (6 mesi). Vanno distinti dalla durata
   `end - start`, non dal campo `fp`, altrimenti i valori raddoppiano.
2. Il Q4 non è mai marcato come tale: va derivato sottraendo i primi tre
   trimestri dal totale dell'esercizio.
3. Un filing rettificato (10-K/A) riemette lo stesso periodo con valori
   diversi: si tiene la versione depositata più di recente.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any, ClassVar, Literal, cast

from biocatalyst.data.base import (
    DataNotFoundError,
    DataParseError,
    HTTPDataProvider,
    RateLimiter,
    parse_flexible_date,
    translates_validation_errors,
)
from biocatalyst.data.cache import DataCache
from biocatalyst.log import get_logger
from biocatalyst.models.raw_data import QuarterlyFinancials, SECFilingSignals

logger = get_logger(__name__)

TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
FULL_TEXT_SEARCH_URL = "https://efts.sec.gov/LATEST/search-index"

# Uno stesso dato economico è taggato con concetti diversi a seconda del filer e
# dell'esercizio: Ensysce, per esempio, usa NetIncomeLoss fino al 2021 e
# ProfitLoss dal 2022. Si prova quindi una catena di concetti equivalenti in
# ordine di preferenza e, per ogni periodo, vince il primo che ha il dato.
CASH_CONCEPTS = (
    "CashAndCashEquivalentsAtCarryingValue",
    "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
)
RD_CONCEPTS = ("ResearchAndDevelopmentExpense",)
NET_INCOME_CONCEPTS = (
    "NetIncomeLoss",
    "ProfitLoss",
    "NetIncomeLossAvailableToCommonStockholdersBasic",
)

# Un trimestre reale dura 89-92 giorni: la finestra 80-100 assorbe i calendari
# fiscali irregolari senza mai catturare un semestre (180gg) o un anno (365gg).
QUARTER_DAYS = (80, 100)
FISCAL_YEAR_DAYS = (350, 380)

ATM_QUERY = '"at-the-market offering"'
WARRANT_QUERY = '"warrant"'

FiscalPeriod = Literal["Q1", "Q2", "Q3", "Q4", "FY"]
FormType = Literal["10-Q", "10-K"]
QUARTER_PERIODS: tuple[FiscalPeriod, ...] = ("Q1", "Q2", "Q3", "Q4")
INSTANT_PERIODS: tuple[FiscalPeriod, ...] = ("Q1", "Q2", "Q3", "Q4", "FY")


class SECProvider(HTTPDataProvider):
    # La SEC conta 10 richieste/secondo per IP sommando www, data ed efts:
    # il limitatore è quindi uno solo, condiviso a livello di classe. 0.12s
    # (~8 req/s) lascia margine sotto la soglia.
    rate_limiter: ClassVar[RateLimiter] = RateLimiter(0.12)

    def __init__(
        self,
        user_agent: str,
        cache: DataCache | None = None,
        timeout: int = 30,
        max_retries: int = 3,
        filing_ttl_seconds: int = 86_400,
    ) -> None:
        # Senza uno User-Agent identificativo la SEC risponde 403 a ogni chiamata.
        super().__init__(
            cache=cache,
            timeout=timeout,
            max_retries=max_retries,
            headers={"User-Agent": user_agent},
        )
        self.filing_ttl_seconds = filing_ttl_seconds

    # --- Mappatura ticker -> CIK ---------------------------------------------

    def get_cik(self, ticker: str) -> str:
        """CIK a 10 cifre con zeri iniziali, come richiesto dagli URL di data.sec.gov."""
        mapping = self._get_json(
            TICKER_MAP_URL,
            ttl_seconds=self.filing_ttl_seconds,
            cache_key="sec:ticker_map",
        )
        wanted = ticker.upper()
        for entry in mapping.values():
            if entry.get("ticker", "").upper() == wanted:
                # Il file espone il CIK come intero senza padding: gli URL
                # con CIK non zero-paddato rispondono 404.
                return f"{int(entry['cik_str']):010d}"
        raise DataNotFoundError(f"ticker '{ticker}' non presente nell'elenco SEC")

    def get_company_name(self, ticker: str) -> str | None:
        mapping = self._get_json(
            TICKER_MAP_URL,
            ttl_seconds=self.filing_ttl_seconds,
            cache_key="sec:ticker_map",
        )
        wanted = ticker.upper()
        for entry in mapping.values():
            if entry.get("ticker", "").upper() == wanted:
                name: str | None = entry.get("title")
                return name
        return None

    # --- Dati finanziari trimestrali -----------------------------------------

    @translates_validation_errors
    def get_quarterly_financials(self, ticker: str) -> list[QuarterlyFinancials]:
        cik = self.get_cik(ticker)
        facts = self._get_json(
            COMPANY_FACTS_URL.format(cik=cik),
            ttl_seconds=self.filing_ttl_seconds,
            cache_key=f"sec:facts:{cik}",
        )
        us_gaap = facts.get("facts", {}).get("us-gaap")
        if not us_gaap:
            raise DataParseError(f"nessun dato us-gaap nei filing XBRL di {ticker}")

        cash = _merge_periods(us_gaap, CASH_CONCEPTS, _instant_values)
        rd = _merge_periods(us_gaap, RD_CONCEPTS, _quarterly_values)
        net = _merge_periods(us_gaap, NET_INCOME_CONCEPTS, _quarterly_values)

        rd = _add_derived_q4(rd, _merge_annual(us_gaap, RD_CONCEPTS))
        net = _add_derived_q4(net, _merge_annual(us_gaap, NET_INCOME_CONCEPTS))

        periods = sorted(set(cash) | set(rd) | set(net))
        results: list[QuarterlyFinancials] = []
        for key in periods:
            fiscal_year, fiscal_period = key
            reference = cash.get(key) or rd.get(key) or net.get(key)
            if reference is None:
                continue
            results.append(
                QuarterlyFinancials(
                    fiscal_year=fiscal_year,
                    fiscal_period=fiscal_period,
                    period_end=reference.period_end,
                    cash_and_equivalents_usd=_value_of(cash.get(key)),
                    rd_expense_usd=_value_of(rd.get(key)),
                    net_income_loss_usd=_value_of(net.get(key)),
                    form_type=reference.form_type,
                    filed_date=reference.filed_date,
                )
            )
        return results

    # --- Ricerca full-text nei filing ----------------------------------------

    @translates_validation_errors
    def get_filing_signals(self, ticker: str) -> SECFilingSignals:
        """Cerca menzioni di ATM offering e warrant nei filing della società.

        La ricerca full-text EDGAR richiede `ciks` oppure un intervallo di date:
        con il solo parametro `q` risponde 500.
        """
        cik = self.get_cik(ticker)
        atm_hits = self._search_filings(cik, ATM_QUERY)
        warrant_hits = self._search_filings(cik, WARRANT_QUERY)
        return SECFilingSignals(
            atm_offering_mentioned=bool(atm_hits),
            warrant_mentioned=bool(warrant_hits),
            matching_accession_numbers=sorted({*atm_hits, *warrant_hits}),
            as_of=date.today(),
        )

    def _search_filings(self, cik: str, query: str) -> list[str]:
        payload = self._get_json(
            FULL_TEXT_SEARCH_URL,
            params={"q": query, "ciks": cik},
            ttl_seconds=self.filing_ttl_seconds,
            cache_key=f"sec:fts:{cik}:{query}",
        )
        hits = payload.get("hits", {}).get("hits", [])
        accessions: list[str] = []
        for hit in hits:
            adsh = hit.get("_source", {}).get("adsh")
            if adsh:
                accessions.append(adsh)
        return accessions


class _Fact:
    __slots__ = ("filed_date", "form_type", "period_end", "value")

    def __init__(
        self, value: float | None, period_end: date, form_type: str, filed_date: date
    ) -> None:
        self.value = value
        self.period_end = period_end
        # Le rettifiche mantengono il tipo di origine: "10-Q/A" resta un 10-Q.
        self.form_type: FormType = "10-Q" if form_type.startswith("10-Q") else "10-K"
        self.filed_date = filed_date


PeriodKey = tuple[int, FiscalPeriod]


def _value_of(fact: _Fact | None) -> float | None:
    return fact.value if fact is not None else None


def _merge_periods(
    us_gaap: dict[str, Any],
    concepts: tuple[str, ...],
    extractor: Callable[[dict[str, Any] | None], dict[PeriodKey, _Fact]],
) -> dict[PeriodKey, _Fact]:
    """Fonde più concetti equivalenti: per ogni periodo vince il primo della catena.

    Serve perché un filer può cambiare tag da un esercizio all'altro: la fusione
    per periodo copre l'intera serie storica invece di fermarsi al primo
    concetto che contiene qualcosa.
    """
    merged: dict[PeriodKey, _Fact] = {}
    for concept in concepts:
        for key, fact in extractor(us_gaap.get(concept)).items():
            merged.setdefault(key, fact)
    return merged


def _merge_annual(us_gaap: dict[str, Any], concepts: tuple[str, ...]) -> dict[int, _Fact]:
    merged: dict[int, _Fact] = {}
    for concept in concepts:
        for fiscal_year, fact in _annual_values(us_gaap.get(concept)).items():
            merged.setdefault(fiscal_year, fact)
    return merged


def _usd_entries(concept: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not concept:
        return []
    entries = concept.get("units", {}).get("USD", [])
    return [e for e in entries if isinstance(e, dict)]


def _duration_days(entry: dict[str, Any]) -> int | None:
    start = parse_flexible_date(entry.get("start"))
    end = parse_flexible_date(entry.get("end"))
    if start is None or end is None:
        return None
    return (end - start).days


def _to_fact(entry: dict[str, Any]) -> _Fact | None:
    end = parse_flexible_date(entry.get("end"))
    filed = parse_flexible_date(entry.get("filed"))
    if end is None or filed is None:
        return None
    return _Fact(
        value=entry.get("val"),
        period_end=end,
        form_type=str(entry.get("form", "")),
        filed_date=filed,
    )


def _keep_latest_filed(collected: dict[PeriodKey, _Fact], key: PeriodKey, candidate: _Fact) -> None:
    """Una rettifica (10-K/A) riemette lo stesso periodo: vince il deposito più recente."""
    existing = collected.get(key)
    if existing is None or candidate.filed_date >= existing.filed_date:
        collected[key] = candidate


def _instant_values(concept: dict[str, Any] | None) -> dict[PeriodKey, _Fact]:
    """Fatti puntuali (es. cassa a fine periodo): hanno solo `end`, mai `start`."""
    collected: dict[PeriodKey, _Fact] = {}
    for entry in _usd_entries(concept):
        if entry.get("start") is not None:
            continue
        fp_raw = entry.get("fp")
        fy = entry.get("fy")
        if fp_raw not in INSTANT_PERIODS or not isinstance(fy, int):
            continue
        fact = _to_fact(entry)
        if fact is None:
            continue
        # Il controllo di appartenenza qui sopra garantisce il valore letterale.
        fp = cast(FiscalPeriod, fp_raw)
        # Il bilancio di fine esercizio è la fotografia al termine del Q4.
        period: FiscalPeriod = "Q4" if fp == "FY" else fp
        _keep_latest_filed(collected, (fy, period), fact)
    return collected


def _quarterly_values(concept: dict[str, Any] | None) -> dict[PeriodKey, _Fact]:
    """Solo i fatti di durata trimestrale, scartando i cumulati year-to-date."""
    collected: dict[PeriodKey, _Fact] = {}
    for entry in _usd_entries(concept):
        days = _duration_days(entry)
        if days is None or not (QUARTER_DAYS[0] <= days <= QUARTER_DAYS[1]):
            continue
        fp_raw = entry.get("fp")
        fy = entry.get("fy")
        if fp_raw not in QUARTER_PERIODS or not isinstance(fy, int):
            continue
        fact = _to_fact(entry)
        if fact is None:
            continue
        _keep_latest_filed(collected, (fy, cast(FiscalPeriod, fp_raw)), fact)
    return collected


def _annual_values(concept: dict[str, Any] | None) -> dict[int, _Fact]:
    collected: dict[int, _Fact] = {}
    for entry in _usd_entries(concept):
        days = _duration_days(entry)
        if days is None or not (FISCAL_YEAR_DAYS[0] <= days <= FISCAL_YEAR_DAYS[1]):
            continue
        fy = entry.get("fy")
        if not isinstance(fy, int):
            continue
        fact = _to_fact(entry)
        if fact is None:
            continue
        existing = collected.get(fy)
        if existing is None or fact.filed_date >= existing.filed_date:
            collected[fy] = fact
    return collected


def _add_derived_q4(
    quarterly: dict[PeriodKey, _Fact], annual: dict[int, _Fact]
) -> dict[PeriodKey, _Fact]:
    """Ricostruisce il Q4, che XBRL non marca mai: totale annuo meno i primi tre trimestri.

    Si calcola solo se l'esercizio è completo (Q1, Q2, Q3 e FY tutti presenti
    con un valore): con un trimestre mancante il risultato sarebbe silenziosamente
    sbagliato, quindi in quel caso il Q4 resta assente.
    """
    enriched = dict(quarterly)
    for fiscal_year, annual_fact in annual.items():
        if (fiscal_year, "Q4") in enriched or annual_fact.value is None:
            continue
        first_three = [enriched.get((fiscal_year, q)) for q in ("Q1", "Q2", "Q3")]
        if any(f is None or f.value is None for f in first_three):
            continue
        total_first_three = sum(f.value for f in first_three if f and f.value is not None)
        enriched[(fiscal_year, "Q4")] = _Fact(
            value=annual_fact.value - total_first_three,
            period_end=annual_fact.period_end,
            form_type=annual_fact.form_type,
            filed_date=annual_fact.filed_date,
        )
    return enriched
