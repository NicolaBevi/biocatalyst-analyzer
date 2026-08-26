"""Expected value, ROI e variazioni percentuali dei target.

Realizza la regola esplicita del progetto: l'LLM fornisce soltanto le
probabilità degli scenari e i prezzi obiettivo; ogni operazione aritmetica
avviene qui, così i numeri del report sono sempre coerenti fra loro.

Il calcolo è in dollari, la valuta in cui il titolo quota: così nessuna
assunzione sul cambio entra nel risultato dell'investimento. Il tasso EUR/USD
resta allegato al report come riferimento informativo per un lettore in area
euro, ma **il rischio di cambio non è modellato**.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from biocatalyst.models.report import (
    ExpectedValueAnalysis,
    ExpectedValueRow,
    Scenario,
    ScenarioAnalysis,
)

#: Importo di riferimento della tabella del valore atteso, in dollari.
DEFAULT_INVESTMENTS_USD: tuple[float, ...] = (1000.0,)


@dataclass(frozen=True)
class ScenarioInput:
    """Ciò che l'LLM può fornire: una probabilità, un target e le condizioni.

    Volutamente privo della variazione percentuale: quella è aritmetica e
    viene calcolata da `build_scenario_analysis`.
    """

    probability: float
    target_price: float
    conditions: str


def target_change_pct(target_price: float, current_price: float) -> float:
    """Variazione percentuale fra prezzo corrente e obiettivo."""
    if current_price <= 0:
        raise ValueError("il prezzo corrente deve essere positivo")
    return (target_price - current_price) / current_price * 100.0


def build_scenario_analysis(
    current_price: float,
    bull: ScenarioInput,
    base: ScenarioInput,
    bear: ScenarioInput,
) -> ScenarioAnalysis:
    """Compone i tre scenari calcolando in Python le variazioni percentuali.

    La validazione che le probabilità sommino a 1 avviene nel modello
    `ScenarioAnalysis`.
    """

    def to_scenario(item: ScenarioInput) -> Scenario:
        return Scenario(
            probability=item.probability,
            target_price=item.target_price,
            target_price_change_pct=target_change_pct(item.target_price, current_price),
            conditions=item.conditions,
        )

    return ScenarioAnalysis(
        bull=to_scenario(bull),
        base=to_scenario(base),
        bear=to_scenario(bear),
    )


def expected_price(scenarios: ScenarioAnalysis) -> float:
    """Prezzo atteso: media dei target pesata per le rispettive probabilità."""
    return (
        scenarios.bull.probability * scenarios.bull.target_price
        + scenarios.base.probability * scenarios.base.target_price
        + scenarios.bear.probability * scenarios.bear.target_price
    )


def expected_roi_pct(scenarios: ScenarioAnalysis, current_price: float) -> float:
    """ROI atteso in percentuale, indipendente dall'importo investito."""
    if current_price <= 0:
        raise ValueError("il prezzo corrente deve essere positivo")
    return (expected_price(scenarios) / current_price - 1.0) * 100.0


def build_expected_value_analysis(
    current_price_usd: float,
    scenarios: ScenarioAnalysis,
    investments_usd: tuple[float, ...] = DEFAULT_INVESTMENTS_USD,
    eur_usd_rate: float | None = None,
    rate_date: date | None = None,
) -> ExpectedValueAnalysis:
    """Tabella del valore atteso per ciascun importo investito, in dollari.

    `eur_usd_rate` è solo un riferimento allegato al report (quanti dollari
    vale un euro): non entra in alcun calcolo.
    """
    if current_price_usd <= 0:
        raise ValueError("il prezzo corrente deve essere positivo")
    if eur_usd_rate is not None and eur_usd_rate <= 0:
        raise ValueError("il tasso EUR/USD deve essere positivo")

    price_expected = expected_price(scenarios)
    roi_pct = expected_roi_pct(scenarios, current_price_usd)

    rows: list[ExpectedValueRow] = []
    for investment_usd in investments_usd:
        if investment_usd <= 0:
            raise ValueError("l'importo investito deve essere positivo")
        shares = investment_usd / current_price_usd
        rows.append(
            ExpectedValueRow(
                investment_usd=investment_usd,
                shares_purchasable=shares,
                expected_value_usd=shares * price_expected,
                expected_roi_pct=roi_pct,
            )
        )

    return ExpectedValueAnalysis(rows=rows, eur_usd_rate=eur_usd_rate, rate_date=rate_date)
