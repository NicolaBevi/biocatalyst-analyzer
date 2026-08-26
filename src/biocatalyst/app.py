"""Interfaccia Streamlit.

Due vincoli di Streamlit Community Cloud hanno guidato il progetto di questa
pagina:

1. **Timeout di ~60s sulle risposte HTTP in uscita.** L'agente scrittore
   impiega più del doppio. Non si risolve spostando la chiamata in un thread:
   la risposta HTTP resta comunque lunga. Si risolve con lo streaming, che
   tiene i byte in movimento (verificato: intervallo massimo fra chunk 0,7s).
   Lo streaming è attivo per default via `LLM_USE_STREAMING`.
2. **La pipeline dura minuti.** Eseguirla dentro il ciclo di rendering
   bloccherebbe l'interfaccia: gira in un thread separato e la pagina si
   aggiorna leggendo lo stato condiviso.
"""

from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import streamlit as st

from biocatalyst import __version__
from biocatalyst.agents import analyze as run_analysis
from biocatalyst.config import LLMProviderName, Settings, get_settings
from biocatalyst.data.factory import build_data_providers
from biocatalyst.models.report import Report
from biocatalyst.report import DEFAULT_REPORTS_DIR, render_json, render_markdown, save_all_formats
from biocatalyst.report.pdf import PDFRenderingError, render_pdf

st.set_page_config(page_title="BioCatalyst Analyzer", page_icon="🧬", layout="wide")

AGENTI_TOTALI = 4


@dataclass
class StatoAnalisi:
    """Stato condiviso fra il thread di lavoro e il ciclo di rendering."""

    ticker: str
    lingua: str
    fase: str = "in attesa"
    indice: int = 0
    report: Report | None = None
    errore: str | None = None
    avviata: datetime = field(default_factory=lambda: datetime.now(UTC))
    conclusa: bool = False


def _avvia_analisi(ticker: str, lingua: str, settings: Settings) -> StatoAnalisi:
    """Lancia la pipeline in un thread e restituisce subito lo stato osservabile."""
    stato = StatoAnalisi(ticker=ticker.upper(), lingua=lingua)

    def lavora() -> None:
        providers = build_data_providers(settings)
        try:

            def avanzamento(indice: int, totale: int, nome: str) -> None:
                stato.indice = indice
                stato.fase = nome

            stato.report = run_analysis(
                ticker,
                providers=providers,
                settings=settings,
                on_progress=avanzamento,
                language=lingua,  # type: ignore[arg-type]
            )
        except Exception as exc:  # la UI deve mostrare l'errore, non morire
            stato.errore = f"{type(exc).__name__}: {exc}"
            # Il traceback resta nei log del server, non finisce in pagina.
            traceback.print_exc()
        finally:
            providers.close()
            stato.conclusa = True

    threading.Thread(target=lavora, daemon=True).start()
    return stato


def _impostazioni_correnti() -> Settings:
    """Configurazione con gli override scelti nella barra laterale."""
    settings = get_settings()
    updates: dict[str, Any] = {}

    provider_scelto = st.session_state.get("provider")
    if provider_scelto and provider_scelto != "(dal file .env)":
        updates.update(
            default_provider=LLMProviderName(provider_scelto),
            default_model=None,
            agent_analyst_provider=None,
            agent_analyst_model=None,
            agent_news_provider=None,
            agent_news_model=None,
            agent_writer_provider=None,
            agent_writer_model=None,
        )
    return settings.model_copy(update=updates) if updates else settings


def _barra_laterale() -> tuple[str, str]:
    with st.sidebar:
        st.title("🧬 BioCatalyst")
        st.caption(f"versione {__version__}")

        ticker = st.text_input("Ticker", value="ENSC", help="Es. ENSC, MRNA, VRTX").strip()
        lingua = st.radio(
            "Lingua del report",
            options=["it", "en"],
            format_func=lambda v: {"it": "Italiano", "en": "English"}[v],
            horizontal=True,
        )

        with st.expander("Configurazione modello"):
            st.selectbox(
                "Provider LLM",
                options=["(dal file .env)", *[p.value for p in LLMProviderName]],
                key="provider",
                help="Cambiando provider si azzerano i modelli per-agente del .env.",
            )
            try:
                settings = get_settings()
                default = settings.default_model or "—"
                analista = settings.agent_analyst_model or default
                notizie = settings.agent_news_model or default
                scrittore = settings.agent_writer_model or default
                streaming = "attivo" if settings.llm_use_streaming else "disattivo"
                st.caption(
                    f"Analista: `{analista}`  \n"
                    f"Notizie: `{notizie}`  \n"
                    f"Report: `{scrittore}`  \n"
                    f"Streaming: {streaming}"
                )
            except Exception as exc:  # configurazione incompleta
                st.error(f"Configurazione non valida: {exc}")

        st.divider()
        st.caption(
            "L'analisi richiede alcuni minuti: quattro agenti in sequenza, "
            "di cui due usano un modello di ragionamento."
        )
    return ticker, lingua


def _mostra_avanzamento(stato: StatoAnalisi) -> None:
    trascorso = (datetime.now(UTC) - stato.avviata).total_seconds()
    st.progress(
        min(stato.indice / AGENTI_TOTALI, 1.0),
        text=f"({stato.indice}/{AGENTI_TOTALI}) {stato.fase} — {trascorso:.0f}s",
    )


@st.fragment(run_every=2)
def _avanzamento_che_si_aggiorna(stato: StatoAnalisi) -> None:
    """Frammento che si ridisegna da solo ogni 2 secondi.

    Aggiornare solo questo blocco invece dell'intera pagina evita di
    ricostruire la barra laterale a ogni battito. Quando il thread ha finito
    serve però un ricalcolo completo, per sostituire la barra col report.
    """
    _mostra_avanzamento(stato)
    if stato.conclusa:
        st.rerun(scope="app")


def _mostra_report(report: Report) -> None:
    colore = {"BUY": "green", "HOLD": "orange", "SELL": "red"}[report.rating]
    st.markdown(
        f"## {report.company_name or report.ticker} "
        f"(:{colore}[{report.rating}]) — ${report.current_price:,.4f}"
    )

    if report.source_quality.warnings:
        for avviso in report.source_quality.warnings:
            st.warning(avviso, icon="⚠️")

    m = report.financial_metrics
    colonne = st.columns(4)
    colonne[0].metric(
        "Autonomia di cassa",
        f"{m.cash_runway_months:,.1f} mesi" if m.cash_runway_months is not None else "—",
    )
    colonne[1].metric(
        "Burn trimestrale",
        f"${m.quarterly_burn_rate_usd:,.0f}" if m.quarterly_burn_rate_usd is not None else "—",
    )
    colonne[2].metric(
        "Rischio diluizione",
        f"{m.dilution_risk_score:,.0f}/100" if m.dilution_risk_score is not None else "—",
    )
    riga = report.expected_value.rows[0]
    colonne[3].metric(
        f"Valore atteso su ${riga.investment_usd:,.0f}",
        f"${riga.expected_value_usd:,.2f}",
        delta=f"{riga.expected_roi_pct:+.1f}%",
    )

    _pulsanti_esportazione(report)
    st.divider()
    st.markdown(render_markdown(report))


def _pulsanti_esportazione(report: Report) -> None:
    colonne = st.columns(4)
    base = f"{report.ticker}_{report.report_date.isoformat()}_{report.language}"

    colonne[0].download_button(
        "⬇ Markdown", render_markdown(report), f"{base}.md", "text/markdown", width="stretch"
    )
    colonne[1].download_button(
        "⬇ JSON", render_json(report), f"{base}.json", "application/json", width="stretch"
    )

    try:
        percorso = render_pdf(report, Path(st.session_state["cartella_pdf"]) / f"{base}.pdf")
        colonne[2].download_button(
            "⬇ PDF",
            percorso.read_bytes(),
            f"{base}.pdf",
            "application/pdf",
            width="stretch",
        )
    except PDFRenderingError as exc:
        colonne[2].button("⬇ PDF", disabled=True, help=str(exc), width="stretch")

    if colonne[3].button("💾 Salva in reports/", width="stretch"):
        scritti = save_all_formats(report, DEFAULT_REPORTS_DIR)
        st.success(f"Salvati {len(scritti)} file in `{DEFAULT_REPORTS_DIR / report.ticker}/`")


def main() -> None:
    if "cartella_pdf" not in st.session_state:
        import tempfile

        st.session_state["cartella_pdf"] = tempfile.mkdtemp(prefix="biocatalyst-")

    ticker, lingua = _barra_laterale()
    stato: StatoAnalisi | None = st.session_state.get("analisi")

    in_corso = stato is not None and not stato.conclusa
    if st.button("Analizza", type="primary", disabled=in_corso or not ticker):
        try:
            settings = _impostazioni_correnti()
        except Exception as exc:
            st.error(f"Configurazione non valida: {exc}")
            return
        st.session_state["analisi"] = _avvia_analisi(ticker, lingua, settings)
        st.rerun()

    if stato is None:
        st.info(
            "Inserisci un ticker e avvia l'analisi. "
            "Il sistema raccoglie dati da SEC EDGAR, ClinicalTrials.gov, openFDA, "
            "yfinance e Finnhub, poi produce un report di due diligence."
        )
        return

    if not stato.conclusa:
        _avanzamento_che_si_aggiorna(stato)
        return

    if stato.errore is not None:
        st.error(f"Analisi di {stato.ticker} non riuscita.\n\n{stato.errore}")
        return

    if stato.report is not None:
        _mostra_report(stato.report)


main()
