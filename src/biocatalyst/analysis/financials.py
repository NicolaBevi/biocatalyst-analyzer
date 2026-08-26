"""Burn rate e cash runway.

Scelta della metrica di burn, motivata sui dati reali:

- Il **calo di cassa** fra due trimestri è distorto dai finanziamenti. Su
  Ensysce la cassa passa da 1,67M a 4,31M fra Q3 e Q4 2025 per un aumento di
  capitale: misurata così, l'azienda avrebbe "burn negativo" pur bruciando
  liquidità.
- Il **risultato netto** è distorto dalle poste non monetarie (rivalutazione
  di warrant, stock compensation), che nel biotech micro-cap sono grandi: lo
  stesso Ensysce ha un Q3 2024 in utile mentre la cassa scendeva.

Si usa la media del risultato netto sugli ultimi trimestri: la media assorbe
i singoli trimestri anomali e non viene falsata dagli aumenti di capitale.
Resta un'approssimazione, perché il rendiconto finanziario (l'unica fonte
esatta del burn operativo) non è esposto dalle API XBRL usate qui.
"""

from __future__ import annotations

from datetime import date

from biocatalyst.models.raw_data import QuarterlyFinancials

#: Trimestri usati per la media. Quattro coprono un esercizio intero e
#: attenuano la stagionalità dei costi di trial.
DEFAULT_BURN_QUARTERS = 4

#: Sotto due trimestri la media non ha significato statistico.
MIN_BURN_QUARTERS = 2

MONTHS_PER_QUARTER = 3


def sorted_by_period(financials: list[QuarterlyFinancials]) -> list[QuarterlyFinancials]:
    """Ordina per data di fine periodo, dal più vecchio al più recente."""
    return sorted(financials, key=lambda f: f.period_end)


def latest_cash(financials: list[QuarterlyFinancials]) -> tuple[float, date] | None:
    """Cassa più recente disponibile, con il trimestre di riferimento.

    Il requisito chiede di esporre sempre il trimestre a cui il dato si
    riferisce: una cassa senza data non è verificabile.
    """
    for entry in reversed(sorted_by_period(financials)):
        if entry.cash_and_equivalents_usd is not None:
            return entry.cash_and_equivalents_usd, entry.period_end
    return None


def quarterly_burn_rate(
    financials: list[QuarterlyFinancials],
    quarters: int = DEFAULT_BURN_QUARTERS,
) -> float | None:
    """Liquidità bruciata in media per trimestre, in USD positivi.

    Restituisce None se i trimestri con risultato disponibile sono meno di
    `MIN_BURN_QUARTERS`. Restituisce 0.0 se l'azienda è mediamente in utile:
    in quel caso non sta bruciando cassa e il runway non è un vincolo.
    """
    if quarters < 1:
        raise ValueError("quarters deve essere almeno 1")

    recent = sorted_by_period(financials)[-quarters:]
    results = [f.net_income_loss_usd for f in recent if f.net_income_loss_usd is not None]
    if len(results) < MIN_BURN_QUARTERS:
        return None

    average_result = sum(results) / len(results)
    # Una perdita è negativa: il burn è il suo opposto. Un utile medio
    # produrrebbe un burn negativo, che non ha senso: si azzera.
    return max(0.0, -average_result)


def cash_runway_months(cash_usd: float | None, quarterly_burn_usd: float | None) -> float | None:
    """Mesi di autonomia al ritmo di consumo corrente.

    None quando manca un ingrediente o quando il burn è nullo (azienda in
    utile): in quel caso il runway non è definito, e restituire un numero
    enorme sarebbe fuorviante quanto restituire zero.
    """
    if cash_usd is None or quarterly_burn_usd is None:
        return None
    if quarterly_burn_usd <= 0:
        return None
    if cash_usd < 0:
        return None
    return cash_usd / quarterly_burn_usd * MONTHS_PER_QUARTER
