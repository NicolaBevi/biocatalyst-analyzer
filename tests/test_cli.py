"""Test della CLI. La pipeline è sostituita da un doppio: nessuna chiamata reale."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from biocatalyst.agents import AgentError
from biocatalyst.cli import _parse_formats, _settings_for, app
from biocatalyst.config import LLMProviderName
from biocatalyst.data.base import DataUnavailableError
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

runner = CliRunner()


def _report(ticker: str = "ENSC", roi: float = -28.0, **overrides: Any) -> Report:
    defaults: dict[str, Any] = {
        "ticker": ticker,
        "company_name": f"{ticker} Inc.",
        "report_date": date(2026, 8, 26),
        "generated_at": datetime(2026, 8, 26, 12, 0, tzinfo=UTC),
        "current_price": 0.403,
        "rating": "SELL",
        "main_catalyst": "Fase 1 PF614",
        "sections": ReportSections(
            pipeline_and_clinical_results="pipeline",
            catalyst_analysis="catalizzatore",
            operational_strategy="strategia",
        ),
        "financial_metrics": FinancialMetrics(
            cash_runway_months=0.64,
            quarterly_burn_rate_usd=3_156_097,
            short_squeeze_score=19.8,
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
                    expected_roi_pct=roi,
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


@pytest.fixture(autouse=True)
def _pipeline_finta(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Sostituisce pipeline e provider dati: i test non devono toccare la rete."""
    monkeypatch.setattr("biocatalyst.cli.build_data_providers", lambda *a, **k: _ProvidersFinti())
    monkeypatch.setattr("biocatalyst.cli.DEFAULT_REPORTS_DIR", tmp_path / "reports")
    monkeypatch.setattr(
        "biocatalyst.cli.run_analysis",
        lambda ticker, **kwargs: _report(ticker.upper()),
    )


class _ProvidersFinti:
    def close(self) -> None:
        self.chiuso = True


# --- Validazione dei parametri --------------------------------------------------


@pytest.mark.parametrize(
    ("valore", "atteso"),
    [
        ("md", (".md",)),
        ("md,json", (".md", ".json")),
        (".md, .pdf", (".md", ".pdf")),
        ("MD,PDF", (".md", ".pdf")),
    ],
)
def test_parse_formats(valore: str, atteso: tuple[str, ...]) -> None:
    assert _parse_formats(valore) == atteso


def test_parse_formats_rifiuta_estensioni_ignote() -> None:
    with pytest.raises(Exception, match="unsupported formats"):
        _parse_formats("docx")


def test_parse_formats_rifiuta_stringa_vuota() -> None:
    with pytest.raises(Exception, match="at least one format"):
        _parse_formats("")


def test_formato_non_valido_fallisce_prima_di_analizzare(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un formato sbagliato scoperto a valle costerebbe un'analisi a pagamento."""
    chiamate = []
    monkeypatch.setattr(
        "biocatalyst.cli.run_analysis",
        lambda ticker, **kw: chiamate.append(ticker) or _report(),
    )

    result = runner.invoke(app, ["analyze", "ENSC", "--formats", "docx"])

    assert result.exit_code != 0
    assert chiamate == []  # la pipeline non è mai partita


def test_provider_sconosciuto_viene_rifiutato() -> None:
    result = runner.invoke(app, ["analyze", "ENSC", "--provider", "inesistente"])
    assert result.exit_code != 0
    assert "unknown provider" in result.output


def test_lingua_non_valida_viene_rifiutata() -> None:
    result = runner.invoke(app, ["analyze", "ENSC", "--language", "fr"])
    assert result.exit_code != 0


# --- Override della configurazione ----------------------------------------------


def test_override_provider_azzera_i_modelli_per_agente(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un modello valido per un provider non lo è per un altro."""
    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", "test t@example.com")
    monkeypatch.setenv("DEFAULT_PROVIDER", "deepseek")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant")
    monkeypatch.setenv("AGENT_WRITER_MODEL", "deepseek-v4-pro")
    from biocatalyst.config import get_settings

    get_settings.cache_clear()

    settings = _settings_for("anthropic", None)

    assert settings.default_provider is LLMProviderName.ANTHROPIC
    assert settings.agent_writer_model is None
    assert settings.agent_analyst_provider is None
    get_settings.cache_clear()


def test_override_lingua() -> None:
    assert _settings_for(None, "en").report_language == "en"


def test_senza_override_la_configurazione_resta_invariata() -> None:
    from biocatalyst.config import get_settings

    assert _settings_for(None, None) is get_settings()


# --- analyze ---------------------------------------------------------------------


def test_analyze_salva_in_cartella_per_ticker(tmp_path: Path) -> None:
    result = runner.invoke(app, ["analyze", "ensc", "--formats", "md,json"])

    assert result.exit_code == 0
    cartella = tmp_path / "reports" / "ENSC"
    assert (cartella / "ENSC_2026-08-26_en.md").exists()
    assert (cartella / "ENSC_2026-08-26_en.json").exists()


def test_analyze_con_output_esplicito(tmp_path: Path) -> None:
    destinazione = tmp_path / "mio_report.md"
    result = runner.invoke(app, ["analyze", "ENSC", "--output", str(destinazione)])

    assert result.exit_code == 0
    assert destinazione.exists()


def test_analyze_mostra_il_riassunto() -> None:
    result = runner.invoke(app, ["analyze", "ENSC", "--formats", "md"])

    assert result.exit_code == 0
    assert "SELL" in result.output
    assert "0.64 months" in result.output or "0.6 months" in result.output


def test_analyze_mostra_gli_avvisi(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "biocatalyst.cli.run_analysis",
        lambda ticker, **kw: _report(
            source_quality=SourceQuality(warnings=["Target analisti sospetto"])
        ),
    )

    result = runner.invoke(app, ["analyze", "ENSC", "--formats", "md"])

    assert "Target analisti sospetto" in result.output


def test_analyze_traduce_gli_errori_in_messaggi_leggibili(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def esplode(ticker: str, **kwargs: Any) -> Report:
        raise DataUnavailableError("Yahoo Finance non risponde")

    monkeypatch.setattr("biocatalyst.cli.run_analysis", esplode)

    result = runner.invoke(app, ["analyze", "ENSC"])

    assert result.exit_code == 1
    assert "Yahoo Finance non risponde" in result.output
    # Nessun traceback nell'output.
    assert "Traceback" not in result.output


def test_analyze_chiude_sempre_i_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    providers = _ProvidersFinti()
    monkeypatch.setattr("biocatalyst.cli.build_data_providers", lambda *a, **k: providers)

    def esplode(ticker: str, **kwargs: Any) -> Report:
        raise AgentError("guasto")

    monkeypatch.setattr("biocatalyst.cli.run_analysis", esplode)
    runner.invoke(app, ["analyze", "ENSC"])

    assert getattr(providers, "chiuso", False) is True


# --- compare ----------------------------------------------------------------------


def test_compare_richiede_almeno_due_ticker() -> None:
    result = runner.invoke(app, ["compare", "ENSC"])
    assert result.exit_code != 0
    assert "at least two tickers" in result.output


def test_compare_ordina_per_rendimento_atteso(monkeypatch: pytest.MonkeyPatch) -> None:
    rendimenti = {"AAA": -50.0, "BBB": 30.0, "CCC": -10.0}
    monkeypatch.setattr(
        "biocatalyst.cli.run_analysis",
        lambda ticker, **kw: _report(ticker.upper(), roi=rendimenti[ticker.upper()]),
    )

    result = runner.invoke(app, ["compare", "AAA", "BBB", "CCC", "--no-save"])

    assert result.exit_code == 0
    # Il migliore per primo: il confronto serve a scegliere.
    posizioni = [result.output.index(t) for t in ("BBB", "CCC", "AAA")]
    tabella = result.output[result.output.index("Comparison") :]
    assert tabella.index("BBB") < tabella.index("CCC") < tabella.index("AAA")
    assert posizioni  # i tre ticker compaiono tutti


def test_compare_prosegue_se_un_ticker_fallisce(monkeypatch: pytest.MonkeyPatch) -> None:
    def analizza(ticker: str, **kwargs: Any) -> Report:
        if ticker.upper() == "ROTTO":
            raise DataUnavailableError("fonte irraggiungibile")
        return _report(ticker.upper())

    monkeypatch.setattr("biocatalyst.cli.run_analysis", analizza)

    result = runner.invoke(app, ["compare", "ENSC", "ROTTO", "--no-save"])

    assert result.exit_code == 0
    assert "ENSC" in result.output
    assert "Not analyzed: ROTTO" in result.output


def test_compare_fallisce_se_nessun_ticker_riesce(monkeypatch: pytest.MonkeyPatch) -> None:
    def esplode(ticker: str, **kwargs: Any) -> Report:
        raise DataUnavailableError("giù")

    monkeypatch.setattr("biocatalyst.cli.run_analysis", esplode)

    result = runner.invoke(app, ["compare", "AAA", "BBB", "--no-save"])

    assert result.exit_code == 1
    assert "No ticker could be analyzed" in result.output


# --- screen e version --------------------------------------------------------------


def _screen_result(candidate: list[Any]) -> Any:
    from datetime import UTC, datetime

    from biocatalyst.models.screening import ScreenCriteria, ScreenResult

    return ScreenResult(
        criteria=ScreenCriteria(),
        candidates=candidate,
        generated_at=datetime(2026, 8, 26, tzinfo=UTC),
    )


def _candidata(ticker: str = "AAA", punteggio: float = 80.0, eccezionale: bool = False) -> Any:
    from biocatalyst.models.analysis import Catalyst
    from biocatalyst.models.screening import ScreenCandidate

    return ScreenCandidate(
        ticker=ticker,
        company_name=f"{ticker} Bio",
        sector="Biotecnologie",
        price=5.0,
        market_cap_usd=100_000_000,
        main_drug="Studio X",
        indication="Oncologia",
        catalyst=Catalyst(
            name="Fase 3",
            catalyst_type="clinical_readout",
            expected_date=date(2026, 12, 1),
            source="ClinicalTrials.gov NCT1",
            imminence_rank=1,
        ),
        cash_runway_months=14.0,
        attractiveness_score=punteggio,
        exceptional=eccezionale,
        rationale="Motivazione di prova.",
        key_risks=["Rischio uno"],
    )


def test_screen_mostra_le_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "biocatalyst.cli.run_screen", lambda **kw: _screen_result([_candidata("AAA")])
    )

    result = runner.invoke(app, ["screen", "--max-price", "5"])

    assert result.exit_code == 0
    assert "AAA" in result.output
    assert "Motivazione di prova" in result.output
    assert "Rischio uno" in result.output


def test_screen_passa_i_criteri_della_riga_di_comando(monkeypatch: pytest.MonkeyPatch) -> None:
    ricevuti = {}
    monkeypatch.setattr(
        "biocatalyst.cli.run_screen",
        lambda **kw: ricevuti.update(kw) or _screen_result([_candidata()]),
    )

    runner.invoke(app, ["screen", "--max-price", "7", "--catalyst-window", "3", "--limit", "4"])

    criteri = ricevuti["criteria"]
    assert criteri.max_price_usd == 7.0
    assert criteri.catalyst_window_months == 3
    assert ricevuti["max_candidates"] == 4


def test_screen_segnala_le_candidate_eccezionali(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "biocatalyst.cli.run_screen",
        lambda **kw: _screen_result([_candidata(eccezionale=True)]),
    )

    result = runner.invoke(app, ["screen"])

    assert "exception" in result.output


def test_screen_senza_risultati_suggerisce_come_allargare(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("biocatalyst.cli.run_screen", lambda **kw: _screen_result([]))

    result = runner.invoke(app, ["screen"])

    assert result.exit_code == 0
    assert "No stock meets the criteria" in result.output
    assert "widening" in result.output


def test_screen_salva_il_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("biocatalyst.cli.run_screen", lambda **kw: _screen_result([_candidata()]))
    destinazione = tmp_path / "screen.json"

    result = runner.invoke(app, ["screen", "--output", str(destinazione)])

    assert result.exit_code == 0
    assert json.loads(destinazione.read_text())["candidates"][0]["ticker"] == "AAA"


def test_screen_traduce_gli_errori(monkeypatch: pytest.MonkeyPatch) -> None:
    def esplode(**kwargs: Any) -> Any:
        raise DataUnavailableError("SEC non risponde")

    monkeypatch.setattr("biocatalyst.cli.run_screen", esplode)

    result = runner.invoke(app, ["screen"])

    assert result.exit_code == 1
    assert "SEC non risponde" in result.output


def test_version() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "biocatalyst-analyzer" in result.output
