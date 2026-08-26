"""Punteggi di rischio: short squeeze e diluizione.

Sono indicatori euristici su scala 0-100, non probabilità: servono a
ordinare i titoli fra loro, non a prevedere un esito. Le soglie sono
esplicite e commentate proprio perché sono convenzioni, non leggi di mercato.

Regola comune: quando manca un ingrediente, il peso viene ridistribuito sui
componenti disponibili; se non ne resta nessuno il punteggio è None. Restituire
0 per "dato assente" si leggerebbe come "rischio nullo".
"""

from __future__ import annotations

from math import log10

# --- Soglie dello short squeeze score ----------------------------------------
#: Oltre il 30% del flottante short il punteggio è già al massimo: sopra questa
#: soglia il mercato è comunque in territorio estremo.
SHORT_PERCENT_SATURATION = 30.0
#: Dieci giorni di copertura sono un blocco severo: chi è short non può uscire
#: rapidamente senza muovere il prezzo.
DAYS_TO_COVER_SATURATION = 10.0
#: Sotto i 5 milioni di azioni il flottante è talmente sottile da rendere il
#: titolo massimamente vulnerabile; sopra i 100 milioni l'effetto svanisce.
FLOAT_SCARCE = 5_000_000.0
FLOAT_ABUNDANT = 100_000_000.0

WEIGHT_SHORT_PERCENT = 0.45
WEIGHT_DAYS_TO_COVER = 0.35
WEIGHT_FLOAT_SCARCITY = 0.20

# --- Soglie del dilution risk score ------------------------------------------
#: Con meno di 6 mesi di autonomia un aumento di capitale è pressoché certo.
RUNWAY_CRITICAL_MONTHS = 6.0
#: Oltre i 24 mesi la pressione a diluire nel breve è trascurabile.
RUNWAY_COMFORTABLE_MONTHS = 24.0

WEIGHT_RUNWAY = 0.60
WEIGHT_ATM = 0.25
WEIGHT_WARRANT = 0.15


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _weighted(components: list[tuple[float, float]]) -> float | None:
    """Media pesata che ridistribuisce il peso dei componenti assenti."""
    if not components:
        return None
    total_weight = sum(weight for _, weight in components)
    if total_weight <= 0:
        return None
    return sum(score * weight for score, weight in components) / total_weight


def float_scarcity_score(float_shares: float | None) -> float | None:
    """Quanto è sottile il flottante, su scala 0-100.

    L'interpolazione è logaritmica perché i flottanti spaziano su ordini di
    grandezza: fra 5 e 10 milioni di azioni la differenza pesa molto più che
    fra 90 e 95 milioni.
    """
    if float_shares is None or float_shares <= 0:
        return None
    if float_shares <= FLOAT_SCARCE:
        return 100.0
    if float_shares >= FLOAT_ABUNDANT:
        return 0.0
    span = log10(FLOAT_ABUNDANT) - log10(FLOAT_SCARCE)
    position = (log10(float_shares) - log10(FLOAT_SCARCE)) / span
    return _clamp(100.0 * (1.0 - position))


def short_squeeze_score(
    short_percent_of_float: float | None,
    days_to_cover: float | None,
    float_shares: float | None,
) -> float | None:
    """Potenziale di short squeeze, 0-100.

    `short_percent_of_float` è atteso in percentuale (12.5 = 12,5%), come
    normalizzato dal provider di mercato: yfinance lo espone invece come
    frazione.
    """
    components: list[tuple[float, float]] = []

    if short_percent_of_float is not None and short_percent_of_float >= 0:
        score = _clamp(short_percent_of_float / SHORT_PERCENT_SATURATION * 100.0)
        components.append((score, WEIGHT_SHORT_PERCENT))

    if days_to_cover is not None and days_to_cover >= 0:
        score = _clamp(days_to_cover / DAYS_TO_COVER_SATURATION * 100.0)
        components.append((score, WEIGHT_DAYS_TO_COVER))

    scarcity = float_scarcity_score(float_shares)
    if scarcity is not None:
        components.append((scarcity, WEIGHT_FLOAT_SCARCITY))

    return _weighted(components)


def runway_pressure_score(cash_runway_months: float | None) -> float | None:
    """Pressione a raccogliere capitale derivante dalla scarsità di cassa."""
    if cash_runway_months is None or cash_runway_months < 0:
        return None
    if cash_runway_months <= RUNWAY_CRITICAL_MONTHS:
        return 100.0
    if cash_runway_months >= RUNWAY_COMFORTABLE_MONTHS:
        return 0.0
    span = RUNWAY_COMFORTABLE_MONTHS - RUNWAY_CRITICAL_MONTHS
    position = (cash_runway_months - RUNWAY_CRITICAL_MONTHS) / span
    return _clamp(100.0 * (1.0 - position))


def dilution_risk_score(
    cash_runway_months: float | None,
    atm_offering_mentioned: bool | None,
    warrant_mentioned: bool | None,
) -> float | None:
    """Rischio di diluizione degli azionisti, 0-100.

    I due flag arrivano dalla ricerca full-text nei filing SEC. `None`
    significa "ricerca non eseguita o fallita" e fa ridistribuire il peso;
    `False` significa "cercato e non trovato" e contribuisce con zero.
    """
    components: list[tuple[float, float]] = []

    pressure = runway_pressure_score(cash_runway_months)
    if pressure is not None:
        components.append((pressure, WEIGHT_RUNWAY))

    if atm_offering_mentioned is not None:
        components.append((100.0 if atm_offering_mentioned else 0.0, WEIGHT_ATM))

    if warrant_mentioned is not None:
        components.append((100.0 if warrant_mentioned else 0.0, WEIGHT_WARRANT))

    return _weighted(components)
