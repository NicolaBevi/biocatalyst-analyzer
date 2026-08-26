"""Test della UI Streamlit, con il framework di test ufficiale (AppTest).

La pipeline è sempre sostituita da un doppio: nessuna chiamata reale.
"""

from __future__ import annotations

import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from biocatalyst.app import StatoAnalisi, _avvia_analisi
from biocatalyst.models.analysis import FinancialMetrics, TAMEstimate
from biocatalyst.models.raw_data import MarketData
from biocatalyst.models.report import (
    AcquisitionAssessment,
    ExpectedValueAnalysis,
    ExpectedValueRow,
    Report,
    ReportSections,
    Scenario,
    ScenarioAnalysis,
    SourceQuality,
)

#: I percorsi relativi sono risolti rispetto al file che chiama AppTest.
APP = str(Path(__file__).parent.parent / "src" / "biocatalyst" / "app.py")


def _report(**overrides: Any) -> Report:
    defaults: dict[str, Any] = {
        "ticker": "ENSC",
        "company_name": "Ensysce Biosciences, Inc.",
        "report_date": date(2026, 8, 26),
        "generated_at": datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
        "current_price": 0.403,
        "rating": "SELL",
        "main_catalyst": "Fase 1 PF614",
        "sections": ReportSections(
            pipeline_and_clinical_results="Panoramica pipeline.",
            catalyst_analysis="Analisi catalizzatore.",
            operational_strategy="Strategia.",
        ),
        "financial_metrics": FinancialMetrics(
            cash_runway_months=0.64,
            quarterly_burn_rate_usd=3_156_097,
            dilution_risk_score=100.0,
            as_of=date(2026, 6, 30),
        ),
        "market_snapshot": MarketData(price=0.403, market_cap_usd=7_841_088),
        "catalysts": [],
        "scenarios": ScenarioAnalysis(
            bull=Scenario(
                probability=0.1, target_price=0.75, target_price_change_pct=86.1, conditions="su"
            ),
            base=Scenario(
                probability=0.4, target_price=0.35, target_price_change_pct=-13.2, conditions="="
            ),
            bear=Scenario(
                probability=0.5, target_price=0.15, target_price_change_pct=-62.8, conditions="giu"
            ),
        ),
        "expected_value": ExpectedValueAnalysis(
            rows=[
                ExpectedValueRow(
                    investment_usd=1000,
                    shares_purchasable=2481.4,
                    expected_value_usd=720.0,
                    expected_roi_pct=-28.0,
                )
            ]
        ),
        "acquisition": AcquisitionAssessment(probability_pct=5.0),
        "tam": TAMEstimate(
            indication="non determinata",
            prevalence_estimate="n/d",
            pricing_comparable="n/d",
            methodology_notes="non prodotta",
        ),
        "source_quality": SourceQuality(),
    }
    defaults.update(overrides)
    return Report(**defaults)


# --- Thread di lavoro ------------------------------------------------------------


def _attendi(stato: StatoAnalisi, secondi: float = 5.0) -> None:
    scadenza = time.monotonic() + secondi
    while not stato.conclusa and time.monotonic() < scadenza:
        time.sleep(0.02)


def test_l_analisi_gira_in_un_thread_e_aggiorna_lo_stato(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La pipeline non deve bloccare il ciclo di rendering della pagina."""
    monkeypatch.setattr("biocatalyst.app.build_data_providers", lambda s: _ProvidersFinti())

    def analisi(ticker: str, **kwargs: Any) -> Report:
        kwargs["on_progress"](3, 4, "MarketNews")
        return _report()

    monkeypatch.setattr("biocatalyst.app.run_analysis", analisi)

    stato = _avvia_analisi("ensc", "it", object())  # type: ignore[arg-type]
    assert stato.ticker == "ENSC"  # normalizzato subito, senza attendere il thread
    _attendi(stato)

    assert stato.conclusa is True
    assert stato.errore is None
    assert stato.report is not None
    assert stato.indice == 3
    assert stato.fase == "MarketNews"


def test_un_errore_nella_pipeline_non_uccide_la_pagina(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers = _ProvidersFinti()
    monkeypatch.setattr("biocatalyst.app.build_data_providers", lambda s: providers)

    def esplode(ticker: str, **kwargs: Any) -> Report:
        raise RuntimeError("fonte irraggiungibile")

    monkeypatch.setattr("biocatalyst.app.run_analysis", esplode)

    stato = _avvia_analisi("ENSC", "it", object())  # type: ignore[arg-type]
    _attendi(stato)

    assert stato.conclusa is True
    assert stato.report is None
    assert stato.errore is not None
    assert "fonte irraggiungibile" in stato.errore
    # I provider vengono chiusi anche in caso di errore.
    assert providers.chiuso is True


class _ProvidersFinti:
    def __init__(self) -> None:
        self.chiuso = False

    def close(self) -> None:
        self.chiuso = True


# --- Rendering della pagina ------------------------------------------------------


def _app(monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "test t@example.com")
    return AppTest.from_file(APP, default_timeout=30)


def test_pagina_iniziale_spiega_cosa_fare(monkeypatch: pytest.MonkeyPatch) -> None:
    at = _app(monkeypatch).run()

    assert not at.exception
    assert any("Inserisci un ticker" in i.value for i in at.info)
    # Il pulsante è presente e attivo con il ticker di default.
    assert at.button[0].label == "Analizza"


def test_barra_laterale_espone_ticker_e_lingua(monkeypatch: pytest.MonkeyPatch) -> None:
    at = _app(monkeypatch).run()

    assert not at.exception
    assert at.sidebar.text_input[0].value == "ENSC"
    # `options` restituisce le etichette mostrate, non i valori grezzi.
    assert at.sidebar.radio[0].options == ["Italiano", "English"]


def test_report_concluso_mostra_metriche_ed_esportazioni(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = _app(monkeypatch)
    at.session_state["analisi"] = StatoAnalisi(
        ticker="ENSC", lingua="it", conclusa=True, report=_report()
    )
    at.run()

    assert not at.exception
    etichette = [m.label for m in at.metric]
    assert "Autonomia di cassa" in etichette
    assert "Rischio diluizione" in etichette
    # Tre pulsanti di scaricamento: Markdown, JSON, PDF.
    assert len(at.download_button) >= 2
    assert any("Markdown" in b.label for b in at.download_button)


def test_gli_avvisi_sui_dati_sono_visibili(monkeypatch: pytest.MonkeyPatch) -> None:
    at = _app(monkeypatch)
    at.session_state["analisi"] = StatoAnalisi(
        ticker="ENSC",
        lingua="it",
        conclusa=True,
        report=_report(
            source_quality=SourceQuality(warnings=["Target analisti 20 volte il prezzo"])
        ),
    )
    at.run()

    assert not at.exception
    assert any("20 volte il prezzo" in w.value for w in at.warning)


def test_un_errore_viene_mostrato_all_utente(monkeypatch: pytest.MonkeyPatch) -> None:
    at = _app(monkeypatch)
    at.session_state["analisi"] = StatoAnalisi(
        ticker="ENSC", lingua="it", conclusa=True, errore="DataUnavailableError: SEC non risponde"
    )
    at.run()

    assert not at.exception
    assert any("SEC non risponde" in e.value for e in at.error)


def test_analisi_in_corso_mostra_l_avanzamento(monkeypatch: pytest.MonkeyPatch) -> None:
    at = _app(monkeypatch)
    at.session_state["analisi"] = StatoAnalisi(
        ticker="ENSC", lingua="it", indice=2, fase="ClinicalFinancialAnalyst"
    )
    at.run()

    assert not at.exception
    # Nessun report mostrato mentre l'analisi è in corso.
    assert not at.metric
    assert not at.download_button
