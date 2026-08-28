"""Test del rendering nei quattro formati."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from biocatalyst.analysis.validation import (
    check_analyst_target,
    collect_data_warnings,
)
from biocatalyst.models.analysis import (
    Catalyst,
    FinancialMetrics,
    PhaseBaseRate,
    TAMEstimate,
)
from biocatalyst.models.raw_data import (
    DrugSpending,
    MarketData,
    ScheduleRevision,
    TrialScheduleHistory,
)
from biocatalyst.models.report import (
    AcquisitionAssessment,
    ExpectedValueAnalysis,
    ExpectedValueRow,
    Report,
    ReportLanguage,
    ReportSections,
    Scenario,
    ScenarioAnalysis,
    SourceEntry,
    SourceQuality,
)
from biocatalyst.report import render_html, render_json, render_markdown, save_report
from biocatalyst.report.labels import EXPLANATIONS, LABELS


def _report(language: ReportLanguage = "it", **overrides: object) -> Report:
    defaults: dict[str, object] = {
        "ticker": "ENSC",
        "company_name": "Ensysce Biosciences, Inc.",
        "report_date": date(2026, 8, 26),
        "generated_at": datetime(2026, 8, 26, 12, 6, tzinfo=UTC),
        "language": language,
        "current_price": 0.403,
        "rating": "SELL",
        "average_analyst_target": 8.25,
        "main_catalyst": "Fase 1 PF614-MPAR-102",
        "sections": ReportSections(
            pipeline_and_clinical_results="Panoramica della pipeline.",
            catalyst_analysis="Analisi del catalizzatore.",
            operational_strategy="Strategia operativa.",
        ),
        "financial_metrics": FinancialMetrics(
            cash_runway_months=0.64,
            quarterly_burn_rate_usd=3_156_097,
            short_squeeze_score=19.8,
            dilution_risk_score=100.0,
            as_of=date(2026, 6, 30),
        ),
        "market_snapshot": MarketData(
            price=0.403,
            market_cap_usd=7_841_088,
            float_shares=19_443_174,
            short_percent_of_float=5.86,
            short_ratio_days=0.03,
            short_interest_date=date(2026, 8, 14),
        ),
        "catalysts": [
            Catalyst(
                name="Fase 1: studio PF614",
                catalyst_type="clinical_readout",
                expected_date=date(2026, 12, 22),
                expected_date_window="data stimata dallo sponsor",
                source="ClinicalTrials.gov NCT06500793",
                imminence_rank=1,
            )
        ],
        "scenarios": ScenarioAnalysis(
            bull=Scenario(
                probability=0.10,
                target_price=0.75,
                target_price_change_pct=86.1,
                conditions="Dati positivi",
            ),
            base=Scenario(
                probability=0.40,
                target_price=0.35,
                target_price_change_pct=-13.2,
                conditions="Dati neutri",
            ),
            bear=Scenario(
                probability=0.50,
                target_price=0.15,
                target_price_change_pct=-62.8,
                conditions="Dati negativi",
            ),
        ),
        "expected_value": ExpectedValueAnalysis(
            rows=[
                ExpectedValueRow(
                    investment_usd=1000,
                    shares_purchasable=2481.4,
                    expected_value_usd=719.6,
                    expected_roi_pct=-28.0,
                )
            ],
            eur_usd_rate=1.1662,
            rate_date=date(2026, 8, 25),
        ),
        "acquisition": AcquisitionAssessment(
            probability_pct=5.0,
            potential_acquirers=["Pfizer"],
            comparable_deals=["Operazione 2025"],
        ),
        "tam": TAMEstimate(
            indication="Dolore acuto",
            prevalence_estimate="50 milioni di pazienti",
            pricing_comparable="$100/mese",
            tam_low_usd=1_000_000_000,
            tam_high_usd=3_000_000_000,
            methodology_notes="Stima conservativa.",
        ),
        "source_quality": SourceQuality(
            sources_consulted=[
                SourceEntry(name="SEC EDGAR XBRL", retrieved_at=datetime(2026, 8, 26, tzinfo=UTC))
            ],
            missing_data=[],
            warnings=["Target analisti sospetto"],
        ),
    }
    defaults.update(overrides)
    return Report(**defaults)  # type: ignore[arg-type]


# --- Controllo del target price ------------------------------------------------


@pytest.mark.parametrize(
    ("target", "prezzo", "atteso_avviso"),
    [
        (8.25, 0.403, True),  # 20x: il caso reale di ENSC
        (2.0, 1.0, False),  # 2x: normale su un titolo speculativo
        (5.0, 1.0, False),  # 5x: esattamente alla soglia, ancora accettabile
        (5.01, 1.0, True),  # appena oltre
        (0.1, 1.0, True),  # 0,1x: anomalo verso il basso
        (0.5, 1.0, False),
        (None, 1.0, False),  # dato assente: nessun avviso
        (8.25, None, False),
        (8.25, 0.0, False),  # prezzo non valido
        (0.0, 1.0, False),  # target non valido
    ],
)
def test_controllo_target_analisti(
    target: float | None, prezzo: float | None, atteso_avviso: bool
) -> None:
    risultato = check_analyst_target(target, prezzo)
    assert (risultato is not None) is atteso_avviso


def test_avviso_target_cita_i_numeri() -> None:
    avviso = check_analyst_target(8.25, 0.403)
    assert avviso is not None
    assert "8.25" in avviso
    assert "0.40" in avviso
    assert "20.5" in avviso  # il rapporto calcolato


def test_avvisi_includono_l_arretratezza_dello_short_interest() -> None:
    avvisi = collect_data_warnings(
        analyst_target=1.0, current_price=1.0, short_interest_days_old=12
    )
    assert len(avvisi) == 1
    assert "12 days old" in avvisi[0]
    assert "FINRA" in avvisi[0]


def test_nessun_avviso_su_dati_coerenti() -> None:
    assert collect_data_warnings(analyst_target=1.2, current_price=1.0) == []


# --- Markdown -------------------------------------------------------------------


def test_markdown_contiene_tutte_le_sezioni_richieste() -> None:
    testo = render_markdown(_report())

    for titolo in (
        "Pipeline e risultati clinici",
        "Analisi finanziaria",
        "Catalizzatore principale",
        "Scenari",
        "Valore atteso",
        "Probabilità di acquisizione",
        "Strategia operativa",
        "Fonti e qualità del dato",
    ):
        assert f"## {titolo}" in testo


def test_markdown_riporta_entrambe_le_date() -> None:
    testo = render_markdown(_report())
    assert "Analisi generata il**: 2026-08-26" in testo
    assert "Dati interrogati il**: 2026-08-26 12:06 UTC" in testo


def test_markdown_mette_gli_avvisi_in_cima() -> None:
    """Se un dato è inaffidabile il lettore deve saperlo prima di leggerlo."""
    testo = render_markdown(_report())
    posizione_avviso = testo.index("Target analisti sospetto")
    posizione_analisi = testo.index("## Analisi finanziaria")
    assert posizione_avviso < posizione_analisi


def test_markdown_include_le_spiegazioni_delle_metriche() -> None:
    """Il report deve spiegare cosa si sta leggendo, non solo elencare numeri."""
    testo = render_markdown(_report())
    assert "un aumento di capitale diventa probabile" in testo  # runway
    assert "poste non monetarie" in testo  # burn rate
    assert "Non è una probabilità" in testo  # squeeze score
    assert "aritmetico e svolto dal sistema" in testo  # expected value


def test_markdown_riporta_capitalizzazione_float_e_short() -> None:
    """Il formato richiesto elenca esplicitamente questi campi."""
    testo = render_markdown(_report())
    assert "$7,841,088" in testo
    assert "19,443,174" in testo
    assert "5.86%" in testo
    # Accanto allo short interest deve comparire la data di riferimento.
    assert "2026-08-14" in testo


def test_markdown_expected_value_in_dollari() -> None:
    testo = render_markdown(_report())
    assert "$1,000" in testo
    assert "$719.60" in testo
    assert "-28.0%" in testo
    # Il cambio compare solo come riferimento.
    assert "1 EUR = 1.1662 USD" in testo


def test_markdown_in_inglese() -> None:
    testo = render_markdown(_report(language="en"))
    assert "## Financial analysis" in testo
    assert "## Expected value" in testo
    assert "Analysis generated on" in testo
    assert "a capital raise becomes likely" in testo
    assert "Analisi finanziaria" not in testo


def test_markdown_gestisce_le_metriche_assenti() -> None:
    report = _report(
        financial_metrics=FinancialMetrics(as_of=date(2026, 6, 30)),
        source_quality=SourceQuality(missing_data=["burn rate non calcolabile"]),
    )
    testo = render_markdown(report)
    assert "—" in testo
    assert "burn rate non calcolabile" in testo


# --- JSON -----------------------------------------------------------------------


def test_json_e_valido_e_completo() -> None:
    dati = json.loads(render_json(_report()))

    assert dati["ticker"] == "ENSC"
    assert dati["rating"] == "SELL"
    assert dati["language"] == "it"
    assert dati["generated_at"].startswith("2026-08-26")
    assert dati["expected_value"]["rows"][0]["investment_usd"] == 1000
    assert dati["source_quality"]["warnings"] == ["Target analisti sospetto"]


def test_json_preserva_gli_accenti() -> None:
    """ensure_ascii=False: gli accenti restano leggibili invece di diventare \\uXXXX."""
    testo = render_json(_report())
    assert "finalità" in testo
    assert "\\u00e0" not in testo


# --- HTML -----------------------------------------------------------------------


def test_html_contiene_le_sezioni_e_le_note() -> None:
    html = render_html(_report())
    assert "<h2>Analisi finanziaria</h2>" in html
    assert 'class="nota"' in html
    assert 'class="avviso"' in html
    assert "ENSC" in html


def test_html_effettua_l_escaping() -> None:
    """I testi vengono da un LLM e da titoli di stampa: possono contenere markup."""
    report = _report(
        sections=ReportSections(
            pipeline_and_clinical_results="<script>alert('x')</script>",
            catalyst_analysis="a & b",
            operational_strategy="normale",
        )
    )
    html = render_html(report)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "a &amp; b" in html


def test_html_in_inglese() -> None:
    html = render_html(_report(language="en"))
    assert "<h2>Financial analysis</h2>" in html


# --- Salvataggio su file --------------------------------------------------------


@pytest.mark.parametrize("estensione", [".md", ".json", ".html"])
def test_save_report_scrive_il_formato_dedotto(tmp_path: Path, estensione: str) -> None:
    destinazione = tmp_path / f"report{estensione}"
    risultato = save_report(_report(), destinazione)

    assert risultato == destinazione
    assert destinazione.read_text(encoding="utf-8")


def test_save_report_crea_le_cartelle_mancanti(tmp_path: Path) -> None:
    destinazione = tmp_path / "sotto" / "cartella" / "report.md"
    save_report(_report(), destinazione)
    assert destinazione.exists()


def test_save_report_rifiuta_le_estensioni_sconosciute(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non supportata"):
        save_report(_report(), tmp_path / "report.docx")


def test_save_report_genera_un_pdf_reale(tmp_path: Path) -> None:
    destinazione = tmp_path / "report.pdf"
    save_report(_report(), destinazione)

    contenuto = destinazione.read_bytes()
    assert contenuto.startswith(b"%PDF")
    assert len(contenuto) > 5_000


# --- Coerenza delle traduzioni --------------------------------------------------


def test_le_due_lingue_hanno_le_stesse_chiavi() -> None:
    """Una chiave presente solo in una lingua produrrebbe testo non tradotto."""
    assert set(LABELS["it"]) == set(LABELS["en"])
    assert set(EXPLANATIONS["it"]) == set(EXPLANATIONS["en"])


# --- Localizzazione dei testi generati dal codice ---------------------------------


def test_ogni_messaggio_esiste_in_entrambe_le_lingue() -> None:
    """Una traduzione dimenticata comparirebbe nel report nella lingua sbagliata."""
    from biocatalyst.i18n import MESSAGES

    mancanti = [k for k, v in MESSAGES.items() if set(v) != {"en", "it"}]
    assert mancanti == []


def test_i_segnaposto_di_formattazione_coincidono_fra_le_lingue() -> None:
    """Un segnaposto presente solo in una lingua farebbe fallire .format()."""
    import re

    from biocatalyst.i18n import MESSAGES

    for chiave, voci in MESSAGES.items():
        campi = {lingua: set(re.findall(r"\{(\w+)", testo)) for lingua, testo in voci.items()}
        assert campi["en"] == campi["it"], f"segnaposto diversi in '{chiave}': {campi}"


def test_le_note_delle_metriche_seguono_la_lingua() -> None:
    from biocatalyst.analysis import compute_financial_metrics

    _, note_en = compute_financial_metrics([], language="en")
    _, note_it = compute_financial_metrics([], language="it")

    assert any("cash not available" in n for n in note_en)
    assert any("cassa non disponibile" in n for n in note_it)
    # Nessun residuo dell'altra lingua.
    assert not any("cassa" in n for n in note_en)


def test_gli_avvisi_seguono_la_lingua() -> None:
    avviso_en = check_analyst_target(8.25, 0.403, "en")
    avviso_it = check_analyst_target(8.25, 0.403, "it")

    assert avviso_en is not None and "times the current price" in avviso_en
    assert avviso_it is not None and "volte il prezzo" in avviso_it


def test_la_chiave_sconosciuta_non_solleva() -> None:
    """Un testo grezzo in pagina è meno grave di un report non generato."""
    from biocatalyst.i18n import t

    assert t("en", "chiave.inesistente") == "chiave.inesistente"


# --- Storico dei rinvii e popolazione trattata ------------------------------


def _storia() -> TrialScheduleHistory:
    """Lo storico reale di REGAL (NCT04229979), verificato sul registro."""
    return TrialScheduleHistory(
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


@pytest.mark.parametrize("language", ["it", "en"])
def test_markdown_mostra_lo_storico_dei_rinvii(language: ReportLanguage) -> None:
    md = render_markdown(_report(language=language, schedule_history=_storia()))

    assert "NCT04229979" in md
    assert "2021-12-01 → 2024-12-01" in md
    assert "2024-12-01 → 2025-12-01" in md
    # Il numero di rinvii e i 48 mesi di slittamento sono il punto della sezione.
    assert LABELS[language]["times_postponed"] in md
    assert "48" in md
    assert EXPLANATIONS[language]["schedule_history"][:40] in md


def test_markdown_senza_storico_non_stampa_la_sezione() -> None:
    md = render_markdown(_report(schedule_history=None))
    assert LABELS["it"]["schedule_history"] not in md


def test_html_mostra_lo_storico_dei_rinvii() -> None:
    html = render_html(_report(language="en", schedule_history=_storia()))
    assert "NCT04229979" in html
    assert "2021-12-01" in html and "2025-12-01" in html
    assert LABELS["en"]["times_postponed"] in html


def test_popolazione_trattata_accanto_al_prezzo_verificato() -> None:
    """Il conteggio dei beneficiari è un riscontro misurato sulla prevalenza."""
    tam = TAMEstimate(
        indication="AML",
        prevalence_estimate="circa 20.000 pazienti l'anno",
        pricing_comparable="Onureg",
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
    md = render_markdown(_report(language="en", tam=tam))

    assert "1,842" in md
    assert LABELS["en"]["treated_population"] in md
    assert EXPLANATIONS["en"]["treated_population"][:40] in md


# --- Tasso storico di riferimento -------------------------------------------


def _base_rate() -> PhaseBaseRate:
    return PhaseBaseRate(
        phase="PHASE3",
        area="hematology",
        transition_pct=57.8,
        approval_pct=23.9,
        source="BIO, Informa Pharma Intelligence & QLS",
        data_through_year=2020,
    )


@pytest.mark.parametrize("language", ["it", "en"])
def test_markdown_mostra_il_tasso_storico(language: ReportLanguage) -> None:
    md = render_markdown(_report(language=language, base_rate=_base_rate()))

    assert "58%" in md
    assert "24%" in md
    assert LABELS[language]["base_rate"] in md
    # La fonte e l'anno devono comparire: non è un dato da API.
    assert "BIO" in md
    assert "2020" in md


def test_la_spiegazione_del_tasso_avverte_che_non_e_la_probabilita_del_titolo() -> None:
    """Confondere i due significati è l'errore di lettura più facile."""
    assert "not the probability that the stock goes up" in EXPLANATIONS["en"]["base_rate"]
    assert "non è la probabilità che il titolo" in EXPLANATIONS["it"]["base_rate"]


def test_markdown_senza_tasso_storico_non_stampa_la_sezione() -> None:
    assert LABELS["it"]["base_rate"] not in render_markdown(_report(base_rate=None))
