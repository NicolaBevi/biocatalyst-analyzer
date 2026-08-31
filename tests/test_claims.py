"""Test della separazione fra cifre misurate e cifre di provenienza ignota."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel

from biocatalyst.analysis.claims import (
    collect_known_values,
    unverified_figures,
)
from biocatalyst.models.analysis import FinancialMetrics
from biocatalyst.models.raw_data import ScheduleRevision, TrialScheduleHistory


def test_una_cifra_nota_non_viene_segnalata() -> None:
    testo = "Il burn rate trimestrale è di 3.156.097 dollari."
    assert unverified_figures(testo, {3_156_097.0}) == []


def test_una_cifra_ignota_viene_segnalata_col_contesto() -> None:
    testo = "La sopravvivenza mediana storica del braccio di controllo è di 8 mesi."
    trovate = unverified_figures(testo, {127.0})

    assert len(trovate) == 1
    assert trovate[0].value == 8.0
    assert "sopravvivenza mediana" in trovate[0].context


def test_gli_arrotondamenti_del_modello_restano_verificati() -> None:
    """$129.238 diventa "circa $129.000" nella prosa: è la stessa cifra."""
    testo = "Il comparatore costa circa $129,000 all'anno."
    assert unverified_figures(testo, {129_238.0}) == []


def test_i_moltiplicatori_vengono_normalizzati() -> None:
    testo = "Il mercato vale 450 million di dollari."
    assert unverified_figures(testo, {450_000_000.0}) == []


def test_percentuali_e_frazioni_sono_la_stessa_cosa() -> None:
    """Il modello scrive indifferentemente "0,25" e "25%"."""
    assert unverified_figures("una probabilità del 25%", {0.25}) == []


def test_gli_anni_non_sono_quantita_da_verificare() -> None:
    testo = "La lettura era attesa nel 2025 ed è slittata al 2026."
    assert unverified_figures(testo, set()) == []


def test_i_numeri_minuscoli_non_riempiono_l_elenco() -> None:
    """Segnalare "le 2 letture possibili" sarebbe solo rumore."""
    assert unverified_figures("Ci sono 2 letture possibili.", set()) == []


def test_ogni_cifra_compare_una_volta_sola() -> None:
    testo = "Sono 800 pazienti. Gli 800 pazienti sono pochi. Ancora 800."
    assert len(unverified_figures(testo, set())) == 1


def test_la_raccolta_dei_valori_noti_include_le_proprieta_calcolate() -> None:
    """I mesi di slittamento esistono solo come proprietà.

    Senza guardarle, il "48 mesi" scritto nel testo risulterebbe non
    verificato pur essendo un nostro calcolo.
    """
    storia = TrialScheduleHistory(
        nct_id="NCT1",
        revisions_total=10,
        first_declared_date=date(2021, 12, 1),
        current_declared_date=date(2025, 12, 1),
        changes=[
            ScheduleRevision(
                revised_on=date(2023, 1, 27),
                previous_date=date(2021, 12, 1),
                new_date=date(2024, 12, 1),
            )
        ],
    )
    noti = collect_known_values(storia)

    assert 1461.0 in noti, "i giorni di slittamento sono un campo derivato"
    assert unverified_figures("La data è slittata di 48 mesi.", noti) == []


def test_la_raccolta_attraversa_i_modelli_annidati() -> None:
    metriche = FinancialMetrics(
        cash_runway_months=51.1,
        quarterly_burn_rate_usd=3_156_097,
        as_of=date(2026, 6, 30),
    )
    noti = collect_known_values(metriche)
    assert {51.1, 3_156_097.0} <= noti


def test_le_sezioni_narrative_non_sono_una_fonte() -> None:
    """Verificare la prosa contro sé stessa non verificherebbe nulla."""
    finto = {"sections": {"a": "il valore è 999999"}, "prezzo": 12.5}
    noti = collect_known_values(finto)
    assert 12.5 in noti
    assert unverified_figures("il valore è 999999", noti) != []


def test_uno_zero_fra_i_valori_noti_non_rompe_il_confronto() -> None:
    """Uno zero non è divisibile: senza la guardia il confronto esploderebbe.

    Capita davvero: un burn rate o uno short interest a zero finiscono fra i
    valori noti come tutti gli altri.
    """
    trovate = unverified_figures("la sopravvivenza mediana è di 9 mesi", {0.0, 127.0})
    assert [f.value for f in trovate] == [9.0], "lo zero non deve coprire nulla"


def test_l_elenco_ha_un_tetto() -> None:
    """Un elenco lunghissimo non aiuterebbe nessuno a controllare le cifre."""
    testo = " ".join(f"il valore {n}" for n in range(100, 130))
    assert len(unverified_figures(testo, set(), max_results=4)) == 4


def test_la_raccolta_non_scende_all_infinito() -> None:
    """Una struttura che si contiene fermerebbe la raccolta senza la guardia."""
    annidato: dict[str, object] = {"valore": 7.0}
    corrente = annidato
    for _ in range(20):
        successivo: dict[str, object] = {"valore": 7.0}
        corrente["dentro"] = successivo
        corrente = successivo

    noti = collect_known_values(annidato)
    assert 7.0 in noti, "i livelli raggiungibili vanno comunque raccolti"


def test_una_proprieta_che_solleva_non_ferma_la_raccolta() -> None:
    """Meglio perdere un valore che perdere l'intero elenco."""

    class ConProprietaRotta(BaseModel):
        prezzo: float

        @property
        def rotta(self) -> float:
            raise RuntimeError("questa proprietà non funziona")

    noti = collect_known_values(ConProprietaRotta(prezzo=13.85))
    assert 13.85 in noti
