from __future__ import annotations

import time
from datetime import date
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from pydantic import SecretStr

from biocatalyst.data import (
    ClinicalTrialsProvider,
    DataAuthError,
    DataCache,
    DataNotFoundError,
    DataProviderError,
    DataRateLimitError,
    DataUnavailableError,
    FDAProvider,
    ForexProvider,
    HTTPDataProvider,
    MarketDataProvider,
    NewsProvider,
    RateLimiter,
    SECProvider,
    collect_safely,
    parse_flexible_date,
)
from biocatalyst.data import sec as sec_module

USER_AGENT = "BioCatalystAnalyzer test@example.com"


@pytest.fixture(autouse=True)
def _no_rate_limiting(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Azzera le attese: i limitatori reali (fino a 1 req/s) renderebbero i test lenti.

    Il test che verifica il limitatore stesso si esclude con l'apposito marker,
    altrimenti misurerebbe una funzione svuotata.
    """
    if "rate_limiter_reale" in request.keywords:
        return
    monkeypatch.setattr(RateLimiter, "wait", lambda self: None)


@pytest.fixture
def cache(tmp_path: Path) -> DataCache:
    return DataCache(tmp_path / "cache")


# --- Date in formati eterogenei ----------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2030-05-31", date(2030, 5, 31)),  # ISO completo (ClinicalTrials.gov)
        ("2027-04", date(2027, 4, 1)),  # parziale anno-mese: normalizzata al giorno 1
        ("20160523", date(2016, 5, 23)),  # formato compatto (openFDA)
        (None, None),
        ("", None),
        ("non-una-data", None),
    ],
)
def test_parse_flexible_date(value: str | None, expected: date | None) -> None:
    assert parse_flexible_date(value) == expected


# --- Rate limiter -------------------------------------------------------------


@pytest.mark.rate_limiter_reale
def test_rate_limiter_rispetta_intervallo_minimo() -> None:
    limiter = RateLimiter(0.05)
    start = time.monotonic()
    limiter.wait()
    limiter.wait()
    limiter.wait()
    elapsed = time.monotonic() - start
    # La prima chiamata non attende; le due successive sì.
    assert elapsed >= 0.09


# --- collect_safely: il report si genera comunque -----------------------------


def test_collect_safely_restituisce_il_valore_se_va_a_buon_fine() -> None:
    missing: list[str] = []
    result = collect_safely("prezzi", lambda: 42, missing)
    assert result == 42
    assert missing == []


def test_collect_safely_annota_il_buco_invece_di_propagare() -> None:
    missing: list[str] = []

    def fallisce() -> int:
        raise DataUnavailableError("fonte irraggiungibile")

    result = collect_safely("short interest", fallisce, missing)

    assert result is None
    assert len(missing) == 1
    assert "short interest" in missing[0]
    assert "fonte irraggiungibile" in missing[0]


def test_collect_safely_non_maschera_errori_di_programmazione() -> None:
    def bug() -> int:
        raise ValueError("bug nel codice")

    with pytest.raises(ValueError):
        collect_safely("x", bug, [])


# --- Cache --------------------------------------------------------------------


def test_cache_serve_il_valore_memorizzato_senza_richiamare_la_fonte(cache: DataCache) -> None:
    chiamate = 0

    def fetch() -> str:
        nonlocal chiamate
        chiamate += 1
        return "dato"

    assert cache.get_or_fetch("k", 60, fetch) == "dato"
    assert cache.get_or_fetch("k", 60, fetch) == "dato"
    assert chiamate == 1
    cache.close()


def test_cache_scade_secondo_il_ttl(cache: DataCache) -> None:
    chiamate = 0

    def fetch() -> str:
        nonlocal chiamate
        chiamate += 1
        return f"dato{chiamate}"

    cache.get_or_fetch("k", 1, fetch)
    time.sleep(1.1)
    assert cache.get_or_fetch("k", 1, fetch) == "dato2"
    cache.close()


def test_cache_non_memorizza_i_fallimenti(cache: DataCache) -> None:
    """Un errore transitorio non deve restare congelato per tutto il TTL."""

    def fallisce() -> str:
        raise DataUnavailableError("giù")

    with pytest.raises(DataUnavailableError):
        cache.get_or_fetch("k", 3600, fallisce)

    assert cache.get_or_fetch("k", 3600, lambda: "poi funziona") == "poi funziona"
    cache.close()


def test_cache_disattivata_chiama_sempre_la_fonte(tmp_path: Path) -> None:
    disabled = DataCache(tmp_path / "c", enabled=False)
    chiamate = 0

    def fetch() -> int:
        nonlocal chiamate
        chiamate += 1
        return chiamate

    disabled.get_or_fetch("k", 60, fetch)
    disabled.get_or_fetch("k", 60, fetch)
    assert chiamate == 2


# --- Traduzione degli errori HTTP --------------------------------------------


class _Probe(HTTPDataProvider):
    pass


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (404, DataNotFoundError),
        (401, DataAuthError),
        (403, DataAuthError),
        (429, DataRateLimitError),
        (500, DataUnavailableError),
        (503, DataUnavailableError),
        (400, DataProviderError),
    ],
)
@respx.mock
def test_errori_http_tradotti_nella_gerarchia(
    status: int, expected: type[DataProviderError]
) -> None:
    respx.get("https://example.invalid/x").mock(return_value=httpx.Response(status))
    provider = _Probe(max_retries=1)
    with pytest.raises(expected):
        provider._get_json("https://example.invalid/x")


@respx.mock
def test_timeout_diventa_errore_ritentabile() -> None:
    respx.get("https://example.invalid/x").mock(side_effect=httpx.ReadTimeout("lento"))
    provider = _Probe(max_retries=1)
    with pytest.raises(DataUnavailableError, match="timeout"):
        provider._get_json("https://example.invalid/x")


@respx.mock
def test_ritenta_gli_errori_transitori_e_poi_riesce() -> None:
    route = respx.get("https://example.invalid/x").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )
    provider = _Probe(max_retries=3)
    provider.retry_initial_wait = 0.0
    provider.retry_max_wait = 0.0

    assert provider._get_json("https://example.invalid/x") == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_non_ritenta_gli_errori_definitivi() -> None:
    route = respx.get("https://example.invalid/x").mock(return_value=httpx.Response(404))
    provider = _Probe(max_retries=3)
    provider.retry_initial_wait = 0.0

    with pytest.raises(DataNotFoundError):
        provider._get_json("https://example.invalid/x")
    # Un 404 non cambia esito ritentando: una sola chiamata.
    assert route.call_count == 1


# --- SEC EDGAR ----------------------------------------------------------------

TICKER_MAP = {
    "0": {"cik_str": 1716947, "ticker": "ENSC", "title": "Ensysce Biosciences, Inc."},
    "1": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
}


def _sec_provider() -> SECProvider:
    provider = SECProvider(user_agent=USER_AGENT, max_retries=1)
    provider.retry_initial_wait = 0.0
    return provider


@respx.mock
def test_sec_cik_viene_riempito_a_dieci_cifre() -> None:
    respx.get(sec_module.TICKER_MAP_URL).mock(return_value=httpx.Response(200, json=TICKER_MAP))
    # Un CIK non zero-paddato produce 404 sugli endpoint di data.sec.gov.
    assert _sec_provider().get_cik("ENSC") == "0001716947"
    assert _sec_provider().get_cik("aapl") == "0000320193"


@respx.mock
def test_sec_ticker_sconosciuto_solleva_not_found() -> None:
    respx.get(sec_module.TICKER_MAP_URL).mock(return_value=httpx.Response(200, json=TICKER_MAP))
    with pytest.raises(DataNotFoundError, match="ZZZZ"):
        _sec_provider().get_cik("ZZZZ")


@respx.mock
def test_sec_invia_lo_user_agent_richiesto() -> None:
    route = respx.get(sec_module.TICKER_MAP_URL).mock(
        return_value=httpx.Response(200, json=TICKER_MAP)
    )
    _sec_provider().get_cik("ENSC")
    # Senza User-Agent identificativo la SEC risponde 403.
    assert route.calls[0].request.headers["User-Agent"] == USER_AGENT


def _usd(entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {"units": {"USD": entries}}


def _facts_payload(concepts: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    return {"facts": {"us-gaap": {name: _usd(rows) for name, rows in concepts.items()}}}


def _mock_facts(payload: dict[str, Any]) -> None:
    respx.get(sec_module.TICKER_MAP_URL).mock(return_value=httpx.Response(200, json=TICKER_MAP))
    respx.get(sec_module.COMPANY_FACTS_URL.format(cik="0001716947")).mock(
        return_value=httpx.Response(200, json=payload)
    )


@respx.mock
def test_sec_scarta_i_cumulati_year_to_date() -> None:
    """Per un dato `fp` coesistono trimestre e cumulato: va tenuto solo il trimestre."""
    _mock_facts(
        _facts_payload(
            {
                "ResearchAndDevelopmentExpense": [
                    # Cumulato di 6 mesi: da ignorare.
                    {
                        "start": "2026-01-01",
                        "end": "2026-06-30",
                        "val": 5_818_633,
                        "fy": 2026,
                        "fp": "Q2",
                        "form": "10-Q",
                        "filed": "2026-08-13",
                    },
                    # Trimestre vero: da tenere.
                    {
                        "start": "2026-04-01",
                        "end": "2026-06-30",
                        "val": 2_471_752,
                        "fy": 2026,
                        "fp": "Q2",
                        "form": "10-Q",
                        "filed": "2026-08-13",
                    },
                ]
            }
        )
    )

    results = _sec_provider().get_quarterly_financials("ENSC")

    assert len(results) == 1
    assert results[0].rd_expense_usd == 2_471_752


@respx.mock
def test_sec_riconosce_i_fatti_puntuali_senza_start() -> None:
    """La cassa è un dato puntuale: ha solo `end`, e assumere `start` romperebbe."""
    _mock_facts(
        _facts_payload(
            {
                "CashAndCashEquivalentsAtCarryingValue": [
                    {
                        "end": "2026-06-30",
                        "val": 676_704,
                        "fy": 2026,
                        "fp": "Q2",
                        "form": "10-Q",
                        "filed": "2026-08-13",
                    }
                ]
            }
        )
    )

    results = _sec_provider().get_quarterly_financials("ENSC")

    assert results[0].cash_and_equivalents_usd == 676_704
    assert results[0].period_end == date(2026, 6, 30)


@respx.mock
def test_sec_deriva_il_q4_sottraendo_i_primi_tre_trimestri() -> None:
    """XBRL non marca mai il Q4: va ricostruito da FY meno i primi tre trimestri."""

    def quarter(fp: str, start: str, end: str, val: int) -> dict[str, Any]:
        return {
            "start": start,
            "end": end,
            "val": val,
            "fy": 2025,
            "fp": fp,
            "form": "10-Q",
            "filed": f"{end[:4]}-11-01",
        }

    _mock_facts(
        _facts_payload(
            {
                "NetIncomeLoss": [
                    quarter("Q1", "2025-01-01", "2025-03-31", -1_945_573),
                    quarter("Q2", "2025-04-01", "2025-06-30", -1_733_517),
                    quarter("Q3", "2025-07-01", "2025-09-30", -3_729_128),
                    {
                        "start": "2025-01-01",
                        "end": "2025-12-31",
                        "val": -10_176_187,
                        "fy": 2025,
                        "fp": "FY",
                        "form": "10-K",
                        "filed": "2026-03-15",
                    },
                ]
            }
        )
    )

    results = {r.fiscal_period: r for r in _sec_provider().get_quarterly_financials("ENSC")}

    assert "Q4" in results
    assert results["Q4"].net_income_loss_usd == pytest.approx(-2_767_969)
    assert results["Q4"].form_type == "10-K"


@respx.mock
def test_sec_non_deriva_il_q4_se_manca_un_trimestre() -> None:
    """Con un trimestre mancante la sottrazione darebbe un numero sbagliato in silenzio."""
    _mock_facts(
        _facts_payload(
            {
                "NetIncomeLoss": [
                    {
                        "start": "2025-01-01",
                        "end": "2025-03-31",
                        "val": -1_000_000,
                        "fy": 2025,
                        "fp": "Q1",
                        "form": "10-Q",
                        "filed": "2025-05-01",
                    },
                    {
                        "start": "2025-01-01",
                        "end": "2025-12-31",
                        "val": -10_000_000,
                        "fy": 2025,
                        "fp": "FY",
                        "form": "10-K",
                        "filed": "2026-03-15",
                    },
                ]
            }
        )
    )

    periods = {r.fiscal_period for r in _sec_provider().get_quarterly_financials("ENSC")}

    assert "Q4" not in periods


@respx.mock
def test_sec_preferisce_il_filing_rettificato_piu_recente() -> None:
    """Un 10-K/A riemette lo stesso periodo: vince il deposito più recente."""
    _mock_facts(
        _facts_payload(
            {
                "NetIncomeLoss": [
                    {
                        "start": "2025-01-01",
                        "end": "2025-03-31",
                        "val": 2_404_519,
                        "fy": 2025,
                        "fp": "Q1",
                        "form": "10-Q",
                        "filed": "2025-05-01",
                    },
                    {
                        "start": "2025-01-01",
                        "end": "2025-03-31",
                        "val": 4_310_769,
                        "fy": 2025,
                        "fp": "Q1",
                        "form": "10-Q/A",
                        "filed": "2025-09-30",
                    },
                ]
            }
        )
    )

    results = _sec_provider().get_quarterly_financials("ENSC")

    assert results[0].net_income_loss_usd == 4_310_769
    # Una rettifica di un 10-Q resta un 10-Q, non diventa un 10-K.
    assert results[0].form_type == "10-Q"


@respx.mock
def test_sec_usa_profitloss_quando_manca_netincomeloss() -> None:
    """Alcuni filer cambiano tag negli anni: la catena di concetti copre entrambi."""
    _mock_facts(
        _facts_payload(
            {
                "NetIncomeLoss": [
                    {
                        "start": "2021-01-01",
                        "end": "2021-03-31",
                        "val": -1_711_607,
                        "fy": 2021,
                        "fp": "Q1",
                        "form": "10-Q",
                        "filed": "2021-05-15",
                    }
                ],
                "ProfitLoss": [
                    {
                        "start": "2026-01-01",
                        "end": "2026-03-31",
                        "val": -3_556_415,
                        "fy": 2026,
                        "fp": "Q1",
                        "form": "10-Q",
                        "filed": "2026-05-15",
                    }
                ],
            }
        )
    )

    results = {
        (r.fiscal_year, r.fiscal_period): r
        for r in _sec_provider().get_quarterly_financials("ENSC")
    }

    assert results[(2021, "Q1")].net_income_loss_usd == -1_711_607
    assert results[(2026, "Q1")].net_income_loss_usd == -3_556_415


@respx.mock
def test_sec_ricerca_full_text_richiede_il_cik() -> None:
    """Con il solo parametro `q` l'endpoint EDGAR risponde 500: serve `ciks`."""
    respx.get(sec_module.TICKER_MAP_URL).mock(return_value=httpx.Response(200, json=TICKER_MAP))
    route = respx.get(sec_module.FULL_TEXT_SEARCH_URL).mock(
        return_value=httpx.Response(
            200, json={"hits": {"hits": [{"_source": {"adsh": "0001493152-26-037817"}}]}}
        )
    )

    signals = _sec_provider().get_filing_signals("ENSC")

    assert signals.atm_offering_mentioned is True
    assert "0001493152-26-037817" in signals.matching_accession_numbers
    assert route.calls[0].request.url.params["ciks"] == "0001716947"


# --- ClinicalTrials.gov -------------------------------------------------------


def _study(nct: str, sponsor: str, completion: str | None = "2027-04") -> dict[str, Any]:
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct, "briefTitle": f"Studio {nct}"},
            "statusModule": {
                "overallStatus": "RECRUITING",
                "primaryCompletionDateStruct": {"date": completion, "type": "ESTIMATED"},
            },
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": sponsor}},
            "designModule": {
                "phases": ["PHASE2"],
                "enrollmentInfo": {"count": 54, "type": "ESTIMATED"},
            },
            "outcomesModule": {
                "primaryOutcomes": [{"measure": "Sopravvivenza libera da progressione"}]
            },
            "conditionsModule": {"conditions": ["NSCLC"]},
        }
    }


@respx.mock
def test_ctgov_esclude_gli_studi_dove_e_solo_collaboratore() -> None:
    """query.spons trova anche gli studi altrui: vanno filtrati lato client."""
    respx.get("https://clinicaltrials.gov/api/v2/studies").mock(
        return_value=httpx.Response(
            200,
            json={
                "studies": [
                    _study("NCT001", "Ensysce Biosciences"),
                    _study("NCT002", "Alliance Foundation Trials, LLC."),
                ]
            },
        )
    )

    trials = ClinicalTrialsProvider(max_retries=1).get_trials_by_sponsor("Ensysce")

    assert [t.nct_id for t in trials] == ["NCT001"]


@respx.mock
def test_ctgov_interpreta_le_date_parziali() -> None:
    respx.get("https://clinicaltrials.gov/api/v2/studies").mock(
        return_value=httpx.Response(200, json={"studies": [_study("NCT001", "Ensysce", "2027-04")]})
    )

    trials = ClinicalTrialsProvider(max_retries=1).get_trials_by_sponsor("Ensysce")

    assert trials[0].primary_completion_date == date(2027, 4, 1)
    assert trials[0].primary_completion_date_type == "ESTIMATED"


@respx.mock
def test_ctgov_salta_gli_studi_senza_identificativo() -> None:
    respx.get("https://clinicaltrials.gov/api/v2/studies").mock(
        return_value=httpx.Response(200, json={"studies": [{"protocolSection": {}}]})
    )

    assert ClinicalTrialsProvider(max_retries=1).get_trials_by_sponsor("X") == []


# --- openFDA ------------------------------------------------------------------


@respx.mock
def test_openfda_nessun_risultato_non_e_un_errore() -> None:
    """Per una biotech senza farmaci approvati openFDA risponde 404: è normale."""
    respx.get("https://api.fda.gov/drug/drugsfda.json").mock(return_value=httpx.Response(404))

    assert FDAProvider(max_retries=1).get_approvals_by_sponsor("Ensysce Biosciences") == []


@respx.mock
def test_openfda_estrae_la_data_di_approvazione() -> None:
    respx.get("https://api.fda.gov/drug/drugsfda.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "application_number": "NDA050784",
                        "sponsor_name": "PFIZER",
                        "submissions": [
                            {"submission_status": "TA", "submission_status_date": "20100101"},
                            {
                                "submission_type": "SUPPL",
                                "submission_status": "AP",
                                "submission_status_date": "20160523",
                            },
                        ],
                        "products": [
                            {"brand_name": "ZITHROMAX", "marketing_status": "Prescription"}
                        ],
                    }
                ]
            },
        )
    )

    approvals = FDAProvider(max_retries=1).get_approvals_by_sponsor("PFIZER")

    assert len(approvals) == 1
    # Le date openFDA sono compatte ("20160523"), non ISO con trattini.
    assert approvals[0].approval_date == date(2016, 5, 23)
    assert approvals[0].product_name == "ZITHROMAX"


# --- Finnhub ------------------------------------------------------------------


def test_finnhub_senza_chiave_da_errore_esplicito() -> None:
    with pytest.raises(DataAuthError, match="FINNHUB_API_KEY"):
        NewsProvider(api_key=None).get_company_news("ENSC")


@respx.mock
def test_finnhub_non_mette_il_token_nella_chiave_di_cache(cache: DataCache) -> None:
    respx.get("https://finnhub.io/api/v1/company-news").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "headline": "Titolo",
                    "url": "https://example.com/a",
                    "datetime": 1787000000,
                    "source": "Reuters",
                }
            ],
        )
    )
    provider = NewsProvider(api_key=SecretStr("token-segreto"), cache=cache, max_retries=1)

    news = provider.get_company_news("ENSC")

    assert len(news) == 1
    assert news[0].source == "Reuters"
    chiavi = list(cache._cache) if cache._cache is not None else []
    assert all("token-segreto" not in str(k) for k in chiavi)
    cache.close()


@respx.mock
def test_finnhub_scarta_le_voci_incomplete() -> None:
    respx.get("https://finnhub.io/api/v1/company-news").mock(
        return_value=httpx.Response(
            200,
            json=[
                {"headline": "Senza url", "datetime": 1787000000},
                {"headline": "Buona", "url": "https://x.it/a", "datetime": 1787000000},
            ],
        )
    )

    news = NewsProvider(api_key=SecretStr("t"), max_retries=1).get_company_news("ENSC")

    assert [n.headline for n in news] == ["Buona"]


# --- Frankfurter --------------------------------------------------------------


@respx.mock
def test_forex_usa_la_data_restituita_non_quella_richiesta() -> None:
    """Nei weekend la BCE non pubblica: l'API risponde con l'ultimo giorno utile."""
    respx.get("https://api.frankfurter.dev/v1/2026-08-23").mock(
        return_value=httpx.Response(
            200, json={"amount": 1.0, "base": "EUR", "date": "2026-08-21", "rates": {"USD": 1.1664}}
        )
    )

    result = ForexProvider(max_retries=1).get_eur_usd(date(2026, 8, 23))

    assert result.rate == 1.1664
    assert result.rate_date == date(2026, 8, 21)


@respx.mock
def test_forex_risposta_senza_tasso_solleva_errore() -> None:
    respx.get("https://api.frankfurter.dev/v1/latest").mock(
        return_value=httpx.Response(200, json={"base": "EUR", "rates": {}})
    )

    with pytest.raises(DataProviderError):
        ForexProvider(max_retries=1).get_eur_usd()


# --- yfinance -----------------------------------------------------------------


class _FakeTicker:
    def __init__(self, info: dict[str, Any]) -> None:
        self._info = info

    @property
    def info(self) -> dict[str, Any]:
        return self._info

    def history(self, period: str) -> Any:  # noqa: ARG002
        import pandas as pd

        return pd.DataFrame(
            {"Close": [1.0, 2.0]},
            index=pd.to_datetime(["2026-08-24", "2026-08-25"]),
        )


def _patch_yfinance(monkeypatch: pytest.MonkeyPatch, info: dict[str, Any]) -> None:
    from biocatalyst.data import market as market_module

    monkeypatch.setattr(market_module.yf, "Ticker", lambda symbol: _FakeTicker(info))


def test_market_converte_short_percent_da_frazione_a_percentuale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """yfinance restituisce 0.0125 per l'1,25%: trattarlo come percentuale sbaglierebbe di 100x."""
    _patch_yfinance(monkeypatch, {"currentPrice": 0.403, "shortPercentOfFloat": 0.0125})

    data = MarketDataProvider().get_market_data("ENSC")

    assert data.short_percent_of_float == pytest.approx(1.25)


def test_market_converte_la_data_short_interest_da_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_yfinance(monkeypatch, {"currentPrice": 1.0, "dateShortInterest": 1785456000})

    data = MarketDataProvider().get_market_data("ENSC")

    # Il dato FINRA è per costruzione vecchio di settimane: la data va sempre esposta.
    assert data.short_interest_date is not None


def test_market_tollera_i_campi_assenti_dei_microcap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Per i micro-cap i campi sullo short interest mancano spesso del tutto."""
    _patch_yfinance(monkeypatch, {"currentPrice": 0.4, "marketCap": 7_841_088})

    data = MarketDataProvider().get_market_data("ENSC")

    assert data.price == 0.4
    assert data.shares_short is None
    assert data.short_percent_of_float is None
    assert data.short_interest_date is None


def test_market_ignora_i_valori_non_numerici(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_yfinance(monkeypatch, {"currentPrice": 1.0, "marketCap": "non-un-numero"})

    assert MarketDataProvider().get_market_data("ENSC").market_cap_usd is None


def test_market_ripiega_su_regular_market_price(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_yfinance(monkeypatch, {"regularMarketPrice": 3.21})

    assert MarketDataProvider().get_market_data("ENSC").price == 3.21


def test_market_risposta_vuota_solleva_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_yfinance(monkeypatch, {})

    with pytest.raises(DataNotFoundError):
        MarketDataProvider().get_market_data("TICKERINESISTENTE")


# --- Sentiment di settore (XBI/IBB) -------------------------------------------


def test_sector_sentiment_calcola_la_variazione_percentuale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_yfinance(monkeypatch, {})

    sentiment = MarketDataProvider().get_sector_sentiment(period_days=30)

    # Il finto storico va da 1.0 a 2.0: +100%.
    assert [s.symbol for s in sentiment] == ["XBI", "IBB"]
    assert sentiment[0].price_change_pct == pytest.approx(100.0)
    assert sentiment[0].period_days == 30


def test_sector_sentiment_salta_gli_etf_non_disponibili(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un ETF che non risponde non deve far fallire l'intero contesto di mercato."""
    from biocatalyst.data import market as market_module

    def ticker_rotto(symbol: str) -> Any:
        if symbol == "XBI":
            raise RuntimeError("Yahoo non risponde")
        return _FakeTicker({})

    monkeypatch.setattr(market_module.yf, "Ticker", ticker_rotto)

    sentiment = MarketDataProvider().get_sector_sentiment()

    assert [s.symbol for s in sentiment] == ["IBB"]


# --- Factory dei provider ------------------------------------------------------


def test_build_data_providers_usa_i_ttl_della_configurazione(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from biocatalyst.config import Settings
    from biocatalyst.data import build_data_providers

    monkeypatch.setenv("SEC_EDGAR_USER_AGENT", USER_AGENT)
    monkeypatch.setenv("DEFAULT_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("CACHE_TTL_PRICE_SECONDS", "300")
    monkeypatch.setenv("CACHE_TTL_FILING_SECONDS", "7200")
    settings = Settings(_env_file=None)

    providers = build_data_providers(settings)

    assert providers.market.price_ttl_seconds == 300
    assert providers.sec.filing_ttl_seconds == 7200
    assert providers.sec.headers["User-Agent"] == USER_AGENT
    # Una sola cache condivisa da tutte le fonti.
    assert providers.forex.cache is providers.cache
    assert providers.news.cache is providers.cache
    providers.close()


@respx.mock
def test_finnhub_il_token_non_finisce_nei_messaggi_di_errore() -> None:
    """Il token viaggia come query param: un messaggio che citasse l'URL completo
    lo esporrebbe in log e traceback."""
    respx.get("https://finnhub.io/api/v1/company-news").mock(return_value=httpx.Response(500))
    provider = NewsProvider(api_key=SecretStr("token-segretissimo"), max_retries=1)
    provider.retry_initial_wait = 0.0

    with pytest.raises(DataProviderError) as exc_info:
        provider.get_company_news("ENSC")

    assert "token-segretissimo" not in str(exc_info.value)
