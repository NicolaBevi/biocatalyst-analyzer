"""Test dei tassi storici di successo usati come termine di paragone."""

from __future__ import annotations

import pytest

from biocatalyst.analysis.base_rates import (
    _AREA_KEYWORDS,
    APPROVAL_FROM_PHASE1_BY_AREA,
    OVERALL,
    base_rate_for,
    detect_therapeutic_area,
    highest_phase,
)


@pytest.mark.parametrize(
    ("conditions", "atteso"),
    [
        (["Acute Myeloid Leukemia"], "hematology"),
        (["Non-Small Cell Lung Cancer"], "oncology"),
        (["Metastatic Melanoma"], "oncology"),
        (["Alzheimer Disease"], "neurology"),
        (["Type 2 Diabetes"], "metabolic"),
        (["Healthy Volunteers"], None),
        ([], None),
    ],
)
def test_riconoscimento_area_terapeutica(conditions: list[str], atteso: str | None) -> None:
    assert detect_therapeutic_area(conditions) == atteso


def test_i_tumori_del_sangue_non_finiscono_fra_i_solidi() -> None:
    """L'ematologia ha tassi molto più alti dei tumori solidi.

    Una leucemia contiene spesso la parola "cancer" nelle condizioni: se
    vincesse l'oncologia il riferimento sarebbe quello sbagliato (5,3% invece
    di 23,9% di probabilità di approvazione).
    """
    assert detect_therapeutic_area(["Leukemia", "Blood Cancer"]) == "hematology"


def test_la_sigla_all_non_cattura_la_parola_inglese() -> None:
    """ "ALL" (leucemia linfoblastica acuta) coincide con l'inglese "all"."""
    assert detect_therapeutic_area(["All Solid Tumors"]) == "oncology"
    assert detect_therapeutic_area(["All Advanced Carcinomas"]) == "oncology"


def test_i_plurali_vengono_riconosciuti() -> None:
    assert detect_therapeutic_area(["Solid Tumors"]) == "oncology"
    assert detect_therapeutic_area(["Solid Tumor"]) == "oncology"


@pytest.mark.parametrize(
    ("phases", "atteso"),
    [
        (["PHASE1", "PHASE2"], "PHASE2"),
        (["PHASE3"], "PHASE3"),
        (["EARLY_PHASE1"], None),
        (["NA"], None),
        ([], None),
    ],
)
def test_fase_piu_avanzata(phases: list[str], atteso: str | None) -> None:
    assert highest_phase(phases) == atteso


def test_tasso_di_riferimento_completo() -> None:
    rate = base_rate_for(["PHASE3"], ["Acute Myeloid Leukemia"])
    assert rate is not None
    assert rate.transition_pct == pytest.approx(57.8)
    assert rate.approval_pct == pytest.approx(23.9)
    assert rate.area == "hematology"
    assert rate.label == "Phase 3 — hematology"
    # La fonte viaggia col dato: non è ricavato da un'API, va potuto verificare.
    assert "BIO" in rate.source
    assert rate.data_through_year == 2020


def test_senza_area_riconosciuta_si_usa_il_dato_complessivo() -> None:
    rate = base_rate_for(["PHASE2"], ["Healthy Volunteers"])
    assert rate is not None
    assert rate.area == "all indications"
    assert rate.approval_pct == OVERALL["PHASE2"].approval_pct


def test_senza_fase_nota_nessun_riferimento() -> None:
    assert base_rate_for([], ["Cancer"]) is None
    assert base_rate_for(["NA"], ["Cancer"]) is None


def test_ogni_area_con_un_tasso_ha_anche_le_parole_per_riconoscerla() -> None:
    """Un'area senza parole chiave è un tasso irraggiungibile."""
    assert set(APPROVAL_FROM_PHASE1_BY_AREA).issubset(set(_AREA_KEYWORDS))


def test_la_transizione_e_sempre_piu_probabile_dell_approvazione() -> None:
    """Superare una fase è per forza più facile che arrivare in fondo."""
    for fase, rate in OVERALL.items():
        assert rate.approval_pct is not None
        assert rate.approval_pct <= rate.transition_pct, fase
