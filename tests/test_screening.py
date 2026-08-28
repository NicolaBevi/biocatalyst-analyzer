"""Test della modalità screen: universo, filtri deterministici, orchestrazione."""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
import respx

from biocatalyst.analysis.screening import (
    RISK_APPETITE_LABELS,
    RISK_APPETITES,
    attractiveness_score,
    imminence_score,
    meets_phase_requirement,
    months_to_catalyst,
    passes_price_and_size,
    phase_score,
    risk_appetite_label,
    runway_coverage_score,
    size_score,
)
from biocatalyst.data import RateLimiter
from biocatalyst.data.universe import (
    BROWSE_EDGAR_URL,
    TICKERS_EXCHANGE_URL,
    UniverseProvider,
)
from biocatalyst.models.analysis import Catalyst
from biocatalyst.models.raw_data import ClinicalTrial, MarketData
from biocatalyst.models.screening import ScreenCriteria
from biocatalyst.screening import screen

OGGI = date(2026, 8, 26)


@pytest.fixture(autouse=True)
def _no_rate_limiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(RateLimiter, "wait", lambda self: None)


def _catalizzatore(giorni: int = 90) -> Catalyst:
    from datetime import timedelta

    return Catalyst(
        name="Fase 2 studio X",
        catalyst_type="clinical_readout",
        expected_date=OGGI + timedelta(days=giorni),
        source="ClinicalTrials.gov NCT001",
        imminence_rank=1,
    )


def _criteri(**overrides: Any) -> ScreenCriteria:
    defaults: dict[str, Any] = {
        "max_price_usd": 10.0,
        "max_price_usd_exceptional": 15.0,
        "market_cap_max_usd": 500_000_000,
        "market_cap_max_usd_exceptional": 2_000_000_000,
        "catalyst_window_months": 6,
    }
    defaults.update(overrides)
    return ScreenCriteria(**defaults)


# --- Filtro prezzo e dimensione --------------------------------------------------


def test_titolo_dentro_le_soglie_ordinarie() -> None:
    esito = passes_price_and_size(5.0, 200_000_000, _criteri())
    assert esito.passed is True
    assert esito.exceptional is False


def test_titolo_nella_banda_eccezionale_viene_incluso_e_marcato() -> None:
    """I requisiti chiedono di non scartarlo ma di segnalarlo motivandolo."""
    esito = passes_price_and_size(12.0, 200_000_000, _criteri())
    assert esito.passed is True
    assert esito.exceptional is True


def test_capitalizzazione_nella_banda_eccezionale() -> None:
    esito = passes_price_and_size(5.0, 900_000_000, _criteri())
    assert esito.passed is True
    assert esito.exceptional is True


def test_titolo_oltre_il_limite_assoluto_viene_scartato() -> None:
    esito = passes_price_and_size(20.0, 100_000_000, _criteri())
    assert esito.passed is False
    assert esito.reason is not None
    assert "prezzo" in esito.reason


def test_capitalizzazione_oltre_il_limite_assoluto() -> None:
    esito = passes_price_and_size(5.0, 5_000_000_000, _criteri())
    assert esito.passed is False
    assert esito.reason is not None
    assert "capitalizzazione" in esito.reason


@pytest.mark.parametrize(("prezzo", "cap"), [(None, 100_000_000), (5.0, None), (None, None)])
def test_dati_mancanti_escludono_il_titolo(prezzo: float | None, cap: float | None) -> None:
    esito = passes_price_and_size(prezzo, cap, _criteri())
    assert esito.passed is False
    assert esito.reason is not None


# --- Fasi -------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fasi", "minimo", "atteso"),
    [
        (["PHASE3"], "PHASE2", True),
        (["PHASE2"], "PHASE2", True),
        (["PHASE1"], "PHASE2", False),
        (["PHASE1", "PHASE2"], "PHASE2", True),  # basta che una raggiunga il minimo
        (["NA"], "PHASE2", False),
        ([], "PHASE2", False),
        (["EARLY_PHASE1"], "PHASE1", False),
        (["phase3"], "PHASE2", True),  # confronto insensibile alle maiuscole
    ],
)
def test_requisito_di_fase(fasi: list[str], minimo: str, atteso: bool) -> None:
    assert meets_phase_requirement(fasi, minimo) is atteso


def test_punteggio_di_fase_cresce_con_l_avanzamento() -> None:
    assert phase_score(["PHASE3"]) > phase_score(["PHASE1"])  # type: ignore[operator]
    assert phase_score(["PHASE4"]) == 100.0
    assert phase_score([]) is None
    assert phase_score(["NA"]) is None


# --- Imminenza --------------------------------------------------------------------


def test_mesi_al_catalizzatore() -> None:
    assert months_to_catalyst(_catalizzatore(giorni=91), OGGI) == pytest.approx(3.0, abs=0.05)


def test_mesi_al_catalizzatore_senza_data_puntuale() -> None:
    c = Catalyst(
        name="x",
        catalyst_type="clinical_readout",
        expected_date_window="Q2 2027",
        source="s",
        imminence_rank=1,
    )
    assert months_to_catalyst(c, OGGI) is None


def test_imminenza_premia_i_catalizzatori_vicini() -> None:
    vicino = imminence_score(1.0, 6)
    lontano = imminence_score(5.0, 6)
    assert vicino > lontano
    assert imminence_score(0.0, 6) == pytest.approx(100.0)


def test_imminenza_azzerata_fuori_finestra_o_nel_passato() -> None:
    assert imminence_score(12.0, 6) == 0.0
    assert imminence_score(-1.0, 6) == 0.0
    assert imminence_score(None, 6) == 0.0


# --- Copertura di cassa ------------------------------------------------------------


def test_copertura_piena_con_cassa_doppia_rispetto_all_attesa() -> None:
    assert runway_coverage_score(12.0, 6.0) == pytest.approx(100.0)
    assert runway_coverage_score(24.0, 6.0) == pytest.approx(100.0)


def test_copertura_parziale() -> None:
    """Cassa pari all'attesa: metà punteggio, perché il margine è nullo."""
    assert runway_coverage_score(6.0, 6.0) == pytest.approx(50.0)


def test_copertura_nulla_se_la_cassa_finisce_prima() -> None:
    punteggio = runway_coverage_score(0.5, 6.0)
    assert punteggio is not None
    assert punteggio < 10.0


def test_copertura_none_se_manca_un_dato() -> None:
    assert runway_coverage_score(None, 6.0) is None
    assert runway_coverage_score(6.0, None) is None


def test_copertura_piena_se_il_catalizzatore_e_gia_arrivato() -> None:
    assert runway_coverage_score(1.0, 0.0) == 100.0


# --- Dimensione ---------------------------------------------------------------------


def test_dimensione_premia_le_capitalizzazioni_piccole() -> None:
    piccola = size_score(50_000_000, _criteri())
    grande = size_score(1_500_000_000, _criteri())
    assert piccola is not None and grande is not None
    assert piccola > grande


def test_dimensione_none_su_dati_non_validi() -> None:
    assert size_score(None, _criteri()) is None
    assert size_score(0, _criteri()) is None
    assert size_score(-1, _criteri()) is None


# --- Punteggio composito -------------------------------------------------------------


def test_punteggio_alto_con_catalizzatore_vicino_e_cassa_capiente() -> None:
    punteggio = attractiveness_score(
        catalyst=_catalizzatore(giorni=30),
        criteria=_criteri(),
        market_cap=20_000_000,
        cash_runway_months=24.0,
        phases=["PHASE3"],
        today=OGGI,
    )
    assert punteggio > 80


def test_punteggio_penalizza_la_cassa_insufficiente() -> None:
    """La cassa deve bastare fino al catalizzatore: è il criterio centrale."""
    comune: dict[str, Any] = {
        "catalyst": _catalizzatore(giorni=180),
        "criteria": _criteri(),
        "market_cap": 20_000_000,
        "phases": ["PHASE3"],
        "today": OGGI,
    }
    capiente = attractiveness_score(cash_runway_months=24.0, **comune)
    esaurita = attractiveness_score(cash_runway_months=1.0, **comune)
    assert capiente > esaurita


def test_punteggio_ridistribuisce_i_pesi_mancanti() -> None:
    punteggio = attractiveness_score(
        catalyst=_catalizzatore(giorni=30),
        criteria=_criteri(),
        market_cap=None,
        cash_runway_months=None,
        phases=[],
        today=OGGI,
    )
    # Resta la sola imminenza: punteggio valido, non zero.
    assert 0 < punteggio <= 100


def test_punteggio_zero_senza_alcun_componente_utile() -> None:
    punteggio = attractiveness_score(
        catalyst=_catalizzatore(giorni=3650),  # ben oltre la finestra
        criteria=_criteri(),
        market_cap=None,
        cash_runway_months=None,
        phases=[],
        today=OGGI,
    )
    assert punteggio == 0.0


# --- Universo -------------------------------------------------------------------------

ATOM = """<?xml version="1.0" encoding="ISO-8859-1"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><content><company-info><cik>0001716947</cik><sic>2836</sic></company-info></content></entry>
  <entry><content><company-info><cik>0000320193</cik><sic>2836</sic></company-info></content></entry>
  <entry><content><company-info><cik>0009999999</cik><sic>2836</sic></company-info></content></entry>
</feed>"""

TICKERS_EXCHANGE = {
    "fields": ["cik", "name", "ticker", "exchange"],
    "data": [
        [1716947, "Ensysce Biosciences, Inc.", "ENSC", "NASDAQ"],
        [320193, "Apple Inc.", "AAPL", "Nasdaq"],
        [9999999, "Non Quotata SpA", "XXXX", "OTC"],
    ],
}


@respx.mock
def test_universo_estrae_i_cik_e_filtra_le_borse() -> None:
    """L'anagrafica SEC include società non quotate: vanno escluse."""
    respx.get(BROWSE_EDGAR_URL).mock(return_value=httpx.Response(200, text=ATOM))
    respx.get(TICKERS_EXCHANGE_URL).mock(return_value=httpx.Response(200, json=TICKERS_EXCHANGE))

    universo = UniverseProvider(user_agent="test t@example.com", max_retries=1).get_universe(
        ("2836",)
    )

    assert universo == {"ENSC": "Ensysce Biosciences, Inc.", "AAPL": "Apple Inc."}
    assert "XXXX" not in universo  # quotata OTC, esclusa


@respx.mock
def test_universo_gestisce_un_feed_vuoto() -> None:
    respx.get(BROWSE_EDGAR_URL).mock(
        return_value=httpx.Response(
            200, text='<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"/>'
        )
    )
    respx.get(TICKERS_EXCHANGE_URL).mock(return_value=httpx.Response(200, json=TICKERS_EXCHANGE))

    assert UniverseProvider(user_agent="t t@e.it", max_retries=1).get_universe(("2836",)) == {}


@respx.mock
def test_universo_rifiuta_un_feed_non_xml() -> None:
    from biocatalyst.data.base import DataParseError

    respx.get(BROWSE_EDGAR_URL).mock(return_value=httpx.Response(200, text="non xml"))
    provider = UniverseProvider(user_agent="t t@e.it", max_retries=1)

    with pytest.raises(DataParseError, match="non interpretabile"):
        provider.get_universe(("2836",))


@respx.mock
def test_universo_rifiuta_una_struttura_inattesa() -> None:
    from biocatalyst.data.base import DataParseError

    respx.get(BROWSE_EDGAR_URL).mock(return_value=httpx.Response(200, text=ATOM))
    respx.get(TICKERS_EXCHANGE_URL).mock(
        return_value=httpx.Response(200, json={"fields": ["altro"], "data": []})
    )
    provider = UniverseProvider(user_agent="t t@e.it", max_retries=1)

    with pytest.raises(DataParseError, match="struttura inattesa"):
        provider.get_universe(("2836",))


# --- Orchestrazione ---------------------------------------------------------------------


def _providers_finti(mercato: dict[str, MarketData], trials: dict[str, list[ClinicalTrial]]) -> Any:
    providers = MagicMock()
    providers.market.get_market_data.side_effect = lambda t: mercato[t]
    providers.clinical_trials.get_trials_by_sponsor.side_effect = lambda s: trials.get(
        s.split()[0], []
    )
    providers.sec.get_quarterly_financials.return_value = []
    return providers


def _trial(nct: str, giorni: int = 90, fasi: list[str] | None = None) -> ClinicalTrial:
    from datetime import timedelta

    return ClinicalTrial(
        nct_id=nct,
        brief_title=f"Studio {nct}",
        phase=fasi if fasi is not None else ["PHASE3"],
        overall_status="RECRUITING",
        primary_completion_date=date.today() + timedelta(days=giorni),
        primary_completion_date_type="ESTIMATED",
        condition=["Oncologia"],
    )


def _screen(monkeypatch: pytest.MonkeyPatch, mercato: Any, trials: Any, **kwargs: Any) -> Any:
    monkeypatch.setattr(
        "biocatalyst.screening.UniverseProvider",
        lambda **kw: MagicMock(get_universe=lambda sic: {"AAA": "Alpha Bio", "BBB": "Beta Bio"}),
    )
    monkeypatch.setattr("biocatalyst.screening._aggiungi_motivazioni", lambda *a, **k: None)
    settings = MagicMock()
    settings.sec_edgar_user_agent = "t t@e.it"
    settings.http_request_timeout_seconds = 30
    settings.cache_ttl_filing_seconds = 86400
    settings.report_language = "it"
    return screen(providers=_providers_finti(mercato, trials), settings=settings, **kwargs)


def test_screen_scarta_chi_non_supera_prezzo_o_dimensione(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mercato = {
        "AAA": MarketData(price=5.0, market_cap_usd=100_000_000),
        "BBB": MarketData(price=99.0, market_cap_usd=100_000_000),  # troppo caro
    }
    risultato = _screen(monkeypatch, mercato, {"Alpha": [_trial("NCT1")], "Beta": [_trial("NCT2")]})

    assert [c.ticker for c in risultato.candidates] == ["AAA"]


def test_screen_scarta_chi_non_ha_catalizzatori(monkeypatch: pytest.MonkeyPatch) -> None:
    mercato = {
        "AAA": MarketData(price=5.0, market_cap_usd=100_000_000),
        "BBB": MarketData(price=5.0, market_cap_usd=100_000_000),
    }
    risultato = _screen(monkeypatch, mercato, {"Alpha": [_trial("NCT1")]})

    assert [c.ticker for c in risultato.candidates] == ["AAA"]


def test_screen_scarta_le_fasi_troppo_precoci(monkeypatch: pytest.MonkeyPatch) -> None:
    mercato = {
        "AAA": MarketData(price=5.0, market_cap_usd=100_000_000),
        "BBB": MarketData(price=5.0, market_cap_usd=100_000_000),
    }
    trials = {
        "Alpha": [_trial("NCT1", fasi=["PHASE3"])],
        "Beta": [_trial("NCT2", fasi=["PHASE1"])],
    }
    risultato = _screen(
        monkeypatch, mercato, trials, criteria=_criteri(min_pipeline_phase="PHASE2")
    )

    assert [c.ticker for c in risultato.candidates] == ["AAA"]


def test_screen_ordina_per_attrattivita(monkeypatch: pytest.MonkeyPatch) -> None:
    mercato = {
        "AAA": MarketData(price=5.0, market_cap_usd=400_000_000),
        "BBB": MarketData(price=5.0, market_cap_usd=20_000_000),  # più piccola
    }
    trials = {"Alpha": [_trial("NCT1", giorni=150)], "Beta": [_trial("NCT2", giorni=20)]}
    risultato = _screen(monkeypatch, mercato, trials)

    # BBB ha catalizzatore più vicino e capitalizzazione minore.
    assert [c.ticker for c in risultato.candidates] == ["BBB", "AAA"]
    assert (
        risultato.candidates[0].attractiveness_score > risultato.candidates[1].attractiveness_score
    )


def test_screen_rispetta_il_limite_di_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    mercato = {
        "AAA": MarketData(price=5.0, market_cap_usd=100_000_000),
        "BBB": MarketData(price=5.0, market_cap_usd=100_000_000),
    }
    trials = {"Alpha": [_trial("NCT1")], "Beta": [_trial("NCT2")]}
    risultato = _screen(monkeypatch, mercato, trials, max_candidates=1)

    assert len(risultato.candidates) == 1


def test_screen_prosegue_se_un_titolo_fallisce(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un titolo che non risponde non deve interrompere la ricerca sugli altri."""
    from biocatalyst.data.base import DataUnavailableError

    def mercato_per(ticker: str) -> MarketData:
        if ticker == "BBB":
            raise DataUnavailableError("Yahoo non risponde")
        return MarketData(price=5.0, market_cap_usd=100_000_000)

    providers = MagicMock()
    providers.market.get_market_data.side_effect = mercato_per
    providers.clinical_trials.get_trials_by_sponsor.return_value = [_trial("NCT1")]
    providers.sec.get_quarterly_financials.return_value = []

    monkeypatch.setattr(
        "biocatalyst.screening.UniverseProvider",
        lambda **kw: MagicMock(get_universe=lambda sic: {"AAA": "Alpha", "BBB": "Beta"}),
    )
    monkeypatch.setattr("biocatalyst.screening._aggiungi_motivazioni", lambda *a, **k: None)
    settings = MagicMock()
    settings.report_language = "it"

    risultato = screen(providers=providers, settings=settings)

    assert [c.ticker for c in risultato.candidates] == ["AAA"]


def test_screen_marca_le_candidate_eccezionali(monkeypatch: pytest.MonkeyPatch) -> None:
    mercato = {
        "AAA": MarketData(price=12.0, market_cap_usd=100_000_000),  # oltre i $10
        "BBB": MarketData(price=5.0, market_cap_usd=100_000_000),
    }
    trials = {"Alpha": [_trial("NCT1")], "Beta": [_trial("NCT2")]}
    risultato = _screen(monkeypatch, mercato, trials)

    per_ticker = {c.ticker: c for c in risultato.candidates}
    assert per_ticker["AAA"].exceptional is True
    assert per_ticker["BBB"].exceptional is False


# --- Profili di rischio: le gemme scontate non devono sparire ---------------------


def test_il_profilo_speculativo_non_penalizza_la_cassa_scarsa() -> None:
    """Diluire non è fallire: un titolo scontato deve restare visibile."""
    from biocatalyst.analysis.screening import BALANCED, PRUDENT, SPECULATIVE

    comune: dict[str, Any] = {
        "catalyst": _catalizzatore(giorni=150),
        "criteria": _criteri(),
        "market_cap": 20_000_000,
        "phases": ["PHASE3"],
        "today": OGGI,
    }
    scarsa = 1.0
    capiente = 24.0

    # Nel profilo speculativo il punteggio non dipende dalla cassa.
    assert attractiveness_score(
        cash_runway_months=scarsa, appetite=SPECULATIVE, **comune
    ) == pytest.approx(
        attractiveness_score(cash_runway_months=capiente, appetite=SPECULATIVE, **comune)
    )

    # Nel prudente il divario è marcato, nel bilanciato contenuto.
    divario_prudente = attractiveness_score(
        cash_runway_months=capiente, appetite=PRUDENT, **comune
    ) - attractiveness_score(cash_runway_months=scarsa, appetite=PRUDENT, **comune)
    divario_bilanciato = attractiveness_score(
        cash_runway_months=capiente, appetite=BALANCED, **comune
    ) - attractiveness_score(cash_runway_months=scarsa, appetite=BALANCED, **comune)
    assert divario_prudente > divario_bilanciato > 0


def test_avviso_finanziario_quando_la_cassa_non_arriva_al_catalizzatore() -> None:
    from biocatalyst.analysis.screening import financing_risk_note

    avviso = financing_risk_note(2.0, _catalizzatore(giorni=180), OGGI)

    assert avviso is not None
    assert "2.0 months" in avviso
    # Distingue i due rischi: diluizione e interruzione dello studio.
    assert "dilute" in avviso
    assert "halted" in avviso


def test_nessun_avviso_se_la_cassa_basta() -> None:
    from biocatalyst.analysis.screening import financing_risk_note

    assert financing_risk_note(24.0, _catalizzatore(giorni=180), OGGI) is None


def test_nessun_avviso_senza_dati_sufficienti() -> None:
    from biocatalyst.analysis.screening import financing_risk_note

    assert financing_risk_note(None, _catalizzatore(), OGGI) is None
    catalizzatore_senza_data = Catalyst(
        name="x",
        catalyst_type="clinical_readout",
        expected_date_window="Q1 2027",
        source="s",
        imminence_rank=1,
    )
    assert financing_risk_note(2.0, catalizzatore_senza_data, OGGI) is None


def test_la_candidata_a_corto_di_cassa_resta_nel_risultato(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Il punto della correzione: segnalare il rischio, non escludere il titolo."""
    mercato = {
        "AAA": MarketData(price=0.4, market_cap_usd=8_000_000),
        "BBB": MarketData(price=5.0, market_cap_usd=100_000_000),
    }
    trials = {"Alpha": [_trial("NCT1", giorni=150)], "Beta": [_trial("NCT2", giorni=150)]}

    providers = _providers_finti(mercato, trials)
    # Alpha ha pochissima cassa, Beta molta.
    providers.sec.get_quarterly_financials.side_effect = lambda t: []
    monkeypatch.setattr(
        "biocatalyst.screening._runway", lambda ticker, p: 1.0 if ticker == "AAA" else 24.0
    )
    monkeypatch.setattr(
        "biocatalyst.screening.UniverseProvider",
        lambda **kw: MagicMock(get_universe=lambda sic: {"AAA": "Alpha Bio", "BBB": "Beta Bio"}),
    )
    monkeypatch.setattr("biocatalyst.screening._aggiungi_motivazioni", lambda *a, **k: None)
    settings = MagicMock()
    settings.report_language = "it"

    risultato = screen(providers=providers, settings=settings)

    per_ticker = {c.ticker: c for c in risultato.candidates}
    assert "AAA" in per_ticker  # non scartata
    assert per_ticker["AAA"].financing_risk is not None
    assert per_ticker["BBB"].financing_risk is None


def test_punteggio_zero_se_tutti_i_pesi_sono_nulli() -> None:
    """Guardia difensiva: un profilo con tutti i pesi a zero non deve dividere per zero."""
    from biocatalyst.analysis.screening import RiskAppetite

    nullo = RiskAppetite("nullo", imminence=0.0, runway_coverage=0.0, size=0.0, phase=0.0)

    punteggio = attractiveness_score(
        catalyst=_catalizzatore(giorni=30),
        criteria=_criteri(),
        market_cap=20_000_000,
        cash_runway_months=24.0,
        phases=["PHASE3"],
        today=OGGI,
        appetite=nullo,
    )

    assert punteggio == 0.0


# --- Nomi dei profili di rischio --------------------------------------------


def test_i_profili_hanno_nomi_inglesi_stabili() -> None:
    """Sono i valori accettati da `--risk`: cambiarli romperebbe i comandi salvati.

    Prima erano in italiano e comparivano così anche nell'interfaccia inglese,
    nel menù di screening.
    """
    assert set(RISK_APPETITES) == {"speculative", "balanced", "prudent"}


@pytest.mark.parametrize(
    ("name", "language", "atteso"),
    [
        ("speculative", "en", "speculative"),
        ("speculative", "it", "speculativo"),
        ("balanced", "it", "bilanciato"),
        ("prudent", "it", "prudente"),
    ],
)
def test_l_etichetta_del_profilo_segue_la_lingua(name: str, language: str, atteso: str) -> None:
    assert risk_appetite_label(name, language) == atteso


def test_un_profilo_sconosciuto_si_mostra_com_e() -> None:
    """Meglio un nome grezzo che un errore in mezzo a uno screen già pagato."""
    assert risk_appetite_label("inventato", "en") == "inventato"


def test_ogni_profilo_ha_l_etichetta_in_entrambe_le_lingue() -> None:
    for nome in RISK_APPETITES:
        assert set(RISK_APPETITE_LABELS[nome]) == {"en", "it"}, nome
