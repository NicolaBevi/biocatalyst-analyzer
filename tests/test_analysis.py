"""Test dell'analysis engine.

Il requisito chiede copertura totale su questa logica: sono i numeri su cui si
prendono decisioni di investimento, e un errore qui non verrebbe segnalato da
nessuna API.
"""

from __future__ import annotations

from datetime import date

import pytest

from biocatalyst.analysis import (
    ScenarioInput,
    build_expected_value_analysis,
    build_scenario_analysis,
    cash_runway_months,
    catalysts_from_trials,
    compute_financial_metrics,
    dilution_risk_score,
    expected_price,
    expected_roi_pct,
    float_scarcity_score,
    latest_cash,
    quarterly_burn_rate,
    runway_pressure_score,
    short_squeeze_score,
    sorted_by_period,
    target_change_pct,
)
from biocatalyst.analysis.catalysts import is_event_driven
from biocatalyst.models.raw_data import (
    ClinicalTrial,
    MarketData,
    QuarterlyFinancials,
    SECFilingSignals,
)


def _quarter(
    year: int,
    period: str,
    end: str,
    cash: float | None = None,
    net: float | None = None,
    rd: float | None = None,
    form: str = "10-Q",
    filed: str = "2026-01-01",
) -> QuarterlyFinancials:
    return QuarterlyFinancials(
        fiscal_year=year,
        fiscal_period=period,  # type: ignore[arg-type]
        period_end=date.fromisoformat(end),
        cash_and_equivalents_usd=cash,
        rd_expense_usd=rd,
        net_income_loss_usd=net,
        form_type=form,  # type: ignore[arg-type]
        filed_date=date.fromisoformat(filed),
    )


#: Serie reale di Ensysce Biosciences, usata come caso di riferimento.
ENSC_QUARTERS = [
    _quarter(2024, "Q3", "2024-09-30", cash=4_153_592, net=661_769),
    _quarter(2024, "Q4", "2024-12-31", cash=3_502_077, net=-3_564_422, form="10-K"),
    _quarter(2025, "Q1", "2025-03-31", cash=3_052_491, net=-1_945_573),
    _quarter(2025, "Q2", "2025-06-30", cash=2_211_575, net=-1_733_517),
    _quarter(2025, "Q3", "2025-09-30", cash=1_673_218, net=-3_729_128),
    _quarter(2025, "Q4", "2025-12-31", cash=4_310_354, net=-2_767_969, form="10-K"),
    _quarter(2026, "Q1", "2026-03-31", cash=745_482, net=-3_556_415),
    _quarter(2026, "Q2", "2026-06-30", cash=676_704, net=-2_570_875),
]


# --- Ordinamento e cassa più recente -----------------------------------------


def test_sorted_by_period_ordina_dal_piu_vecchio() -> None:
    shuffled = [ENSC_QUARTERS[3], ENSC_QUARTERS[0], ENSC_QUARTERS[7]]
    ordered = sorted_by_period(shuffled)
    assert [q.period_end for q in ordered] == [
        date(2024, 9, 30),
        date(2025, 6, 30),
        date(2026, 6, 30),
    ]


def test_latest_cash_restituisce_valore_e_trimestre() -> None:
    result = latest_cash(ENSC_QUARTERS)
    assert result == (676_704, date(2026, 6, 30))


def test_latest_cash_salta_i_trimestri_senza_cassa() -> None:
    quarters = [
        _quarter(2026, "Q1", "2026-03-31", cash=1_000_000),
        _quarter(2026, "Q2", "2026-06-30", cash=None),
    ]
    assert latest_cash(quarters) == (1_000_000, date(2026, 3, 31))


def test_latest_cash_senza_dati_restituisce_none() -> None:
    assert latest_cash([]) is None
    assert latest_cash([_quarter(2026, "Q1", "2026-03-31", cash=None)]) is None


# --- Burn rate ----------------------------------------------------------------


def test_burn_rate_media_gli_ultimi_quattro_trimestri() -> None:
    # Q3'25 + Q4'25 + Q1'26 + Q2'26 = -12.624.387 su 4 trimestri.
    burn = quarterly_burn_rate(ENSC_QUARTERS)
    assert burn == pytest.approx(3_156_096.75)


def test_burn_rate_rispetta_la_finestra_richiesta() -> None:
    burn = quarterly_burn_rate(ENSC_QUARTERS, quarters=2)
    assert burn == pytest.approx((3_556_415 + 2_570_875) / 2)


def test_burn_rate_none_con_meno_di_due_trimestri() -> None:
    assert quarterly_burn_rate([]) is None
    assert quarterly_burn_rate([_quarter(2026, "Q1", "2026-03-31", net=-1_000)]) is None


def test_burn_rate_ignora_i_trimestri_senza_risultato() -> None:
    quarters = [
        _quarter(2026, "Q1", "2026-03-31", net=-1_000_000),
        _quarter(2026, "Q2", "2026-06-30", net=None),
    ]
    # Resta un solo trimestre utile: sotto il minimo.
    assert quarterly_burn_rate(quarters) is None


def test_burn_rate_azzerato_se_l_azienda_e_in_utile() -> None:
    quarters = [
        _quarter(2026, "Q1", "2026-03-31", net=2_000_000),
        _quarter(2026, "Q2", "2026-06-30", net=3_000_000),
    ]
    assert quarterly_burn_rate(quarters) == 0.0


def test_burn_rate_assorbe_un_trimestre_anomalo_in_utile() -> None:
    """Le poste non monetarie possono rendere positivo un trimestre: la media assorbe."""
    quarters = ENSC_QUARTERS[:4]  # include il Q3 2024 in utile
    burn = quarterly_burn_rate(quarters)
    assert burn is not None
    assert burn > 0


def test_burn_rate_rifiuta_finestre_non_valide() -> None:
    with pytest.raises(ValueError, match="almeno 1"):
        quarterly_burn_rate(ENSC_QUARTERS, quarters=0)


# --- Cash runway --------------------------------------------------------------


def test_cash_runway_su_dati_reali() -> None:
    # 676.704 / 3.156.096,75 = 0,2144 trimestri -> 0,64 mesi.
    runway = cash_runway_months(676_704, 3_156_096.75)
    assert runway == pytest.approx(0.6432, abs=1e-3)


def test_cash_runway_none_se_manca_un_ingrediente() -> None:
    assert cash_runway_months(None, 1_000) is None
    assert cash_runway_months(1_000, None) is None


def test_cash_runway_non_definito_se_il_burn_e_nullo() -> None:
    """Un'azienda in utile non ha runway: restituire un numero enorme sarebbe fuorviante."""
    assert cash_runway_months(1_000_000, 0.0) is None


def test_cash_runway_rifiuta_cassa_negativa() -> None:
    assert cash_runway_months(-100, 1_000) is None


def test_cash_runway_e_proporzionale_alla_cassa() -> None:
    assert cash_runway_months(3_000_000, 1_000_000) == pytest.approx(9.0)


# --- Flottante ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("float_shares", "expected"),
    [
        (1_000_000, 100.0),  # sotto la soglia di scarsità
        (5_000_000, 100.0),  # esattamente alla soglia
        (100_000_000, 0.0),  # alla soglia di abbondanza
        (500_000_000, 0.0),  # oltre
    ],
)
def test_float_scarcity_agli_estremi(float_shares: float, expected: float) -> None:
    assert float_scarcity_score(float_shares) == expected


def test_float_scarcity_interpola_in_scala_logaritmica() -> None:
    # Media geometrica fra 5M e 100M: deve cadere a metà scala.
    geometric_mid = (5_000_000 * 100_000_000) ** 0.5
    assert float_scarcity_score(geometric_mid) == pytest.approx(50.0)


def test_float_scarcity_decresce_al_crescere_del_flottante() -> None:
    assert float_scarcity_score(10_000_000) > float_scarcity_score(50_000_000)  # type: ignore[operator]


def test_float_scarcity_none_su_dati_non_validi() -> None:
    assert float_scarcity_score(None) is None
    assert float_scarcity_score(0) is None
    assert float_scarcity_score(-5) is None


# --- Short squeeze score ------------------------------------------------------


def test_squeeze_score_massimo_con_tutti_i_fattori_estremi() -> None:
    score = short_squeeze_score(
        short_percent_of_float=35.0, days_to_cover=12.0, float_shares=2_000_000
    )
    assert score == pytest.approx(100.0)


def test_squeeze_score_minimo_con_tutti_i_fattori_benigni() -> None:
    score = short_squeeze_score(
        short_percent_of_float=0.0, days_to_cover=0.0, float_shares=200_000_000
    )
    assert score == pytest.approx(0.0)


def test_squeeze_score_ridistribuisce_i_pesi_sui_dati_presenti() -> None:
    """Con lo short interest assente il punteggio usa solo il flottante."""
    score = short_squeeze_score(
        short_percent_of_float=None, days_to_cover=None, float_shares=2_000_000
    )
    assert score == pytest.approx(100.0)


def test_squeeze_score_none_senza_alcun_dato() -> None:
    assert short_squeeze_score(None, None, None) is None


def test_squeeze_score_none_se_solo_flottante_non_valido() -> None:
    assert short_squeeze_score(None, None, 0) is None


def test_squeeze_score_ignora_valori_negativi() -> None:
    score = short_squeeze_score(
        short_percent_of_float=-1.0, days_to_cover=-2.0, float_shares=2_000_000
    )
    # Restano solo i pesi del flottante.
    assert score == pytest.approx(100.0)


def test_squeeze_score_pesa_di_piu_lo_short_percent() -> None:
    solo_short = short_squeeze_score(30.0, 0.0, 200_000_000)
    solo_giorni = short_squeeze_score(0.0, 10.0, 200_000_000)
    assert solo_short is not None and solo_giorni is not None
    assert solo_short > solo_giorni


def test_squeeze_score_su_dati_reali_ensc() -> None:
    # ENSC: 5,86% del flottante short, 0,03 giorni di copertura, 19,4M di flottante.
    score = short_squeeze_score(5.86, 0.03, 19_443_174)
    assert score is not None
    # Short interest basso e copertura immediata: potenziale contenuto.
    assert 0 < score < 30


# --- Dilution risk ------------------------------------------------------------


@pytest.mark.parametrize(
    ("runway", "expected"),
    [
        (0.0, 100.0),
        (6.0, 100.0),  # alla soglia critica
        (24.0, 0.0),  # alla soglia di comfort
        (36.0, 0.0),
        (15.0, 50.0),  # esattamente a metà fra le due soglie
    ],
)
def test_runway_pressure_alle_soglie(runway: float, expected: float) -> None:
    assert runway_pressure_score(runway) == pytest.approx(expected)


def test_runway_pressure_none_su_dati_mancanti_o_negativi() -> None:
    assert runway_pressure_score(None) is None
    assert runway_pressure_score(-1.0) is None


def test_dilution_risk_massimo_con_cassa_agli_sgoccioli_e_atm_attivo() -> None:
    score = dilution_risk_score(
        cash_runway_months=0.6, atm_offering_mentioned=True, warrant_mentioned=True
    )
    assert score == pytest.approx(100.0)


def test_dilution_risk_minimo_con_cassa_abbondante_e_nessun_segnale() -> None:
    score = dilution_risk_score(
        cash_runway_months=36.0, atm_offering_mentioned=False, warrant_mentioned=False
    )
    assert score == pytest.approx(0.0)


def test_dilution_risk_distingue_non_cercato_da_non_trovato() -> None:
    """None = ricerca non eseguita (peso ridistribuito); False = cercato e assente."""
    non_cercato = dilution_risk_score(24.0, None, None)
    non_trovato = dilution_risk_score(24.0, False, False)
    assert non_cercato == pytest.approx(0.0)
    assert non_trovato == pytest.approx(0.0)

    # Con runway critico la differenza emerge.
    non_cercato_critico = dilution_risk_score(0.0, None, None)
    con_atm = dilution_risk_score(0.0, True, False)
    assert non_cercato_critico == pytest.approx(100.0)
    assert con_atm is not None
    assert con_atm < 100.0


def test_dilution_risk_none_senza_alcun_ingrediente() -> None:
    assert dilution_risk_score(None, None, None) is None


# --- Expected value: il cuore del requisito -----------------------------------


def _scenari(current: float = 5.0) -> object:
    return build_scenario_analysis(
        current_price=current,
        bull=ScenarioInput(0.25, 14.0, "Esito positivo netto"),
        base=ScenarioInput(0.45, 6.5, "Esito parziale"),
        bear=ScenarioInput(0.30, 1.8, "Fallimento del trial"),
    )


def test_target_change_pct() -> None:
    assert target_change_pct(15.0, 10.0) == pytest.approx(50.0)
    assert target_change_pct(5.0, 10.0) == pytest.approx(-50.0)
    assert target_change_pct(10.0, 10.0) == pytest.approx(0.0)


def test_target_change_pct_rifiuta_prezzo_non_positivo() -> None:
    with pytest.raises(ValueError, match="positivo"):
        target_change_pct(10.0, 0.0)


def test_build_scenario_analysis_calcola_le_variazioni_in_python() -> None:
    """L'LLM fornisce probabilità e target; la percentuale la calcola il codice."""
    scenarios = build_scenario_analysis(
        current_price=5.0,
        bull=ScenarioInput(0.25, 15.0, "su"),
        base=ScenarioInput(0.45, 5.0, "piatto"),
        bear=ScenarioInput(0.30, 2.5, "giu"),
    )
    assert scenarios.bull.target_price_change_pct == pytest.approx(200.0)
    assert scenarios.base.target_price_change_pct == pytest.approx(0.0)
    assert scenarios.bear.target_price_change_pct == pytest.approx(-50.0)


def test_expected_price_media_pesata_per_probabilita() -> None:
    scenarios = _scenari()
    # 0,25*14 + 0,45*6,5 + 0,30*1,8 = 3,5 + 2,925 + 0,54 = 6,965
    assert expected_price(scenarios) == pytest.approx(6.965)  # type: ignore[arg-type]


def test_expected_roi_pct() -> None:
    scenarios = _scenari(current=5.0)
    # 6,965 / 5,0 - 1 = +39,3%
    assert expected_roi_pct(scenarios, 5.0) == pytest.approx(39.3)  # type: ignore[arg-type]


def test_expected_roi_pct_rifiuta_prezzo_non_positivo() -> None:
    with pytest.raises(ValueError, match="positivo"):
        expected_roi_pct(_scenari(), 0.0)  # type: ignore[arg-type]


def test_expected_value_calcola_azioni_valore_e_roi() -> None:
    analysis = build_expected_value_analysis(
        current_price_usd=5.0,
        scenarios=_scenari(),  # type: ignore[arg-type]
        eur_usd_rate=1.1662,
        rate_date=date(2026, 8, 25),
    )

    assert len(analysis.rows) == 1
    riga = analysis.rows[0]
    assert riga.investment_usd == 1000.0
    # 1000 USD / 5,00 = 200 azioni
    assert riga.shares_purchasable == pytest.approx(200.0)
    # 200 azioni * 6,965 USD di prezzo atteso = 1.393 USD
    assert riga.expected_value_usd == pytest.approx(1393.0)
    assert riga.expected_roi_pct == pytest.approx(39.3)


def test_expected_value_il_cambio_e_solo_un_riferimento() -> None:
    """Il calcolo è in dollari: il cambio non deve entrarci."""
    comune: dict[str, object] = {
        "current_price_usd": 5.0,
        "scenarios": _scenari(),
        "rate_date": date(2026, 8, 25),
    }
    a = build_expected_value_analysis(eur_usd_rate=1.05, **comune)  # type: ignore[arg-type]
    b = build_expected_value_analysis(eur_usd_rate=1.25, **comune)  # type: ignore[arg-type]

    assert a.rows[0].expected_value_usd == pytest.approx(b.rows[0].expected_value_usd)
    assert a.rows[0].shares_purchasable == pytest.approx(b.rows[0].shares_purchasable)
    # Il tasso resta allegato al report come riferimento.
    assert a.eur_usd_rate == 1.05


def test_expected_value_senza_cambio_si_calcola_comunque() -> None:
    analysis = build_expected_value_analysis(
        current_price_usd=5.0,
        scenarios=_scenari(),  # type: ignore[arg-type]
    )
    assert analysis.eur_usd_rate is None
    assert analysis.rate_date is None
    assert analysis.rows[0].expected_roi_pct == pytest.approx(39.3)


def test_expected_value_il_roi_non_dipende_dall_importo() -> None:
    analysis = build_expected_value_analysis(
        current_price_usd=5.0,
        scenarios=_scenari(),  # type: ignore[arg-type]
        investments_usd=(1000.0, 2000.0),
    )
    assert analysis.rows[0].expected_roi_pct == pytest.approx(analysis.rows[1].expected_roi_pct)
    assert analysis.rows[1].expected_value_usd == pytest.approx(
        analysis.rows[0].expected_value_usd * 2
    )


def test_expected_value_importi_personalizzati() -> None:
    analysis = build_expected_value_analysis(
        current_price_usd=5.0,
        scenarios=_scenari(),  # type: ignore[arg-type]
        investments_usd=(250.0,),
    )
    assert [r.investment_usd for r in analysis.rows] == [250.0]


@pytest.mark.parametrize(
    ("prezzo", "tasso", "importi", "atteso"),
    [
        (0.0, 1.1, (1000.0,), "prezzo corrente"),
        (5.0, 0.0, (1000.0,), "tasso EUR/USD"),
        (5.0, 1.1, (0.0,), "importo investito"),
        (5.0, 1.1, (-100.0,), "importo investito"),
    ],
)
def test_expected_value_rifiuta_input_non_validi(
    prezzo: float, tasso: float, importi: tuple[float, ...], atteso: str
) -> None:
    with pytest.raises(ValueError, match=atteso):
        build_expected_value_analysis(
            current_price_usd=prezzo,
            scenarios=_scenari(),  # type: ignore[arg-type]
            investments_usd=importi,
            eur_usd_rate=tasso,
            rate_date=date(2026, 8, 25),
        )


# --- Catalizzatori ------------------------------------------------------------


def _trial(
    nct: str,
    status: str = "RECRUITING",
    completion: str | None = "2026-12-01",
    phase: list[str] | None = None,
    completion_type: str | None = "ESTIMATED",
    endpoint: str | None = None,
) -> ClinicalTrial:
    return ClinicalTrial(
        nct_id=nct,
        brief_title=f"Studio {nct}",
        phase=phase if phase is not None else ["PHASE3"],
        overall_status=status,
        primary_completion_date=date.fromisoformat(completion) if completion else None,
        primary_completion_date_type=completion_type,  # type: ignore[arg-type]
        primary_outcome_measure=endpoint,
    )


def test_catalizzatori_ordinati_per_imminenza() -> None:
    trials = [
        _trial("NCT003", completion="2027-06-01"),
        _trial("NCT001", completion="2026-10-01"),
        _trial("NCT002", completion="2026-12-01"),
    ]
    catalysts = catalysts_from_trials(trials, today=date(2026, 8, 26))

    assert [c.source.split()[-1] for c in catalysts] == ["NCT001", "NCT002", "NCT003"]
    assert [c.imminence_rank for c in catalysts] == [1, 2, 3]


def test_catalizzatori_escludono_gli_studi_conclusi() -> None:
    trials = [
        _trial("NCT001", status="COMPLETED", completion="2027-01-01"),
        _trial("NCT002", status="TERMINATED", completion="2027-01-01"),
        _trial("NCT003", status="RECRUITING", completion="2027-01-01"),
    ]
    catalysts = catalysts_from_trials(trials, today=date(2026, 8, 26))

    assert len(catalysts) == 1
    assert "NCT003" in catalysts[0].source


def test_uno_studio_attivo_in_ritardo_resta_un_catalizzatore() -> None:
    """Il caso SELLAS: data stimata passata ma studio ancora attivo.

    Scartarlo faceva sparire dall'analisi lo studio di Fase 3 che è la
    ragione principale della valutazione del titolo.
    """
    trials = [_trial("NCT001", completion="2025-12-01", completion_type="ESTIMATED")]

    catalysts = catalysts_from_trials(trials, today=date(2026, 8, 26))

    assert len(catalysts) == 1
    assert catalysts[0].is_overdue is True
    assert catalysts[0].overdue_days == 268
    assert "superata da 268 giorni" in (catalysts[0].expected_date_window or "")


def test_una_data_effettiva_passata_significa_completamento_avvenuto() -> None:
    """ACTUAL nel passato = è successo davvero, non è un ritardo."""
    trials = [_trial("NCT001", completion="2025-12-01", completion_type="ACTUAL")]
    assert catalysts_from_trials(trials, today=date(2026, 8, 26)) == []


def test_gli_studi_in_ritardo_precedono_quelli_futuri() -> None:
    """Una lettura scaduta può arrivare in qualunque momento: è la più imminente."""
    trials = [
        _trial("NCT_FUTURO", completion="2026-10-01"),
        _trial("NCT_RITARDO", completion="2025-12-01"),
    ]

    catalysts = catalysts_from_trials(trials, today=date(2026, 8, 26))

    assert [c.source.split()[-1] for c in catalysts] == ["NCT_RITARDO", "NCT_FUTURO"]
    assert catalysts[0].imminence_rank == 1


def test_uno_studio_in_ritardo_ignora_la_finestra_temporale() -> None:
    """È già scaduto: escluderlo per 'troppo lontano' non avrebbe senso."""
    trials = [_trial("NCT001", completion="2024-01-01")]

    catalysts = catalysts_from_trials(trials, today=date(2026, 8, 26), window_months=3)

    assert len(catalysts) == 1
    assert catalysts[0].is_overdue is True


@pytest.mark.parametrize(
    ("endpoint", "atteso"),
    [
        ("OS", True),
        ("Overall Survival", True),
        ("Progression-Free Survival (PFS)", True),
        ("PFS", True),
        ("Event-free survival", True),
        ("Duration of Response", True),
        ("Number of participants with adverse events", False),
        ("Tmax", False),
        ("Maximum tolerated dose", False),  # "dose" contiene "os" ma non è un match
        ("Objective response rate", False),
        (None, False),
        ("", False),
    ],
)
def test_riconoscimento_degli_endpoint_a_eventi(endpoint: str | None, atteso: bool) -> None:
    assert is_event_driven(_trial("NCT1", endpoint=endpoint)) is atteso


def test_un_ritardo_su_endpoint_a_eventi_viene_spiegato() -> None:
    """Negli studi a eventi il ritardo è un'informazione, non solo un contrattempo."""
    trials = [_trial("NCT1", completion="2025-12-01", endpoint="Overall Survival (OS)")]

    catalysts = catalysts_from_trials(trials, today=date(2026, 8, 26))

    nota = catalysts[0].expected_date_window or ""
    assert catalysts[0].is_event_driven is True
    assert "eventi si accumulano più lentamente" in nota


def test_la_materialita_riflette_la_fase() -> None:
    catalysts = catalysts_from_trials(
        [_trial("NCT1", phase=["PHASE3"]), _trial("NCT2", phase=["PHASE1"])],
        today=date(2026, 8, 26),
    )
    per_nct = {c.source.split()[-1]: c for c in catalysts}
    assert per_nct["NCT1"].phase_materiality == 3
    assert per_nct["NCT2"].phase_materiality == 1


def test_catalizzatori_escludono_i_trial_senza_data() -> None:
    trials = [_trial("NCT001", completion=None)]
    assert catalysts_from_trials(trials, today=date(2026, 8, 26)) == []


def test_catalizzatori_filtrano_per_finestra_temporale() -> None:
    trials = [
        _trial("NCT001", completion="2026-10-01"),  # fra 2 mesi
        _trial("NCT002", completion="2027-10-01"),  # fra 14 mesi
    ]
    catalysts = catalysts_from_trials(trials, today=date(2026, 8, 26), window_months=6)

    assert len(catalysts) == 1
    assert "NCT001" in catalysts[0].source


def test_catalizzatori_segnalano_le_date_stimate() -> None:
    stimato = catalysts_from_trials([_trial("NCT001")], today=date(2026, 8, 26))
    effettivo = catalysts_from_trials(
        [_trial("NCT002", completion_type="ACTUAL")], today=date(2026, 8, 26)
    )

    assert stimato[0].expected_date_window == "data stimata dallo sponsor"
    assert effettivo[0].expected_date_window is None


def test_catalizzatori_a_parita_di_data_ordinano_per_identificativo() -> None:
    trials = [_trial("NCT002"), _trial("NCT001")]
    catalysts = catalysts_from_trials(trials, today=date(2026, 8, 26))
    assert [c.imminence_rank for c in catalysts] == [1, 2]
    assert "NCT001" in catalysts[0].source


@pytest.mark.parametrize(
    ("phases", "atteso"),
    [
        (["PHASE3"], "Fase 3"),
        (["PHASE1", "PHASE2"], "Fase 1/Fase 2"),
        (["NA"], "Fase non applicabile"),
        ([], "Studio clinico"),
    ],
)
def test_etichetta_di_fase(phases: list[str], atteso: str) -> None:
    catalysts = catalysts_from_trials([_trial("NCT001", phase=phases)], today=date(2026, 8, 26))
    assert catalysts[0].name.startswith(atteso)


def test_catalizzatori_usa_oggi_se_non_specificato() -> None:
    trials = [_trial("NCT001", completion="2099-01-01")]
    assert len(catalysts_from_trials(trials)) == 1


# --- Composizione delle metriche ----------------------------------------------


def test_compute_metrics_su_dati_reali_ensc() -> None:
    metrics, notes = compute_financial_metrics(
        ENSC_QUARTERS,
        market_data=MarketData(
            price=0.403,
            float_shares=19_443_174,
            short_percent_of_float=5.86,
            short_ratio_days=0.03,
        ),
        filing_signals=SECFilingSignals(
            atm_offering_mentioned=True,
            warrant_mentioned=True,
            as_of=date(2026, 8, 26),
        ),
    )

    assert metrics.quarterly_burn_rate_usd == pytest.approx(3_156_096.75)
    assert metrics.cash_runway_months == pytest.approx(0.6432, abs=1e-3)
    assert metrics.short_squeeze_score is not None
    # Cassa quasi esaurita con ATM e warrant attivi: diluizione pressoché certa.
    assert metrics.dilution_risk_score == pytest.approx(100.0)
    # Le metriche sono ancorate al trimestre della cassa, non a oggi.
    assert metrics.as_of == date(2026, 6, 30)
    assert notes == []


def test_compute_metrics_annota_le_metriche_non_calcolabili() -> None:
    metrics, notes = compute_financial_metrics([])

    assert metrics.cash_runway_months is None
    assert metrics.quarterly_burn_rate_usd is None
    assert metrics.short_squeeze_score is None
    assert metrics.dilution_risk_score is None
    assert any("cassa non disponibile" in n for n in notes)
    assert any("burn rate non calcolabile" in n for n in notes)
    assert any("short squeeze score non calcolabile" in n for n in notes)
    assert any("dilution risk score non calcolabile" in n for n in notes)


def test_compute_metrics_annota_l_azienda_in_utile() -> None:
    quarters = [
        _quarter(2026, "Q1", "2026-03-31", cash=10_000_000, net=2_000_000),
        _quarter(2026, "Q2", "2026-06-30", cash=12_000_000, net=3_000_000),
    ]
    metrics, notes = compute_financial_metrics(quarters)

    assert metrics.quarterly_burn_rate_usd == 0.0
    assert metrics.cash_runway_months is None
    assert any("mediamente in utile" in n for n in notes)
    assert any("burn rate è nullo" in n for n in notes)


def test_compute_metrics_accetta_data_di_riferimento_esplicita() -> None:
    metrics, _ = compute_financial_metrics(ENSC_QUARTERS, as_of=date(2026, 8, 26))
    assert metrics.as_of == date(2026, 8, 26)


def test_compute_metrics_usa_oggi_senza_cassa() -> None:
    metrics, _ = compute_financial_metrics([])
    assert metrics.as_of == date.today()


def test_compute_metrics_rispetta_la_finestra_di_burn() -> None:
    metrics, _ = compute_financial_metrics(ENSC_QUARTERS, burn_quarters=2)
    assert metrics.quarterly_burn_rate_usd == pytest.approx((3_556_415 + 2_570_875) / 2)


def test_media_pesata_con_peso_totale_nullo() -> None:
    """Guardia difensiva: irraggiungibile con i pesi attuali, ma protegge da
    una modifica futura che azzerasse una costante di peso."""
    from biocatalyst.analysis.risk import _weighted

    assert _weighted([(50.0, 0.0)]) is None
    assert _weighted([]) is None
