"""Composizione delle metriche finanziarie a partire dai dati grezzi.

Restituisce sempre una coppia (metriche, note): le note spiegano *perché* una
metrica è assente, così il report può dichiararlo invece di lasciare un vuoto
ambiguo.
"""

from __future__ import annotations

from datetime import date

from biocatalyst.analysis.financials import (
    DEFAULT_BURN_QUARTERS,
    cash_runway_months,
    latest_cash,
    quarterly_burn_rate,
)
from biocatalyst.analysis.risk import dilution_risk_score, short_squeeze_score
from biocatalyst.models.analysis import FinancialMetrics
from biocatalyst.models.raw_data import MarketData, QuarterlyFinancials, SECFilingSignals


def compute_financial_metrics(
    financials: list[QuarterlyFinancials],
    market_data: MarketData | None = None,
    filing_signals: SECFilingSignals | None = None,
    burn_quarters: int = DEFAULT_BURN_QUARTERS,
    as_of: date | None = None,
) -> tuple[FinancialMetrics, list[str]]:
    notes: list[str] = []

    cash_entry = latest_cash(financials)
    if cash_entry is None:
        notes.append("cassa non disponibile nei filing XBRL")
        cash_usd, cash_date = None, None
    else:
        cash_usd, cash_date = cash_entry

    burn = quarterly_burn_rate(financials, quarters=burn_quarters)
    if burn is None:
        notes.append(
            "burn rate non calcolabile: meno di due trimestri con risultato economico disponibile"
        )
    elif burn == 0:
        notes.append("burn rate nullo: l'azienda risulta mediamente in utile sui trimestri recenti")

    runway = cash_runway_months(cash_usd, burn)
    if runway is None and cash_usd is not None and burn is not None and burn == 0:
        notes.append("cash runway non definito perché il burn rate è nullo")
    elif runway is None and (cash_usd is None or burn is None):
        notes.append("cash runway non calcolabile: mancano cassa o burn rate")

    squeeze = short_squeeze_score(
        short_percent_of_float=market_data.short_percent_of_float if market_data else None,
        days_to_cover=market_data.short_ratio_days if market_data else None,
        float_shares=market_data.float_shares if market_data else None,
    )
    if squeeze is None:
        notes.append(
            "short squeeze score non calcolabile: nessun dato su short interest o flottante "
            "(frequente per i micro-cap)"
        )

    dilution = dilution_risk_score(
        cash_runway_months=runway,
        atm_offering_mentioned=filing_signals.atm_offering_mentioned if filing_signals else None,
        warrant_mentioned=filing_signals.warrant_mentioned if filing_signals else None,
    )
    if dilution is None:
        notes.append("dilution risk score non calcolabile: mancano runway e segnali dai filing")

    metrics = FinancialMetrics(
        cash_runway_months=runway,
        quarterly_burn_rate_usd=burn,
        short_squeeze_score=squeeze,
        dilution_risk_score=dilution,
        # La data di riferimento è quella del trimestre da cui viene la cassa:
        # ancorare le metriche a "oggi" le farebbe sembrare più fresche di quanto sono.
        as_of=as_of or cash_date or date.today(),
    )
    return metrics, notes
