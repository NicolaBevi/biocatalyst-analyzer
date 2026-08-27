"""Streamlit interface.

Two Streamlit Community Cloud constraints shaped this page:

1. **~60s timeout on outbound HTTP responses.** The writer agent takes more
   than twice that. Moving the call to a thread does not help: the HTTP
   response is just as long. Streaming does, by keeping bytes flowing
   (measured: longest gap between chunks 0.7s). Streaming is on by default
   via `LLM_USE_STREAMING`.
2. **The pipeline takes minutes.** Running it inside the render loop would
   block the interface, so it runs in a separate thread and the page reads
   shared state.

The interface is in English, matching the default report language. The report
itself can still be produced in Italian.
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
from biocatalyst.analysis.screening import RISK_APPETITES
from biocatalyst.config import LLMProviderName, Settings, get_settings
from biocatalyst.data.factory import build_data_providers
from biocatalyst.data.universe import DEFAULT_SIC_CODES, PHARMA_SIC_CODE
from biocatalyst.models.report import Report
from biocatalyst.models.screening import ScreenCriteria, ScreenResult
from biocatalyst.report import DEFAULT_REPORTS_DIR, render_json, render_markdown, save_all_formats
from biocatalyst.report.pdf import PDFRenderingError, render_pdf
from biocatalyst.screening import (
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_MAX_UNIVERSE,
)
from biocatalyst.screening import (
    screen as run_screen,
)

st.set_page_config(page_title="BioCatalyst Analyzer", page_icon="🧬", layout="wide")

TOTAL_AGENTS = 4


@dataclass
class Job:
    """State shared between a worker thread and the render loop."""

    label: str
    stage: str = "starting"
    step: int = 0
    total: int = TOTAL_AGENTS
    result: Any = None
    error: str | None = None
    started: datetime = field(default_factory=lambda: datetime.now(UTC))
    done: bool = False


def _run_in_thread(job: Job, work: Any) -> Job:
    """Starts the work in a daemon thread and returns the observable state."""

    def worker() -> None:
        try:
            job.result = work(job)
        except Exception as exc:  # the UI must show the error, not die
            job.error = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()  # the traceback stays in the server logs
        finally:
            job.done = True

    threading.Thread(target=worker, daemon=True).start()
    return job


def _start_analysis(ticker: str, language: str, settings: Settings) -> Job:
    job = Job(label=ticker.upper())

    def work(current: Job) -> Report:
        providers = build_data_providers(settings)
        try:

            def progress(step: int, total: int, name: str) -> None:
                current.step, current.total, current.stage = step, total, name

            return run_analysis(
                ticker,
                providers=providers,
                settings=settings,
                on_progress=progress,
                language=language,  # type: ignore[arg-type]
            )
        finally:
            providers.close()

    return _run_in_thread(job, work)


def _start_screen(criteria: ScreenCriteria, settings: Settings, options: dict[str, Any]) -> Job:
    job = Job(label="screening", total=100)

    def work(current: Job) -> ScreenResult:
        def progress(phase: str, done: int, total: int) -> None:
            current.stage = phase
            current.step, current.total = done, max(total, 1)

        return run_screen(
            criteria=criteria,
            settings=settings,
            language=settings.report_language,
            on_progress=progress,
            **options,
        )

    return _run_in_thread(job, work)


def _settings_with_overrides(language: str) -> Settings:
    """Configuration with the sidebar overrides applied."""
    settings = get_settings()
    updates: dict[str, Any] = {"report_language": language}

    chosen = st.session_state.get("provider")
    if chosen and chosen != "(from .env)":
        updates.update(
            default_provider=LLMProviderName(chosen),
            default_model=None,
            agent_analyst_provider=None,
            agent_analyst_model=None,
            agent_news_provider=None,
            agent_news_model=None,
            agent_writer_provider=None,
            agent_writer_model=None,
        )
    return settings.model_copy(update=updates)


def _sidebar() -> str:
    with st.sidebar:
        st.title("🧬 BioCatalyst")
        st.caption(f"version {__version__}")

        language = st.radio(
            "Report language",
            options=["en", "it"],
            format_func=lambda v: {"en": "English", "it": "Italiano"}[v],
            horizontal=True,
        )

        with st.expander("Model configuration"):
            st.selectbox(
                "LLM provider",
                options=["(from .env)", *[p.value for p in LLMProviderName]],
                key="provider",
                help="Changing the provider clears the per-agent models set in .env.",
            )
            try:
                settings = get_settings()
                default = settings.default_model or "—"
                st.caption(
                    f"Analyst: `{settings.agent_analyst_model or default}`  \n"
                    f"News: `{settings.agent_news_model or default}`  \n"
                    f"Writer: `{settings.agent_writer_model or default}`  \n"
                    f"Streaming: {'on' if settings.llm_use_streaming else 'off'}"
                )
            except Exception as exc:  # incomplete configuration
                st.error(f"Invalid configuration: {exc}")

        st.divider()
        st.caption(
            "A full analysis takes a few minutes: four agents in sequence, two of "
            "which use a reasoning model."
        )
    return language


def _progress(job: Job) -> None:
    elapsed = (datetime.now(UTC) - job.started).total_seconds()
    st.progress(
        min(job.step / max(job.total, 1), 1.0),
        text=f"({job.step}/{job.total}) {job.stage} — {elapsed:.0f}s",
    )


@st.fragment(run_every=2)
def _live_progress(job: Job) -> None:
    """Redraws itself every 2 seconds while the worker thread runs.

    Refreshing only this block avoids rebuilding the sidebar on every tick;
    when the thread finishes a full rerun replaces the bar with the result.
    """
    _progress(job)
    if job.done:
        st.rerun(scope="app")


# --- Analyse tab ------------------------------------------------------------------


def _analyse_tab(language: str) -> None:
    col_input, col_button = st.columns([3, 1])
    ticker = col_input.text_input(
        "Ticker", value="ENSC", help="e.g. ENSC, SLS, MRNA", label_visibility="collapsed"
    ).strip()

    job: Job | None = st.session_state.get("analysis_job")
    running = job is not None and not job.done

    if col_button.button(
        "Analyse", type="primary", disabled=running or not ticker, width="stretch"
    ):
        try:
            settings = _settings_with_overrides(language)
        except Exception as exc:
            st.error(f"Invalid configuration: {exc}")
            return
        st.session_state["analysis_job"] = _start_analysis(ticker, language, settings)
        st.rerun()

    if job is None:
        st.info(
            "Enter a ticker and start the analysis. The system pulls data from SEC "
            "EDGAR, ClinicalTrials.gov, openFDA, yfinance and Finnhub, then writes a "
            "due diligence report."
        )
        return

    if not job.done:
        _live_progress(job)
        return

    if job.error is not None:
        st.error(f"Analysis of {job.label} failed.\n\n{job.error}")
        return

    if isinstance(job.result, Report):
        _show_report(job.result)


def _show_report(report: Report) -> None:
    colour = {"BUY": "green", "HOLD": "orange", "SELL": "red"}[report.rating]
    st.markdown(
        f"## {report.company_name or report.ticker} "
        f"(:{colour}[{report.rating}]) — ${report.current_price:,.4f}"
    )

    for warning in report.source_quality.warnings:
        st.warning(warning, icon="⚠️")

    m = report.financial_metrics
    cols = st.columns(4)
    cols[0].metric(
        "Cash runway",
        f"{m.cash_runway_months:,.1f} months" if m.cash_runway_months is not None else "—",
    )
    cols[1].metric(
        "Quarterly burn",
        f"${m.quarterly_burn_rate_usd:,.0f}" if m.quarterly_burn_rate_usd is not None else "—",
    )
    cols[2].metric(
        "Dilution risk",
        f"{m.dilution_risk_score:,.0f}/100" if m.dilution_risk_score is not None else "—",
    )
    row = report.expected_value.rows[0]
    cols[3].metric(
        f"Expected value on ${row.investment_usd:,.0f}",
        f"${row.expected_value_usd:,.2f}",
        delta=f"{row.expected_roi_pct:+.1f}%",
    )

    _export_buttons(report)
    st.divider()
    st.markdown(render_markdown(report))


def _export_buttons(report: Report) -> None:
    cols = st.columns(4)
    base = f"{report.ticker}_{report.report_date.isoformat()}_{report.language}"

    cols[0].download_button(
        "⬇ Markdown", render_markdown(report), f"{base}.md", "text/markdown", width="stretch"
    )
    cols[1].download_button(
        "⬇ JSON", render_json(report), f"{base}.json", "application/json", width="stretch"
    )
    try:
        path = render_pdf(report, Path(st.session_state["pdf_dir"]) / f"{base}.pdf")
        cols[2].download_button(
            "⬇ PDF", path.read_bytes(), f"{base}.pdf", "application/pdf", width="stretch"
        )
    except PDFRenderingError as exc:
        cols[2].button("⬇ PDF", disabled=True, help=str(exc), width="stretch")

    if cols[3].button("💾 Save to reports/", width="stretch"):
        written = save_all_formats(report, DEFAULT_REPORTS_DIR)
        st.success(f"Saved {len(written)} files to `{DEFAULT_REPORTS_DIR / report.ticker}/`")


# --- Screen tab -------------------------------------------------------------------


def _screen_tab(language: str) -> None:
    st.caption(
        "Screens NASDAQ/NYSE biotechs built from SEC SIC codes. Price, catalysts and "
        "cash are filtered on free data; the language model runs once, only on the "
        "finalists."
    )

    col1, col2, col3 = st.columns(3)
    max_price = col1.number_input("Max price ($)", value=10.0, min_value=0.5, step=1.0)
    max_cap = col2.number_input("Max market cap ($M)", value=500.0, min_value=10.0, step=50.0)
    window = col3.number_input("Catalyst window (months)", value=6, min_value=1, max_value=36)

    col4, col5, col6 = st.columns(3)
    risk = col4.selectbox(
        "Risk profile",
        options=list(RISK_APPETITES),
        index=list(RISK_APPETITES).index("bilanciato"),
        help=(
            "Speculative ignores cash in the ranking: dilution reduces the upside but "
            "does not remove it, and discounted names are where asymmetric bets live. "
            "The financing risk is flagged on every candidate regardless."
        ),
    )
    limit = col5.number_input("Candidates", value=DEFAULT_MAX_CANDIDATES, min_value=1, max_value=20)
    universe = col6.number_input(
        "Stocks to examine", value=DEFAULT_MAX_UNIVERSE, min_value=10, max_value=1000, step=10
    )

    include_pharma = st.checkbox(
        "Include SIC 2834 (pharmaceutical preparations)",
        help="Adds over 1,500 companies, mostly large pharma. Much slower.",
    )

    job: Job | None = st.session_state.get("screen_job")
    running = job is not None and not job.done

    if st.button("Run screen", type="primary", disabled=running, width="stretch"):
        try:
            settings = _settings_with_overrides(language)
        except Exception as exc:
            st.error(f"Invalid configuration: {exc}")
            return
        criteria = ScreenCriteria(
            max_price_usd=max_price,
            max_price_usd_exceptional=max_price * 1.5,
            market_cap_max_usd=max_cap * 1_000_000,
            market_cap_max_usd_exceptional=max_cap * 4_000_000,
            catalyst_window_months=int(window),
        )
        st.session_state["screen_job"] = _start_screen(
            criteria,
            settings,
            {
                "sic_codes": (*DEFAULT_SIC_CODES, PHARMA_SIC_CODE)
                if include_pharma
                else DEFAULT_SIC_CODES,
                "max_candidates": int(limit),
                "max_universe": int(universe),
                "appetite": RISK_APPETITES[risk],
            },
        )
        st.rerun()

    if job is None:
        return

    if not job.done:
        _live_progress(job)
        return

    if job.error is not None:
        st.error(f"Screening failed.\n\n{job.error}")
        return

    if isinstance(job.result, ScreenResult):
        _show_screen(job.result)


def _show_screen(result: ScreenResult) -> None:
    if not result.candidates:
        st.warning(
            "No stock meets the criteria. Try widening the catalyst window or the price threshold."
        )
        return

    st.success(f"{len(result.candidates)} candidates found")
    st.dataframe(
        [
            {
                "Ticker": c.ticker,
                "Price": f"${c.price:,.2f}",
                "Market cap": f"${c.market_cap_usd / 1_000_000:,.0f}M",
                "Catalyst": str(c.catalyst.expected_date or c.catalyst.expected_date_window),
                "Runway": f"{c.cash_runway_months:,.1f}m"
                if c.cash_runway_months is not None
                else "—",
                "Score": f"{c.attractiveness_score:,.0f}",
                "Cash": "needs refinancing" if c.financing_risk else "sufficient",
            }
            for c in result.candidates
        ],
        width="stretch",
        hide_index=True,
    )

    for c in result.candidates:
        with st.expander(f"{c.ticker} — {c.company_name}"):
            if c.exceptional:
                st.info("Above the ordinary thresholds, included as an exception.", icon="ℹ️")
            if c.financing_risk:
                st.warning(c.financing_risk, icon="⚠️")
            st.write(c.rationale)
            for risk_item in c.key_risks:
                st.markdown(f"- **Risk:** {risk_item}")
            st.caption(f"{c.main_drug} · {c.indication} · {c.catalyst.source}")


def main() -> None:
    if "pdf_dir" not in st.session_state:
        import tempfile

        st.session_state["pdf_dir"] = tempfile.mkdtemp(prefix="biocatalyst-")

    language = _sidebar()
    analyse, screen_tab = st.tabs(["Analyse a ticker", "Screen for opportunities"])
    with analyse:
        _analyse_tab(language)
    with screen_tab:
        _screen_tab(language)


main()
