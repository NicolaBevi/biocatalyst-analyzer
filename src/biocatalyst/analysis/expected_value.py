"""Expected value, ROI e variazioni percentuali dei target.

Realizza la regola esplicita del progetto: l'LLM fornisce soltanto le
probabilità degli scenari e i prezzi obiettivo; ogni operazione aritmetica
avviene qui, così i numeri del report sono sempre coerenti fra loro.

Nota metodologica sul cambio: entrata e uscita sono convertite allo stesso
tasso EUR/USD, quindi il cambio si semplifica e il valore atteso in euro
dipende solo dal rapporto fra prezzo atteso e prezzo corrente. Il tasso resta
necessario per calcolare quante azioni si comprano e va citato nel report,
ma **il rischio di cambio fra ingresso e uscita non è modellato**.
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

#: Importi richiesti dal formato di report.
DEFAULT_INVESTMENTS_EUR: tuple[float, ...] = (500.0, 1000.0)


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
    eur_usd_rate: float,
    rate_date: date,
    investments_eur: tuple[float, ...] = DEFAULT_INVESTMENTS_EUR,
) -> ExpectedValueAnalysis:
    """Tabella del valore atteso per ciascun importo di investimento.

    `eur_usd_rate` è quanti dollari vale un euro (es. 1.1662).
    """
    if current_price_usd <= 0:
        raise ValueError("il prezzo corrente deve essere positivo")
    if eur_usd_rate <= 0:
        raise ValueError("il tasso EUR/USD deve essere positivo")

    price_expected = expected_price(scenarios)
    roi_pct = expected_roi_pct(scenarios, current_price_usd)

    rows: list[ExpectedValueRow] = []
    for investment_eur in investments_eur:
        if investment_eur <= 0:
            raise ValueError("l'importo investito deve essere positivo")
        shares = investment_eur * eur_usd_rate / current_price_usd
        # Il cambio si semplifica fra ingresso e uscita: resta il rapporto
        # fra prezzo atteso e prezzo corrente.
        value_eur = shares * price_expected / eur_usd_rate
        rows.append(
            ExpectedValueRow(
                investment_eur=investment_eur,
                shares_purchasable=shares,
                expected_value_eur=value_eur,
                expected_roi_pct=roi_pct,
            )
        )

    return ExpectedValueAnalysis(
        eur_usd_rate=eur_usd_rate,
        rate_date=rate_date,
        rows=rows,
    )
