"""Filtri e punteggio di attrattività per la modalità screen.

Tutto deterministico: quali titoli superino i criteri e in che ordine è una
questione di soglie e date, non di giudizio. All'LLM resta solo la motivazione
testuale sui pochi finalisti.

L'intuizione che guida il punteggio: **la cassa deve bastare fino al
catalizzatore**. Una società che esaurisce la liquidità prima della lettura
dei dati diluisce gli azionisti proprio mentre il titolo attende l'evento, e
il rialzo atteso viene mangiato dall'aumento di capitale.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from biocatalyst.models.analysis import Catalyst
from biocatalyst.models.screening import ScreenCriteria

#: Fasi ordinate: serve a confrontare "almeno PHASE2" con quanto dichiarato.
PHASE_ORDER: dict[str, int] = {
    "EARLY_PHASE1": 0,
    "PHASE1": 1,
    "PHASE2": 2,
    "PHASE3": 3,
    "PHASE4": 4,
}

WEIGHT_IMMINENCE = 0.35
WEIGHT_RUNWAY_COVERAGE = 0.35
WEIGHT_SIZE = 0.20
WEIGHT_PHASE = 0.10

#: Un margine di cassa pari o superiore al doppio del tempo che manca al
#: catalizzatore è considerato pieno: oltre non aggiunge sicurezza utile.
RUNWAY_COVERAGE_FULL = 2.0


@dataclass(frozen=True)
class ScreenFilterResult:
    """Esito del filtro su un singolo titolo, con la ragione dell'eventuale scarto."""

    passed: bool
    reason: str | None = None
    exceptional: bool = False


def passes_price_and_size(
    price: float | None,
    market_cap: float | None,
    criteria: ScreenCriteria,
) -> ScreenFilterResult:
    """Filtro su prezzo e capitalizzazione, con la banda "eccezionale".

    I requisiti prevedono di non scartare automaticamente un titolo appena
    sopra soglia ma di segnalarlo motivandolo: `exceptional` marca proprio
    questi casi, che vengono inclusi e dichiarati.
    """
    if price is None:
        return ScreenFilterResult(False, "prezzo non disponibile")
    if market_cap is None:
        return ScreenFilterResult(False, "capitalizzazione non disponibile")

    if price > criteria.max_price_usd_exceptional:
        return ScreenFilterResult(False, f"prezzo ${price:,.2f} oltre il limite massimo assoluto")
    if market_cap > criteria.market_cap_max_usd_exceptional:
        return ScreenFilterResult(
            False, f"capitalizzazione ${market_cap:,.0f} oltre il limite massimo assoluto"
        )

    oltre_soglia = price > criteria.max_price_usd or market_cap > criteria.market_cap_max_usd
    return ScreenFilterResult(True, exceptional=oltre_soglia)


def months_to_catalyst(catalyst: Catalyst, today: date | None = None) -> float | None:
    """Mesi che mancano al catalizzatore. None se privo di data puntuale."""
    if catalyst.expected_date is None:
        return None
    reference = today or date.today()
    return (catalyst.expected_date - reference).days / 30.44


def meets_phase_requirement(phases: list[str], minimum: str) -> bool:
    """Verifica che almeno una fase dichiarata raggiunga il minimo richiesto.

    Nota: ClinicalTrials.gov non distingue "Phase 2b" da "Phase 2", quindi il
    confronto è per forza grossolano; l'affinamento avviene guardando
    numerosità e disegno dello studio, non questo campo.
    """
    soglia = PHASE_ORDER.get(minimum.upper(), 2)
    return any(PHASE_ORDER.get(p.upper(), -1) >= soglia for p in phases)


def imminence_score(months_away: float | None, window_months: int) -> float:
    """Più il catalizzatore è vicino (entro la finestra), più il punteggio sale."""
    if months_away is None or months_away < 0:
        return 0.0
    if months_away > window_months:
        return 0.0
    return 100.0 * (1.0 - months_away / window_months)


def runway_coverage_score(
    cash_runway_months: float | None, months_away: float | None
) -> float | None:
    """Quanto la cassa copre l'attesa fino al catalizzatore.

    100 significa liquidità pari almeno al doppio del tempo mancante; 0
    significa che i soldi finiscono prima dell'evento, con diluizione quasi
    certa nel frattempo.
    """
    if cash_runway_months is None or months_away is None:
        return None
    if months_away <= 0:
        return 100.0
    rapporto = cash_runway_months / months_away
    if rapporto >= RUNWAY_COVERAGE_FULL:
        return 100.0
    return max(0.0, 100.0 * rapporto / RUNWAY_COVERAGE_FULL)


def size_score(market_cap: float | None, criteria: ScreenCriteria) -> float | None:
    """Premia le capitalizzazioni più piccole entro la banda ammessa.

    A parità di catalizzatore una società più piccola ha più spazio di
    rivalutazione: è la ragione per cui il profilo cercato è il micro-cap.
    """
    if market_cap is None or market_cap <= 0:
        return None
    tetto = criteria.market_cap_max_usd_exceptional
    return max(0.0, min(100.0, 100.0 * (1.0 - market_cap / tetto)))


def phase_score(phases: list[str]) -> float | None:
    """Le fasi avanzate valgono di più: il catalizzatore è più vicino al mercato."""
    if not phases:
        return None
    massimo = max((PHASE_ORDER.get(p.upper(), -1) for p in phases), default=-1)
    if massimo < 0:
        return None
    return 100.0 * massimo / 4.0


def attractiveness_score(
    catalyst: Catalyst,
    criteria: ScreenCriteria,
    market_cap: float | None,
    cash_runway_months: float | None,
    phases: list[str],
    today: date | None = None,
) -> float:
    """Punteggio composito 0-100 usato per ordinare le candidate.

    I pesi dei componenti mancanti si ridistribuiscono sugli altri, come negli
    score di rischio: un dato assente non deve penalizzare implicitamente.
    """
    months_away = months_to_catalyst(catalyst, today)

    componenti: list[tuple[float, float]] = [
        (imminence_score(months_away, criteria.catalyst_window_months), WEIGHT_IMMINENCE)
    ]
    copertura = runway_coverage_score(cash_runway_months, months_away)
    if copertura is not None:
        componenti.append((copertura, WEIGHT_RUNWAY_COVERAGE))
    dimensione = size_score(market_cap, criteria)
    if dimensione is not None:
        componenti.append((dimensione, WEIGHT_SIZE))
    fase = phase_score(phases)
    if fase is not None:
        componenti.append((fase, WEIGHT_PHASE))

    peso_totale = sum(w for _, w in componenti)
    if peso_totale <= 0:
        return 0.0
    return sum(s * w for s, w in componenti) / peso_totale
