"""Controlli di plausibilità sui dati in ingresso.

Diversi da `missing_data`: qui il numero c'è, ma è talmente fuori scala da
essere probabilmente stantio o errato. Segnalarlo è più utile che scartarlo,
perché il lettore possa verificarlo alla fonte.

Il caso che ha motivato questo modulo è reale: per Ensysce yfinance riporta un
target medio analisti di $8,25 contro un prezzo di $0,403 — oltre venti volte.
Un rapporto simile su un micro-cap indica quasi sempre una copertura non più
aggiornata dopo un raggruppamento di azioni o un crollo, non un'attesa di
rialzo del 1.900%.
"""

from __future__ import annotations

#: Oltre queste soglie il target è considerato non verosimile. Ampie di
#: proposito: su un titolo speculativo un target al doppio o alla metà del
#: prezzo è normale, uno a venti volte no.
TARGET_RATIO_MAX = 5.0
TARGET_RATIO_MIN = 0.2


def check_analyst_target(
    analyst_target: float | None,
    current_price: float | None,
) -> str | None:
    """Restituisce un avviso se il target analisti è incoerente col prezzo.

    None significa "nessuna anomalia rilevata" oppure "controllo non
    applicabile perché manca un valore".
    """
    if analyst_target is None or current_price is None or current_price <= 0:
        return None
    if analyst_target <= 0:
        return None

    ratio = analyst_target / current_price
    if ratio > TARGET_RATIO_MAX:
        return (
            f"Target medio analisti (${analyst_target:,.2f}) pari a {ratio:.1f} volte il prezzo "
            f"corrente (${current_price:,.2f}): valore probabilmente non aggiornato dopo un "
            f"raggruppamento di azioni o un forte ribasso. "
            f"Da verificare alla fonte prima di usarlo."
        )
    if ratio < TARGET_RATIO_MIN:
        return (
            f"Target medio analisti (${analyst_target:,.2f}) pari a {ratio:.2f} volte il prezzo "
            f"corrente (${current_price:,.2f}): valore anomalo, probabilmente non aggiornato. "
            f"Da verificare alla fonte prima di usarlo."
        )
    return None


def collect_data_warnings(
    analyst_target: float | None,
    current_price: float | None,
    short_interest_days_old: int | None = None,
) -> list[str]:
    """Raccoglie tutti gli avvisi di qualità del dato per il report."""
    warnings: list[str] = []

    target_warning = check_analyst_target(analyst_target, current_price)
    if target_warning is not None:
        warnings.append(target_warning)

    if short_interest_days_old is not None and short_interest_days_old > 0:
        warnings.append(
            f"Lo short interest è riferito a {short_interest_days_old} giorni fa: FINRA lo "
            f"rileva due volte al mese, quindi il dato è strutturalmente arretrato per "
            f"qualunque fonte, non solo per questa."
        )

    return warnings
