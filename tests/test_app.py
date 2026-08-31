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

from biocatalyst.app import Job, _start_analysis
from biocatalyst.models.analysis import Catalyst, FinancialMetrics, TAMEstimate
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
from biocatalyst.models.screening import ScreenCandidate, ScreenCriteria, ScreenResult

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
        "main_catalyst": "Phase 1 PF614",
        "sections": ReportSections(
            pipeline_and_clinical_results="Pipeline overview.",
            catalyst_analysis="Catalyst analysis.",
            operational_strategy="Strategy.",
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
                probability=0.1, target_price=0.75, target_price_change_pct=86.1, conditions="up"
            ),
            base=Scenario(
                probability=0.4, target_price=0.35, target_price_change_pct=-13.2, conditions="flat"
            ),
            bear=Scenario(
                probability=0.5, target_price=0.15, target_price_change_pct=-62.8, conditions="down"
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
            indication="not determined",
            prevalence_estimate="n/a",
            pricing_comparable="n/a",
            methodology_notes="not produced",
        ),
        "source_quality": SourceQuality(),
    }
    defaults.update(overrides)
    return Report(**defaults)


def _screen_result(**overrides: Any) -> ScreenResult:
    candidate = ScreenCandidate(
        ticker="AAA",
        company_name="Alpha Bio",
        sector="Biotechnology",
        price=5.0,
        market_cap_usd=100_000_000,
        main_drug="Study X",
        indication="Oncology",
        catalyst=Catalyst(
            name="Phase 3",
            catalyst_type="clinical_readout",
            expected_date=date(2026, 12, 1),
            source="ClinicalTrials.gov NCT1",
            imminence_rank=1,
        ),
        cash_runway_months=4.0,
        financing_risk="Cash covers 4.0 months against the 12.0 remaining.",
        attractiveness_score=80.0,
        rationale="Test rationale.",
        key_risks=["First risk"],
    )
    defaults: dict[str, Any] = {
        "criteria": ScreenCriteria(),
        "candidates": [candidate],
        "generated_at": datetime(2026, 8, 26, tzinfo=UTC),
    }
    defaults.update(overrides)
    return ScreenResult(**defaults)


class _FakeProviders:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _wait(job: Job, seconds: float = 5.0) -> None:
    deadline = time.monotonic() + seconds
    while not job.done and time.monotonic() < deadline:
        time.sleep(0.02)


# --- Thread di lavoro ------------------------------------------------------------


def test_l_analisi_gira_in_un_thread_e_aggiorna_lo_stato(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La pipeline non deve bloccare il ciclo di rendering della pagina."""
    monkeypatch.setattr("biocatalyst.app.build_data_providers", lambda s: _FakeProviders())

    def analysis(ticker: str, **kwargs: Any) -> Report:
        kwargs["on_progress"](3, 4, "MarketNews")
        return _report()

    monkeypatch.setattr("biocatalyst.app.run_analysis", analysis)

    job = _start_analysis("ensc", "en", object())  # type: ignore[arg-type]
    assert job.label == "ENSC"  # normalizzato subito, senza attendere il thread
    _wait(job)

    assert job.done is True
    assert job.error is None
    assert isinstance(job.result, Report)
    assert job.step == 3
    assert job.stage == "MarketNews"


def test_un_errore_nella_pipeline_non_uccide_la_pagina(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    providers = _FakeProviders()
    monkeypatch.setattr("biocatalyst.app.build_data_providers", lambda s: providers)

    def boom(ticker: str, **kwargs: Any) -> Report:
        raise RuntimeError("source unreachable")

    monkeypatch.setattr("biocatalyst.app.run_analysis", boom)

    job = _start_analysis("ENSC", "en", object())  # type: ignore[arg-type]
    _wait(job)

    assert job.done is True
    assert job.result is None
    assert job.error is not None
    assert "source unreachable" in job.error
    # I provider vengono chiusi anche in caso di errore.
    assert providers.closed is True


# --- Rendering della pagina ------------------------------------------------------


def _app(monkeypatch: pytest.MonkeyPatch) -> AppTest:
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "test t@example.com")
    return AppTest.from_file(APP, default_timeout=30)


def test_l_interfaccia_e_in_inglese(monkeypatch: pytest.MonkeyPatch) -> None:
    at = _app(monkeypatch).run()

    assert not at.exception
    assert any("Enter a ticker" in i.value for i in at.info)
    etichette = [b.label for b in at.button]
    assert "Analyze" in etichette
    assert at.sidebar.radio[0].label == "Report language"


def test_l_inglese_e_la_lingua_predefinita(monkeypatch: pytest.MonkeyPatch) -> None:
    at = _app(monkeypatch).run()
    assert at.sidebar.radio[0].value == "en"


def test_ci_sono_entrambe_le_schede(monkeypatch: pytest.MonkeyPatch) -> None:
    """L'analisi di un ticker e lo screening sono due modalità distinte."""
    at = _app(monkeypatch).run()

    assert not at.exception
    assert any("Run screen" in b.label for b in at.button)


def test_report_concluso_mostra_metriche_ed_esportazioni(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = _app(monkeypatch)
    at.session_state["analysis_job"] = Job(label="ENSC", done=True, result=_report())
    at.run()

    assert not at.exception
    etichette = [m.label for m in at.metric]
    assert "Cash runway" in etichette
    assert "Dilution risk" in etichette
    assert any("Markdown" in b.label for b in at.download_button)


def test_gli_avvisi_sui_dati_sono_visibili(monkeypatch: pytest.MonkeyPatch) -> None:
    at = _app(monkeypatch)
    at.session_state["analysis_job"] = Job(
        label="ENSC",
        done=True,
        result=_report(
            source_quality=SourceQuality(warnings=["Mean analyst target is 20x the price"])
        ),
    )
    at.run()

    assert not at.exception
    assert any("20x the price" in w.value for w in at.warning)


def test_un_errore_viene_mostrato_all_utente(monkeypatch: pytest.MonkeyPatch) -> None:
    at = _app(monkeypatch)
    at.session_state["analysis_job"] = Job(
        label="ENSC", done=True, error="DataUnavailableError: SEC not responding"
    )
    at.run()

    assert not at.exception
    assert any("SEC not responding" in e.value for e in at.error)


def test_i_risultati_dello_screening_sono_visibili(monkeypatch: pytest.MonkeyPatch) -> None:
    at = _app(monkeypatch)
    at.session_state["screen_job"] = Job(label="screening", done=True, result=_screen_result())
    at.run()

    assert not at.exception
    assert any("1 candidates found" in s.value for s in at.success)
    # Il rischio di rifinanziamento resta visibile accanto alla candidata.
    assert any("Cash covers 4.0 months" in w.value for w in at.warning)


def test_screening_senza_risultati_suggerisce_come_allargare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = _app(monkeypatch)
    at.session_state["screen_job"] = Job(
        label="screening", done=True, result=_screen_result(candidates=[])
    )
    at.run()

    assert not at.exception
    assert any("widening the catalyst window" in w.value for w in at.warning)


def test_analisi_in_corso_non_mostra_il_report(monkeypatch: pytest.MonkeyPatch) -> None:
    at = _app(monkeypatch)
    at.session_state["analysis_job"] = Job(label="ENSC", step=2, stage="Analyst")
    at.run()

    assert not at.exception
    assert not at.metric
    assert not at.download_button


# --- Campo ticker e scorciatoia dallo screening ------------------------------


def test_il_campo_ticker_e_vuoto_all_avvio(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un valore precompilato va cancellato a mano prima di ogni ricerca.

    Il suggerimento resta come `placeholder`, che si vede ma non si deve
    cancellare.
    """
    at = _app(monkeypatch)
    at.run()

    assert not at.exception
    campo = at.text_input[0]
    assert campo.value == ""
    assert campo.placeholder == "ENSC"


def test_dallo_screening_si_lancia_l_analisi_di_una_candidata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Il ticker passa alla pipeline senza doverlo ricopiare a mano."""
    at = _app(monkeypatch)
    at.session_state["screen_job"] = Job(label="screening", done=True, result=_screen_result())
    at.run()

    pulsanti = [b for b in at.button if b.label.startswith("Analyze ")]
    assert pulsanti, "ogni candidata deve avere il suo pulsante"
    assert pulsanti[0].label == "Analyze AAA"

    pulsanti[0].click().run()

    assert not at.exception
    assert at.session_state["ticker_input"] == "AAA", "il campo va precompilato"
    assert at.session_state["active_tab"] == "Analyze a ticker", "e la scheda va cambiata"
    assert at.session_state["analysis_job"].label == "AAA"


def test_il_pulsante_e_disattivato_se_un_analisi_gira_gia(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Due pipeline insieme si contenderebbero la barra di avanzamento."""
    at = _app(monkeypatch)
    at.session_state["screen_job"] = Job(label="screening", done=True, result=_screen_result())
    at.session_state["analysis_job"] = Job(label="SLS", done=False)
    at.run()

    pulsanti = [b for b in at.button if b.label.startswith("Analyze ")]
    assert pulsanti and pulsanti[0].disabled
