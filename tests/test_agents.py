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
from biocatalyst.models.analysis import AnalysisBundle, FinancialMetrics, TAMEstimate
from biocatalyst.models.raw_data import (
    ClinicalTrial,
    CompanyRawData,
    DrugSpending,
    MarketData,
    QuarterlyFinancials,
    ScheduleRevision,
    SECFilingSignals,
    TrialScheduleHistory,
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
    assert any("market data" in m for m in raw.missing_data)
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
    assert any("without the company name" in m for m in context[KEY_RAW_DATA].missing_data)


# --- ClinicalFinancialAnalystAgent --------------------------------------------


#: Valutazione clinica e TAM arrivano in un'unica risposta: sono una sola
#: chiamata all'LLM, per non pagare due volte lo stesso prompt di contesto.
_ANALISI_JSON = (
    '{"clinical":{"study_design_summary":"disegno",'
    '"primary_endpoint_evaluation":"endpoint",'
    '"population_and_comparator_evaluation":"popolazione",'
    '"statistical_power_evaluation":"potenza",'
    '"historical_precedent_comparison":"precedenti"},'
    '"tam":{"indication":"Dolore","prevalence_estimate":"50M",'
    '"pricing_comparable":"$100/mese","tam_low_usd":1000000,'
    '"tam_high_usd":5000000,"methodology_notes":"note"}}'
)


def test_analista_calcola_le_metriche_in_codice() -> None:
    provider = ScriptedProvider([_ANALISI_JSON])
    context = ClinicalFinancialAnalystAgent(provider).run({KEY_RAW_DATA: _raw_data()})

    bundle: AnalysisBundle = context[KEY_ANALYSIS]
    # Media delle due perdite trimestrali fornite.
    assert bundle.metrics.quarterly_burn_rate_usd == pytest.approx(3_063_645.0)
    assert bundle.metrics.cash_runway_months == pytest.approx(0.6626, abs=1e-3)
    assert bundle.metrics.dilution_risk_score == pytest.approx(100.0)
    assert bundle.clinical_assessment is not None
    assert bundle.tam is not None


def test_analista_fa_una_sola_chiamata_llm() -> None:
    """Valutazione clinica e TAM condividono lo stesso contesto: una chiamata sola."""
    provider = ScriptedProvider([_ANALISI_JSON])
    ClinicalFinancialAnalystAgent(provider).run({KEY_RAW_DATA: _raw_data()})
    assert len(provider.calls) == 1


def test_analista_ordina_i_catalizzatori() -> None:
    provider = ScriptedProvider([_ANALISI_JSON])
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
    assert any("not produced" in n for n in bundle.notes)


def test_analista_senza_trial_non_chiama_l_llm() -> None:
    provider = ScriptedProvider()
    context = ClinicalFinancialAnalystAgent(provider).run(
        {KEY_RAW_DATA: _raw_data(clinical_trials=[])}
    )

    assert provider.calls == []
    assert any("no reference study" in n for n in context[KEY_ANALYSIS].notes)


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

    assert "unavailable" in context["market_context"].macro_notes
    assert any("market context" in m for m in context[KEY_MISSING_DATA])


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
    assert report.expected_value.rows[0].investment_usd == 1000.0
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
    assert tam.indication == "not determined"
    assert "not produced" in tam.methodology_notes


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


# --- Scelta dell'asset di riferimento ---------------------------------------------


def test_l_asset_di_riferimento_e_quello_che_pesa_di_piu() -> None:
    """Il caso SELLAS: una Fase 3 conta più di una Fase 1/2 che legge prima.

    La prima versione sceglieva il catalizzatore con la data più vicina e
    finiva per approfondire l'asset secondario, ignorando lo studio di Fase 3
    che è la ragione principale della valutazione.
    """
    from datetime import date

    from biocatalyst.agents.analyst import _lead_trial
    from biocatalyst.analysis import catalysts_from_trials

    fase3_in_ritardo = ClinicalTrial(
        nct_id="NCT_FASE3",
        brief_title="Studio di Fase 3 sull'asset principale",
        phase=["PHASE3"],
        overall_status="ACTIVE_NOT_RECRUITING",
        primary_completion_date=date(2025, 12, 1),
        primary_completion_date_type="ESTIMATED",
        primary_outcome_measure="Overall Survival",
    )
    fase1_futura = ClinicalTrial(
        nct_id="NCT_FASE1",
        brief_title="Studio di Fase 1/2 sull'asset secondario",
        phase=["PHASE1", "PHASE2"],
        overall_status="RECRUITING",
        primary_completion_date=date(2026, 12, 30),
        primary_completion_date_type="ESTIMATED",
    )
    raw = _raw_data(clinical_trials=[fase1_futura, fase3_in_ritardo])
    catalysts = catalysts_from_trials(raw.clinical_trials, today=date(2026, 8, 26))

    scelto = _lead_trial(raw, catalysts)

    assert scelto is not None
    assert scelto.nct_id == "NCT_FASE3"


def test_a_parita_di_fase_vince_il_catalizzatore_piu_vicino() -> None:
    from datetime import date

    from biocatalyst.agents.analyst import _lead_trial
    from biocatalyst.analysis import catalysts_from_trials

    def fase3(nct: str, completion: date) -> ClinicalTrial:
        return ClinicalTrial(
            nct_id=nct,
            brief_title=f"Studio {nct}",
            phase=["PHASE3"],
            overall_status="RECRUITING",
            primary_completion_date=completion,
            primary_completion_date_type="ESTIMATED",
        )

    raw = _raw_data(
        clinical_trials=[
            fase3("NCT_LONTANO", date(2027, 6, 1)),
            fase3("NCT_VICINO", date(2026, 10, 1)),
        ]
    )
    catalysts = catalysts_from_trials(raw.clinical_trials, today=date(2026, 8, 26))

    assert _lead_trial(raw, catalysts).nct_id == "NCT_VICINO"  # type: ignore[union-attr]


def test_il_writer_riceve_l_intera_pipeline_non_solo_l_asset_scelto() -> None:
    """La panoramica deve elencare ogni studio: il valore della società non
    si spiega con un farmaco solo."""
    from datetime import date

    from biocatalyst.agents.report_writer import _build_prompt

    raw = _raw_data(
        clinical_trials=[
            ClinicalTrial(
                nct_id="NCT_UNO",
                brief_title="Primo asset",
                phase=["PHASE3"],
                overall_status="ACTIVE_NOT_RECRUITING",
                primary_completion_date=date(2025, 12, 1),
                primary_completion_date_type="ESTIMATED",
            ),
            ClinicalTrial(
                nct_id="NCT_DUE",
                brief_title="Secondo asset",
                phase=["PHASE1"],
                overall_status="RECRUITING",
                primary_completion_date=date(2026, 12, 30),
                primary_completion_date_type="ESTIMATED",
            ),
        ]
    )
    prompt = _build_prompt(raw, _analysis_bundle(), None, 0.403, "it")

    assert "PIPELINE CLINICA REGISTRATA" in prompt
    assert "NCT_UNO" in prompt
    assert "NCT_DUE" in prompt
    assert "cita TUTTI gli asset" in prompt

    inglese = _build_prompt(raw, _analysis_bundle(), None, 0.403, "en")
    assert "REGISTERED CLINICAL PIPELINE" in inglese
    assert "cite EVERY relevant asset" in inglese


def test_il_prompt_segnala_ritardo_ed_endpoint_a_eventi() -> None:
    from datetime import date

    from biocatalyst.agents.report_writer import _build_prompt
    from biocatalyst.analysis import catalysts_from_trials

    trial = ClinicalTrial(
        nct_id="NCT_REGAL",
        brief_title="Studio a eventi in ritardo",
        phase=["PHASE3"],
        overall_status="ACTIVE_NOT_RECRUITING",
        primary_completion_date=date(2025, 12, 1),
        primary_completion_date_type="ESTIMATED",
        primary_outcome_measure="OS",
    )
    raw = _raw_data(clinical_trials=[trial])
    bundle = _analysis_bundle()
    bundle.catalysts = catalysts_from_trials([trial], today=date(2026, 8, 26))

    prompt = _build_prompt(raw, bundle, None, 0.403, "it")

    assert "[IN RITARDO]" in prompt
    assert "[ENDPOINT A EVENTI]" in prompt
    assert "due letture possibili" in prompt

    inglese = _build_prompt(raw, bundle, None, 0.403, "en")
    assert "[OVERDUE]" in inglese
    assert "[EVENT-DRIVEN ENDPOINT]" in inglese
    assert "both possible readings" in inglese


def test_il_prompt_del_writer_riceve_lo_storico_dei_rinvii() -> None:
    """Distinguere un rinvio isolato da una serie richiede lo storico.

    Senza questi dati il modello vede "in ritardo di 268 giorni" e non ha modo
    di sapere se è la prima volta o la quarta.
    """
    from biocatalyst.agents.report_writer import _build_prompt

    bundle = _analysis_bundle()
    bundle.schedule_history = TrialScheduleHistory(
        nct_id="NCT04229979",
        revisions_total=10,
        first_declared_date=date(2021, 12, 1),
        current_declared_date=date(2025, 12, 1),
        changes=[
            ScheduleRevision(
                revised_on=date(2023, 1, 27),
                previous_date=date(2021, 12, 1),
                new_date=date(2024, 12, 1),
            ),
            ScheduleRevision(
                revised_on=date(2025, 9, 26),
                previous_date=date(2024, 12, 1),
                new_date=date(2025, 12, 1),
            ),
        ],
    )
    prompt = _build_prompt(_raw_data(), bundle, None, 0.403, "it")

    assert "STORICO DELLE DATE" in prompt
    assert "modificata 2 volte" in prompt
    assert "48 mesi" in prompt
    assert "dato misurato" in prompt

    inglese = _build_prompt(_raw_data(), bundle, None, 0.403, "en")
    assert "DECLARED-DATE HISTORY" in inglese
    assert "revised 2 times" in inglese
    assert "48 months" in inglese


def test_il_writer_riceve_il_prezzo_verificato_non_solo_la_stima() -> None:
    """Il prezzo CMS arriva dopo la risposta dell'analista.

    Senza passarlo al writer, il testo del report ripeterebbe la stima del
    modello mentre la tabella accanto mostra la cifra misurata: due numeri
    diversi per la stessa cosa nella stessa pagina.
    """
    from biocatalyst.agents.report_writer import _build_prompt

    bundle = _analysis_bundle()
    bundle.tam = TAMEstimate(
        indication="AML",
        prevalence_estimate="circa 20.000 pazienti",
        pricing_comparable="Onureg, $240.000-300.000 di listino",
        comparable_drug_name="Onureg",
        verified_pricing=DrugSpending(
            brand_name="Onureg",
            year=2024,
            avg_spend_per_beneficiary_usd=129_238.0,
            beneficiaries=1_842,
            medicare_part="D",
        ),
        methodology_notes="stima",
    )
    prompt = _build_prompt(_raw_data(), bundle, None, 0.403, "it")

    assert "PREZZO VERIFICATO" in prompt
    assert "129,238" in prompt
    assert "prevale sulla stima" in prompt
    assert "1,842 beneficiari" in prompt

    inglese = _build_prompt(_raw_data(), bundle, None, 0.403, "en")
    assert "VERIFIED PRICING" in inglese
    assert "takes precedence" in inglese
    assert "1,842 Medicare beneficiaries" in inglese


def test_lo_schema_dell_analista_non_espone_il_prezzo_verificato() -> None:
    """Garanzia strutturale, non un'istruzione nel prompt.

    Finché `verified_pricing` era nello schema, il modello lo vedeva vuoto e
    scriveva "the verified Medicare spending field is left null" in un report
    che due righe sotto lo mostrava compilato. Toglierlo dallo schema rende la
    contraddizione impossibile.
    """
    from biocatalyst.models.analysis import TAMDraft, TrialAndMarketAssessment

    campi_modello = set(TrialAndMarketAssessment.model_fields["tam"].annotation.model_fields)  # type: ignore[union-attr]
    assert "verified_pricing" not in campi_modello
    assert "comparable_drug_name" in campi_modello, "il comparatore lo sceglie il modello"

    # E il prompt realmente inviato non deve nemmeno nominarlo: finché lo
    # faceva, il modello rispondeva spiegando perché il campo era vuoto.
    provider = ScriptedProvider([_ANALISI_JSON])
    ClinicalFinancialAnalystAgent(provider).run(
        {
            KEY_RAW_DATA: _raw_data(
                clinical_trials=[
                    ClinicalTrial(
                        nct_id="NCT_X",
                        brief_title="Studio",
                        phase=["PHASE2"],
                        overall_status="RECRUITING",
                        primary_completion_date=date(2027, 1, 1),
                        primary_completion_date_type="ESTIMATED",
                    )
                ]
            )
        }
    )
    inviato = provider.calls[0]["messages"][0].content
    assert "verified_pricing" not in inviato
    assert "comparable_drug_name" in inviato

    # Il tipo del report resta completo.
    assert "verified_pricing" in set(TAMEstimate.model_fields)
    assert set(TAMDraft.model_fields).issubset(set(TAMEstimate.model_fields))


def test_il_prompt_del_writer_riceve_il_tasso_storico() -> None:
    """Le probabilità degli scenari sono il numero meno fondato del report.

    Senza un termine di paragone il modello le sceglie e basta, e il sistema ci
    calcola sopra l'expected value al centesimo.
    """
    from biocatalyst.agents.report_writer import _build_prompt
    from biocatalyst.analysis.base_rates import base_rate_for

    bundle = _analysis_bundle()
    bundle.base_rate = base_rate_for(["PHASE3"], ["Acute Myeloid Leukemia"])
    prompt = _build_prompt(_raw_data(), bundle, None, 0.403, "it")

    assert "TASSO STORICO DI SUCCESSO" in prompt
    assert "58%" in prompt
    assert "BIO" in prompt
    # Ancoraggio, non vincolo: uno studio può meritare più o meno della media.
    assert "Non è un vincolo" in prompt

    inglese = _build_prompt(_raw_data(), bundle, None, 0.403, "en")
    assert "HISTORICAL SUCCESS RATE" in inglese
    assert "58%" in inglese
    assert "not a constraint" in inglese


def test_l_analista_calcola_il_tasso_dallo_studio_di_riferimento() -> None:
    agente = ClinicalFinancialAnalystAgent(ScriptedProvider([_ANALISI_JSON]))
    raw = _raw_data(
        clinical_trials=[
            ClinicalTrial(
                nct_id="NCT_AML",
                brief_title="GPS in AML",
                phase=["PHASE3"],
                overall_status="ACTIVE_NOT_RECRUITING",
                primary_completion_date=date(2025, 12, 1),
                primary_completion_date_type="ESTIMATED",
                condition=["Acute Myeloid Leukemia"],
            )
        ]
    )
    bundle = agente.run({KEY_RAW_DATA: raw})[KEY_ANALYSIS]

    assert bundle.base_rate is not None
    assert bundle.base_rate.area == "hematology"
    assert bundle.base_rate.transition_pct == pytest.approx(57.8)
