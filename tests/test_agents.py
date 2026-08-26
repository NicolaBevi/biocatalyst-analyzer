"""Test degli agenti e della pipeline. Nessuna chiamata di rete reale."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel

from biocatalyst.agents import (
    KEY_ANALYSIS,
    KEY_MISSING_DATA,
    KEY_RAW_DATA,
    KEY_REPORT,
    KEY_TICKER,
    AgentError,
    BaseAgent,
    ClinicalFinancialAnalystAgent,
    DataCollectorAgent,
    MarketNewsAgent,
    ReportDraft,
    ReportWriterAgent,
    build_pipeline,
)
from biocatalyst.agents.data_collector import _sponsor_query
from biocatalyst.config import LLMProviderName
from biocatalyst.data.base import DataUnavailableError
from biocatalyst.llm.base import BaseLLMProvider, LLMServerError, Message
from biocatalyst.llm.structured import (
    LLMStructuredOutputError,
    complete_structured,
    extract_json,
)
from biocatalyst.models.analysis import AnalysisBundle, FinancialMetrics
from biocatalyst.models.raw_data import (
    ClinicalTrial,
    CompanyRawData,
    MarketData,
    QuarterlyFinancials,
    SECFilingSignals,
)

# --- Doppi di test ------------------------------------------------------------


class ScriptedProvider(BaseLLMProvider):
    """Provider che restituisce risposte preconfezionate, senza rete."""

    name: ClassVar[LLMProviderName] = LLMProviderName.DEEPSEEK
    default_model: ClassVar[str] = "fake"
    supports_json_mode: ClassVar[bool] = True
    retry_initial_wait: ClassVar[float] = 0.0

    def __init__(self, responses: list[str] | None = None, error: Exception | None = None) -> None:
        super().__init__(max_retries=1)
        self.responses = responses or []
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def _complete(
        self,
        system: str,
        messages: list[Message],
        *,
        max_tokens: int,
        temperature: float | None,
        **kwargs: Any,
    ) -> str:
        self.calls.append({"system": system, "messages": messages, "kwargs": kwargs})
        if self.error is not None:
            raise self.error
        if not self.responses:
            raise AssertionError("ScriptedProvider senza risposte residue")
        return self.responses.pop(0)


def _raw_data(**overrides: Any) -> CompanyRawData:
    defaults: dict[str, Any] = {
        "ticker": "ENSC",
        "company_name": "Ensysce Biosciences, Inc.",
        "retrieved_at": datetime(2026, 8, 26, tzinfo=UTC),
        "market_data": MarketData(
            price=0.403,
            market_cap_usd=7_841_088,
            float_shares=19_443_174,
            short_percent_of_float=5.86,
            short_ratio_days=0.03,
            analyst_target_mean=8.25,
        ),
        "quarterly_financials": [
            QuarterlyFinancials(
                fiscal_year=2026,
                fiscal_period="Q1",
                period_end=date(2026, 3, 31),
                cash_and_equivalents_usd=745_482,
                net_income_loss_usd=-3_556_415,
                form_type="10-Q",
                filed_date=date(2026, 5, 15),
            ),
            QuarterlyFinancials(
                fiscal_year=2026,
                fiscal_period="Q2",
                period_end=date(2026, 6, 30),
                cash_and_equivalents_usd=676_704,
                net_income_loss_usd=-2_570_875,
                form_type="10-Q",
                filed_date=date(2026, 8, 13),
            ),
        ],
        "filing_signals": SECFilingSignals(
            atm_offering_mentioned=True, warrant_mentioned=True, as_of=date(2026, 8, 26)
        ),
        "clinical_trials": [
            ClinicalTrial(
                nct_id="NCT06500793",
                brief_title="Studio di Fase 1 su PF614",
                phase=["PHASE1"],
                overall_status="RECRUITING",
                enrollment_count=54,
                primary_completion_date=date(2099, 12, 22),
                primary_completion_date_type="ESTIMATED",
                condition=["Pain"],
            )
        ],
    }
    defaults.update(overrides)
    return CompanyRawData(**defaults)


# --- BaseAgent ----------------------------------------------------------------


class _Echo(BaseAgent):
    name: ClassVar[str] = "Echo"
    requires: ClassVar[tuple[str, ...]] = ("obbligatoria",)

    def _run(self, context: dict[str, Any]) -> dict[str, Any]:
        context["prodotta"] = True
        return context


def test_agente_fallisce_se_manca_una_chiave_richiesta() -> None:
    with pytest.raises(AgentError, match="obbligatoria"):
        _Echo().run({})


def test_agente_non_muta_il_contesto_del_chiamante() -> None:
    originale: dict[str, Any] = {"obbligatoria": 1}
    risultato = _Echo().run(originale)

    assert "prodotta" in risultato
    # Il dizionario del chiamante resta intatto: un fallimento a metà pipeline
    # non deve lasciarlo in uno stato parziale.
    assert "prodotta" not in originale


def test_agente_propaga_le_eccezioni() -> None:
    class Rotto(BaseAgent):
        name: ClassVar[str] = "Rotto"

        def _run(self, context: dict[str, Any]) -> dict[str, Any]:
            raise ValueError("guasto")

    with pytest.raises(ValueError, match="guasto"):
        Rotto().run({})


# --- Estrazione JSON ----------------------------------------------------------


@pytest.mark.parametrize(
    ("grezzo", "atteso"),
    [
        ('{"a": 1}', '{"a": 1}'),
        ('```json\n{"a": 1}\n```', '{"a": 1}'),
        ('```\n{"a": 1}\n```', '{"a": 1}'),
        ('Ecco il risultato:\n{"a": 1}\nSpero sia utile.', '{"a": 1}'),
        ("nessun json qui", "nessun json qui"),
    ],
)
def test_extract_json(grezzo: str, atteso: str) -> None:
    assert extract_json(grezzo) == atteso


class _Semplice(BaseModel):
    valore: int


def test_output_strutturato_valida_con_pydantic() -> None:
    provider = ScriptedProvider(['{"valore": 42}'])
    risultato = complete_structured(provider, "sys", [Message(role="user", content="x")], _Semplice)
    assert risultato.valore == 42


def test_output_strutturato_richiede_json_mode_se_supportato() -> None:
    provider = ScriptedProvider(['{"valore": 1}'])
    complete_structured(provider, "sys", [Message(role="user", content="x")], _Semplice)
    assert provider.calls[0]["kwargs"]["response_format"] == {"type": "json_object"}


def test_output_strutturato_ritenta_rimandando_l_errore_al_modello() -> None:
    """Ripetere la richiesta identica darebbe lo stesso esito: si manda l'errore."""
    provider = ScriptedProvider(['{"valore": "non-un-numero"}', '{"valore": 7}'])

    risultato = complete_structured(provider, "sys", [Message(role="user", content="x")], _Semplice)

    assert risultato.valore == 7
    assert len(provider.calls) == 2
    secondo_giro = provider.calls[1]["messages"]
    assert any("non è conforme allo schema" in m.content for m in secondo_giro)


def test_output_strutturato_si_arrende_dopo_i_tentativi() -> None:
    provider = ScriptedProvider(['{"valore": "x"}', '{"valore": "y"}'])
    with pytest.raises(LLMStructuredOutputError, match="_Semplice"):
        complete_structured(provider, "sys", [Message(role="user", content="x")], _Semplice)


# --- DataCollectorAgent -------------------------------------------------------


@pytest.mark.parametrize(
    ("ragione_sociale", "atteso"),
    [
        ("Ensysce Biosciences, Inc.", "Ensysce Biosciences"),
        ("Moderna, Inc.", "Moderna"),
        ("Example Corp", "Example"),
        ("Nome Semplice", "Nome Semplice"),
    ],
)
def test_query_sponsor_toglie_la_forma_societaria(ragione_sociale: str, atteso: str) -> None:
    """Gli enti registrano gli studi senza la forma societaria del nome SEC."""
    assert _sponsor_query(ragione_sociale) == atteso


def _providers_finti() -> MagicMock:
    providers = MagicMock()
    providers.sec.get_company_name.return_value = "Ensysce Biosciences, Inc."
    providers.sec.get_quarterly_financials.return_value = []
    providers.sec.get_filing_signals.return_value = None
    providers.market.get_market_data.return_value = MarketData(price=0.4)
    providers.clinical_trials.get_trials_by_sponsor.return_value = []
    providers.fda.get_approvals_by_sponsor.return_value = []
    return providers


def test_data_collector_registra_le_fonti_fallite_senza_interrompersi() -> None:
    providers = _providers_finti()
    providers.market.get_market_data.side_effect = DataUnavailableError("Yahoo non risponde")

    context = DataCollectorAgent(providers).run({KEY_TICKER: "ensc"})

    raw: CompanyRawData = context[KEY_RAW_DATA]
    assert raw.ticker == "ENSC"  # normalizzato in maiuscolo
    assert raw.market_data is None
    assert any("dati di mercato" in m for m in raw.missing_data)
    assert any("Yahoo non risponde" in m for m in raw.missing_data)


def test_data_collector_ripiega_su_yfinance_per_il_nome() -> None:
    providers = _providers_finti()
    providers.sec.get_company_name.side_effect = DataUnavailableError("SEC giù")
    providers.market.get_company_name.return_value = "Ensysce Biosciences Inc"

    context = DataCollectorAgent(providers).run({KEY_TICKER: "ENSC"})

    assert context[KEY_RAW_DATA].company_name == "Ensysce Biosciences Inc"


def test_data_collector_salta_trial_e_fda_senza_ragione_sociale() -> None:
    providers = _providers_finti()
    providers.sec.get_company_name.return_value = None
    providers.market.get_company_name.return_value = None

    context = DataCollectorAgent(providers).run({KEY_TICKER: "ENSC"})

    providers.clinical_trials.get_trials_by_sponsor.assert_not_called()
    assert any("senza la ragione sociale" in m for m in context[KEY_RAW_DATA].missing_data)


# --- ClinicalFinancialAnalystAgent --------------------------------------------


_CLINICA_JSON = (
    '{"study_design_summary":"disegno","primary_endpoint_evaluation":"endpoint",'
    '"population_and_comparator_evaluation":"popolazione",'
    '"statistical_power_evaluation":"potenza","historical_precedent_comparison":"precedenti"}'
)
_TAM_JSON = (
    '{"indication":"Dolore","prevalence_estimate":"50M","pricing_comparable":"$100/mese",'
    '"tam_low_usd":1000000,"tam_high_usd":5000000,"methodology_notes":"note"}'
)


def test_analista_calcola_le_metriche_in_codice() -> None:
    provider = ScriptedProvider([_CLINICA_JSON, _TAM_JSON])
    context = ClinicalFinancialAnalystAgent(provider).run({KEY_RAW_DATA: _raw_data()})

    bundle: AnalysisBundle = context[KEY_ANALYSIS]
    # Media delle due perdite trimestrali fornite.
    assert bundle.metrics.quarterly_burn_rate_usd == pytest.approx(3_063_645.0)
    assert bundle.metrics.cash_runway_months == pytest.approx(0.6626, abs=1e-3)
    assert bundle.metrics.dilution_risk_score == pytest.approx(100.0)
    assert bundle.clinical_assessment is not None
    assert bundle.tam is not None


def test_analista_ordina_i_catalizzatori() -> None:
    provider = ScriptedProvider([_CLINICA_JSON, _TAM_JSON])
    context = ClinicalFinancialAnalystAgent(provider).run({KEY_RAW_DATA: _raw_data()})

    catalysts = context[KEY_ANALYSIS].catalysts
    assert len(catalysts) == 1
    assert catalysts[0].imminence_rank == 1
    assert "NCT06500793" in catalysts[0].source


def test_analista_sopravvive_al_fallimento_dell_llm() -> None:
    """Le metriche deterministiche restano disponibili anche senza il modello."""
    provider = ScriptedProvider(error=LLMServerError("provider giù"))

    context = ClinicalFinancialAnalystAgent(provider).run({KEY_RAW_DATA: _raw_data()})

    bundle: AnalysisBundle = context[KEY_ANALYSIS]
    assert bundle.metrics.quarterly_burn_rate_usd is not None
    assert bundle.clinical_assessment is None
    assert bundle.tam is None
    assert any("valutazione clinica non prodotta" in n for n in bundle.notes)


def test_analista_senza_trial_non_chiama_l_llm() -> None:
    provider = ScriptedProvider()
    context = ClinicalFinancialAnalystAgent(provider).run(
        {KEY_RAW_DATA: _raw_data(clinical_trials=[])}
    )

    assert provider.calls == []
    assert any("nessuno studio di riferimento" in n for n in context[KEY_ANALYSIS].notes)


# --- MarketNewsAgent ----------------------------------------------------------

_MERCATO_JSON = (
    '{"macro_notes":"contesto macro","verified_facts":["fatto"],'
    '"market_speculation":["voce"],"acquisition_rumors":[]}'
)


def test_market_news_sovrascrive_il_sentiment_con_i_dati_misurati() -> None:
    """Il sentiment è misurato: il modello non deve poterlo alterare."""
    from biocatalyst.models.raw_data import SectorSentiment

    misurato = [
        SectorSentiment(symbol="XBI", period_days=30, price_change_pct=8.2, as_of=date(2026, 8, 25))
    ]
    providers = MagicMock()
    providers.news.get_company_news.return_value = []
    providers.market.get_sector_sentiment.return_value = misurato
    # Il modello prova a dichiarare un sentiment inventato.
    provider = ScriptedProvider(
        [
            '{"macro_notes":"x","verified_facts":[],"market_speculation":[],'
            '"acquisition_rumors":[],"sector_sentiment":[{"symbol":"FALSO",'
            '"period_days":1,"price_change_pct":999,"as_of":"2020-01-01"}]}'
        ]
    )

    context = MarketNewsAgent(provider, providers).run({KEY_RAW_DATA: _raw_data()})

    sentiment = context["market_context"].sector_sentiment
    assert [s.symbol for s in sentiment] == ["XBI"]
    assert sentiment[0].price_change_pct == 8.2


def test_market_news_degrada_se_l_llm_fallisce() -> None:
    providers = MagicMock()
    providers.news.get_company_news.return_value = []
    providers.market.get_sector_sentiment.return_value = []
    provider = ScriptedProvider(error=LLMServerError("giù"))

    context = MarketNewsAgent(provider, providers).run({KEY_RAW_DATA: _raw_data()})

    assert "non disponibile" in context["market_context"].macro_notes
    assert any("contesto di mercato" in m for m in context[KEY_MISSING_DATA])


# --- ReportWriterAgent --------------------------------------------------------


def test_lo_schema_del_modello_non_contiene_campi_aritmetici() -> None:
    """Garanzia strutturale: l'LLM non può fornire percentuali o valori attesi."""
    campi = set(ReportDraft.model_fields)
    vietati = {
        "target_price_change_pct",
        "expected_value_eur",
        "expected_roi_pct",
        "shares_purchasable",
    }
    assert campi.isdisjoint(vietati)

    campi_scenario = set(ReportDraft.model_fields["bull"].annotation.model_fields)  # type: ignore[union-attr]
    assert campi_scenario == {"probability", "target_price", "conditions"}


_REPORT_JSON = (
    '{"rating":"SELL","main_catalyst":"Fase 1 PF614",'
    '"pipeline_and_clinical_results":"pipeline","catalyst_analysis":"catalizzatore",'
    '"operational_strategy":"strategia",'
    '"bull":{"probability":0.1,"target_price":0.75,"conditions":"dati positivi"},'
    '"base":{"probability":0.4,"target_price":0.35,"conditions":"neutro"},'
    '"bear":{"probability":0.5,"target_price":0.15,"conditions":"fallimento"},'
    '"acquisition_probability_pct":5.0,"potential_acquirers":["Pfizer"],'
    '"comparable_deals":["deal 2025"]}'
)


def _writer_providers() -> MagicMock:
    providers = MagicMock()
    tasso = MagicMock()
    tasso.rate = 1.1662
    tasso.rate_date = date(2026, 8, 25)
    providers.forex.get_eur_usd.return_value = tasso
    return providers


def _analysis_bundle() -> AnalysisBundle:
    return AnalysisBundle(
        metrics=FinancialMetrics(
            cash_runway_months=0.64,
            quarterly_burn_rate_usd=3_156_097,
            short_squeeze_score=19.8,
            dilution_risk_score=100.0,
            as_of=date(2026, 6, 30),
        )
    )


def test_writer_calcola_expected_value_e_variazioni_in_python() -> None:
    provider = ScriptedProvider([_REPORT_JSON])
    context = ReportWriterAgent(provider, _writer_providers()).run(
        {KEY_RAW_DATA: _raw_data(), KEY_ANALYSIS: _analysis_bundle()}
    )

    report = context[KEY_REPORT]
    # 0,1*0,75 + 0,4*0,35 + 0,5*0,15 = 0,29 contro un prezzo di 0,403
    assert report.expected_value.rows[0].expected_roi_pct == pytest.approx(-28.04, abs=0.01)
    assert report.scenarios.bull.target_price_change_pct == pytest.approx(86.10, abs=0.01)
    assert report.expected_value.eur_usd_rate == 1.1662
    assert report.expected_value.rate_date == date(2026, 8, 25)
    assert report.rating == "SELL"


def test_writer_usa_un_segnaposto_esplicito_se_manca_il_tam() -> None:
    provider = ScriptedProvider([_REPORT_JSON])
    context = ReportWriterAgent(provider, _writer_providers()).run(
        {KEY_RAW_DATA: _raw_data(), KEY_ANALYSIS: _analysis_bundle()}
    )

    tam = context[KEY_REPORT].tam
    assert tam.indication == "non determinata"
    assert "non prodotta" in tam.methodology_notes


def test_writer_fallisce_esplicitamente_senza_prezzo() -> None:
    provider = ScriptedProvider([_REPORT_JSON])
    raw = _raw_data(market_data=None)

    with pytest.raises(AgentError, match="prezzo corrente"):
        ReportWriterAgent(provider, _writer_providers()).run(
            {KEY_RAW_DATA: raw, KEY_ANALYSIS: _analysis_bundle()}
        )


def test_writer_riporta_i_dati_mancanti_accumulati() -> None:
    provider = ScriptedProvider([_REPORT_JSON])
    context = ReportWriterAgent(provider, _writer_providers()).run(
        {
            KEY_RAW_DATA: _raw_data(),
            KEY_ANALYSIS: _analysis_bundle(),
            KEY_MISSING_DATA: ["notizie: chiave assente", "notizie: chiave assente"],
        }
    )

    # Deduplicati e ordinati.
    assert context[KEY_REPORT].source_quality.missing_data == ["notizie: chiave assente"]


# --- Pipeline -----------------------------------------------------------------


def test_pipeline_ha_i_quattro_agenti_nell_ordine_giusto(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "biocatalyst.agents.pipeline.provider_for_agent", lambda *a, **k: ScriptedProvider()
    )
    agents = build_pipeline(MagicMock(), MagicMock())

    assert [a.name for a in agents] == [
        "DataCollector",
        "ClinicalFinancialAnalyst",
        "MarketNews",
        "ReportWriter",
    ]
