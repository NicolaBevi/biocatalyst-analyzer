from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from biocatalyst.models import (
    AcquisitionAssessment,
    Catalyst,
    ClinicalTrial,
    CompanyRawData,
    ExpectedValueAnalysis,
    ExpectedValueRow,
    FinancialMetrics,
    MarketData,
    QuarterlyFinancials,
    Report,
    ReportSections,
    Scenario,
    ScenarioAnalysis,
    ScreenCandidate,
    ScreenCriteria,
    ScreenResult,
    SourceQuality,
    TAMEstimate,
)


def _catalyst(**overrides: object) -> Catalyst:
    defaults: dict[str, object] = {
        "name": "Lettura dati Fase 3 - Studio XYZ-201",
        "catalyst_type": "clinical_readout",
        "expected_date": date(2026, 10, 15),
        "source": "clinicaltrials.gov NCT05123456",
        "imminence_rank": 1,
    }
    defaults.update(overrides)
    return Catalyst(**defaults)  # type: ignore[arg-type]


def _tam(**overrides: object) -> TAMEstimate:
    defaults: dict[str, object] = {
        "indication": "Carcinoma polmonare non a piccole cellule",
        "prevalence_estimate": "~230.000 nuovi casi/anno negli USA (fonte: SEER)",
        "pricing_comparable": "~$180.000/anno (comparabile: Keytruda)",
        "tam_low_usd": 500_000_000,
        "tam_high_usd": 1_200_000_000,
        "methodology_notes": "Stima conservativa su penetrazione 5-10% della popolazione.",
    }
    defaults.update(overrides)
    return TAMEstimate(**defaults)  # type: ignore[arg-type]


# --- Dati grezzi: i campi mancanti restano None, non stimati -----------------


def test_market_data_permette_campi_mancanti() -> None:
    data = MarketData(price=4.20, market_cap_usd=180_000_000)

    assert data.shares_short is None
    assert data.short_ratio_days is None
    assert data.short_interest_date is None


def test_company_raw_data_traccia_i_dati_non_reperiti() -> None:
    raw = CompanyRawData(
        ticker="ENSC",
        retrieved_at=datetime(2026, 8, 25, tzinfo=UTC),
        market_data=MarketData(price=3.10),
        missing_data=["short interest non disponibile per questo ticker su Yahoo Finance"],
    )

    assert raw.filing_signals is None
    assert len(raw.missing_data) == 1


def test_quarterly_financials_q4_e_un_valore_valido_derivato_per_sottrazione() -> None:
    q = QuarterlyFinancials(
        fiscal_year=2025,
        fiscal_period="Q4",
        period_end=date(2025, 12, 31),
        cash_and_equivalents_usd=42_000_000,
        rd_expense_usd=8_500_000,
        net_income_loss_usd=-6_200_000,
        form_type="10-K",
        filed_date=date(2026, 2, 20),
    )

    # Una perdita trimestrale (tipica per biotech clinical-stage) è un valore negativo valido.
    assert q.net_income_loss_usd is not None
    assert q.net_income_loss_usd < 0


def test_clinical_trial_supporta_fasi_multiple() -> None:
    trial = ClinicalTrial(
        nct_id="NCT05123456",
        brief_title="Studio di Fase 1/2 su XYZ-201",
        phase=["PHASE1", "PHASE2"],
        overall_status="RECRUITING",
        condition=["Non-Small Cell Lung Cancer"],
    )

    assert trial.phase == ["PHASE1", "PHASE2"]
    assert trial.enrollment_count is None


# --- Catalyst: deve avere un'informazione temporale --------------------------


def test_catalyst_richiede_data_o_finestra_temporale() -> None:
    with pytest.raises(ValidationError, match="expected_date_window"):
        _catalyst(expected_date=None, expected_date_window=None)


def test_catalyst_accetta_solo_finestra_temporale() -> None:
    catalyst = _catalyst(expected_date=None, expected_date_window="Q2 2026")
    assert catalyst.expected_date_window == "Q2 2026"


# --- ScenarioAnalysis: le probabilità devono sommare a 1 ---------------------


def test_scenario_analysis_richiede_probabilita_che_sommano_a_uno() -> None:
    with pytest.raises(ValidationError, match="devono sommare a 1"):
        ScenarioAnalysis(
            bull=Scenario(
                probability=0.5, target_price=10, target_price_change_pct=100, conditions="x"
            ),
            base=Scenario(
                probability=0.5, target_price=6, target_price_change_pct=20, conditions="y"
            ),
            bear=Scenario(
                probability=0.5, target_price=2, target_price_change_pct=-60, conditions="z"
            ),
        )


def test_scenario_analysis_accetta_piccoli_errori_di_arrotondamento() -> None:
    # 0.34 + 0.33 + 0.33 = 1.00 esatto, ma testiamo comunque la tolleranza (±0.01).
    analysis = ScenarioAnalysis(
        bull=Scenario(
            probability=0.35, target_price=10, target_price_change_pct=100, conditions="x"
        ),
        base=Scenario(probability=0.33, target_price=6, target_price_change_pct=20, conditions="y"),
        bear=Scenario(
            probability=0.32, target_price=2, target_price_change_pct=-60, conditions="z"
        ),
    )
    assert analysis.bull.probability == 0.35


# --- Report: costruzione completa e round-trip JSON --------------------------


def _full_report() -> Report:
    return Report(
        ticker="ENSC",
        company_name="Example Biotech Corp",
        report_date=date(2026, 8, 25),
        generated_at=datetime(2026, 8, 25, 14, 30, tzinfo=UTC),
        current_price=5.10,
        rating="BUY",
        average_analyst_target=9.0,
        main_catalyst="Dati Fase 3 - Studio XYZ-201",
        sections=ReportSections(
            pipeline_and_clinical_results="Panoramica pipeline...",
            catalyst_analysis="Analisi del catalizzatore principale...",
            operational_strategy="Strategia operativa...",
        ),
        financial_metrics=FinancialMetrics(
            cash_runway_months=14.5,
            quarterly_burn_rate_usd=9_000_000,
            short_squeeze_score=62.0,
            dilution_risk_score=40.0,
            as_of=date(2026, 6, 30),
        ),
        catalysts=[_catalyst()],
        scenarios=ScenarioAnalysis(
            bull=Scenario(
                probability=0.25,
                target_price=14.0,
                target_price_change_pct=174.5,
                conditions="Esito positivo netto",
            ),
            base=Scenario(
                probability=0.45,
                target_price=6.5,
                target_price_change_pct=27.5,
                conditions="Esito parzialmente positivo",
            ),
            bear=Scenario(
                probability=0.30,
                target_price=1.8,
                target_price_change_pct=-64.7,
                conditions="Fallimento del trial",
            ),
        ),
        expected_value=ExpectedValueAnalysis(
            eur_usd_rate=1.1664,
            rate_date=date(2026, 8, 24),
            rows=[
                ExpectedValueRow(
                    investment_usd=1000,
                    shares_purchasable=196.1,
                    expected_value_usd=1225.0,
                    expected_roi_pct=22.5,
                ),
            ],
        ),
        acquisition=AcquisitionAssessment(
            probability_pct=15.0,
            potential_acquirers=["Big Pharma Co."],
            comparable_deals=["Esempio deal comparabile 2025"],
        ),
        tam=_tam(),
        source_quality=SourceQuality(missing_data=["dati storici pre-2024 non disponibili"]),
    )


def test_report_si_costruisce_con_dati_completi() -> None:
    report = _full_report()
    assert report.rating == "BUY"
    # Il disclaimer di default è sempre presente senza doverlo specificare.
    assert "informative" in report.disclaimer


def test_report_round_trip_json() -> None:
    report = _full_report()

    dumped = report.model_dump_json()
    restored = Report.model_validate_json(dumped)

    assert restored == report


# --- Screening ----------------------------------------------------------------


def test_screen_result_con_candidate_multiple() -> None:
    candidate = ScreenCandidate(
        ticker="ENSC",
        company_name="Example Biotech Corp",
        sector="Oncologia",
        price=5.10,
        market_cap_usd=180_000_000,
        main_drug="XYZ-201",
        indication="NSCLC",
        tam=_tam(),
        catalyst=_catalyst(),
        rationale="Catalizzatore entro 3 mesi con cash runway sufficiente a coprirlo.",
        key_risks=["Fallimento endpoint primario", "Diluizione via ATM offering"],
    )
    result = ScreenResult(
        criteria=ScreenCriteria(),
        candidates=[candidate],
        generated_at=datetime(2026, 8, 25, tzinfo=UTC),
    )

    assert result.criteria.max_price_usd == 10.0
    assert result.criteria.max_price_usd_exceptional == 15.0
    assert len(result.candidates) == 1
