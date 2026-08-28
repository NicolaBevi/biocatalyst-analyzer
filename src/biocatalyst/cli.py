"""Interfaccia a riga di comando.

Gli errori previsti (fonte dati irraggiungibile, chiave mancante, ticker
inesistente) vengono mostrati come messaggi leggibili con codice di uscita 1,
non come traceback: chi usa la CLI non deve leggere uno stack Python per
capire che manca una API key.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from biocatalyst import __version__
from biocatalyst.agents import AgentError
from biocatalyst.agents import analyze as run_analysis
from biocatalyst.analysis.screening import RISK_APPETITES
from biocatalyst.config import LLMProviderName, Settings, get_settings
from biocatalyst.data.base import DataProviderError
from biocatalyst.data.factory import build_data_providers
from biocatalyst.data.universe import DEFAULT_SIC_CODES, PHARMA_SIC_CODE
from biocatalyst.llm.base import LLMError
from biocatalyst.log import configure_logging
from biocatalyst.models.report import Report
from biocatalyst.models.screening import ScreenCriteria, ScreenResult
from biocatalyst.report import (
    DEFAULT_FORMATS,
    DEFAULT_REPORTS_DIR,
    save_all_formats,
    save_report,
)
from biocatalyst.screening import (
    DEFAULT_MAX_CANDIDATES,
    DEFAULT_MAX_UNIVERSE,
)
from biocatalyst.screening import (
    screen as run_screen,
)

app = typer.Typer(
    name="biocatalyst",
    help="Due diligence reports on NASDAQ and NYSE biotech and pharma companies.",
    no_args_is_help=True,
)
console = Console()
error_console = Console(stderr=True)


def _settings_for(provider: str | None, language: str | None) -> Settings:
    """Applica gli override della riga di comando alla configurazione del .env.

    Cambiando provider si azzerano anche gli override per-agente: un nome di
    modello valido per un provider non lo è per un altro, e tenerli produrrebbe
    un errore poco comprensibile alla prima chiamata.
    """
    settings = get_settings()
    updates: dict[str, object] = {}

    if provider is not None:
        try:
            scelto = LLMProviderName(provider.lower())
        except ValueError:
            validi = ", ".join(p.value for p in LLMProviderName)
            raise typer.BadParameter(
                f"provider sconosciuto '{provider}'. Validi: {validi}"
            ) from None
        updates.update(
            default_provider=scelto,
            default_model=None,
            agent_analyst_provider=None,
            agent_analyst_model=None,
            agent_news_provider=None,
            agent_news_model=None,
            agent_writer_provider=None,
            agent_writer_model=None,
        )

    if language is not None:
        if language not in ("it", "en"):
            raise typer.BadParameter("lingua non valida: usa 'it' oppure 'en'")
        updates["report_language"] = language

    return settings.model_copy(update=updates) if updates else settings


def _configura_log(settings: Settings, verbose: bool) -> None:
    """Log silenziosi per default: la CLI mostra già il proprio avanzamento.

    Con `--verbose` si passa al livello configurato nel .env, utile quando
    serve capire quale fonte sta rallentando o fallendo.
    """
    configure_logging(settings.log_level if verbose else "WARNING")


def _parse_formats(value: str) -> tuple[str, ...]:
    formats = tuple(f".{f.strip().lstrip('.').lower()}" for f in value.split(",") if f.strip())
    if not formats:
        raise typer.BadParameter("indica almeno un formato")
    non_validi = [f for f in formats if f not in (".md", ".json", ".html", ".pdf")]
    if non_validi:
        raise typer.BadParameter(f"formati non supportati: {', '.join(non_validi)}")
    return formats


def _esegui(ticker: str, settings: Settings, providers: object, mostra_avanzamento: bool) -> Report:
    def avanzamento(indice: int, totale: int, nome: str) -> None:
        if mostra_avanzamento:
            console.print(f"  [dim]({indice}/{totale})[/dim] {nome}…")

    return run_analysis(
        ticker,
        providers=providers,  # type: ignore[arg-type]
        settings=settings,
        on_progress=avanzamento,
        language=settings.report_language,
    )


def _riassunto(report: Report) -> Table:
    colore = {"BUY": "green", "HOLD": "yellow", "SELL": "red"}[report.rating]
    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_row("Ticker", f"[bold]{report.ticker}[/bold]")
    table.add_row("Price", f"${report.current_price:,.4f}")
    table.add_row("Rating", f"[{colore} bold]{report.rating}[/{colore} bold]")
    m = report.financial_metrics
    if m.cash_runway_months is not None:
        table.add_row("Cash runway", f"{m.cash_runway_months:,.1f} months")
    if m.dilution_risk_score is not None:
        table.add_row("Dilution risk", f"{m.dilution_risk_score:,.0f}/100")
    roi = report.expected_value.rows[0]
    table.add_row(
        f"Expected value on ${roi.investment_usd:,.0f}",
        f"${roi.expected_value_usd:,.2f} ({roi.expected_roi_pct:+.1f}%)",
    )
    table.add_row("Catalyst", report.main_catalyst[:70])
    return table


@app.command()
def version() -> None:
    """Show the installed version."""
    console.print(f"biocatalyst-analyzer {__version__}")


@app.command()
def analyze(
    ticker: Annotated[str, typer.Argument(help="Ticker to analyse, e.g. ENSC")],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Single output file. If omitted, writes to reports/<TICKER>/.",
        ),
    ] = None,
    formats: Annotated[
        str,
        typer.Option("--formats", "-f", help="Comma-separated formats: md,json,html,pdf"),
    ] = ",".join(f.lstrip(".") for f in DEFAULT_FORMATS),
    language: Annotated[
        str | None, typer.Option("--language", "-l", help="Report language: en or it")
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", "-p", help="Force one LLM provider for every agent"),
    ] = None,
    no_cache: Annotated[
        bool,
        typer.Option(
            "--no-cache",
            help=(
                "Bypass the cache: re-query every source and ask the models again. "
                "Without it, re-running the same analysis reuses the stored answers "
                "and reproduces the same report."
            ),
        ),
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show detailed agent logs")
    ] = False,
) -> None:
    """Full due diligence on a single ticker."""
    # Ogni parametro va validato PRIMA di costruire i provider: un formato
    # sbagliato scoperto a valle costerebbe un'analisi completa a pagamento.
    formati = _parse_formats(formats) if output is None else ()
    settings = _settings_for(provider, language)
    _configura_log(settings, verbose)

    providers = build_data_providers(settings, cache_enabled=not no_cache)
    try:
        console.print(
            f"\n[bold]Analysing {ticker.upper()}[/bold] (language: {settings.report_language})"
        )
        report = _esegui(ticker, settings, providers, mostra_avanzamento=True)

        if output is not None:
            scritti = [save_report(report, output)]
        else:
            scritti = save_all_formats(report, DEFAULT_REPORTS_DIR, formati)

        console.print()
        console.print(_riassunto(report))
        console.print("\n[bold]Files written:[/bold]")
        for percorso in scritti:
            console.print(f"  {percorso}")

        if report.source_quality.warnings:
            console.print(
                f"\n[yellow]⚠ {len(report.source_quality.warnings)} data quality warnings[/yellow]"
            )
            for avviso in report.source_quality.warnings:
                console.print(f"  [yellow]•[/yellow] {avviso}")
    except (DataProviderError, LLMError, AgentError) as exc:
        error_console.print(f"\n[red]Analysis failed:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        providers.close()


@app.command()
def compare(
    tickers: Annotated[list[str], typer.Argument(help="Two or more tickers to compare")],
    language: Annotated[
        str | None, typer.Option("--language", "-l", help="Report language: en or it")
    ] = None,
    provider: Annotated[
        str | None, typer.Option("--provider", "-p", help="Force one LLM provider")
    ] = None,
    save: Annotated[
        bool, typer.Option("--save/--no-save", help="Also save the full reports")
    ] = True,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Show detailed agent logs")
    ] = False,
) -> None:
    """Confronta più ticker affiancandone le metriche principali.

    Un ticker che fallisce non interrompe il confronto: viene segnalato e si
    prosegue con gli altri.
    """
    if len(tickers) < 2:
        raise typer.BadParameter("servono almeno due ticker da confrontare")

    settings = _settings_for(provider, language)
    _configura_log(settings, verbose)

    providers = build_data_providers(settings)
    riusciti: list[Report] = []
    falliti: list[tuple[str, str]] = []

    try:
        for ticker in tickers:
            console.print(f"\n[bold]{ticker.upper()}[/bold]")
            try:
                report = _esegui(ticker, settings, providers, mostra_avanzamento=True)
                riusciti.append(report)
                if save:
                    save_all_formats(report)
            except (DataProviderError, LLMError, AgentError) as exc:
                console.print(f"  [red]failed:[/red] {exc}")
                falliti.append((ticker.upper(), str(exc)))
    finally:
        providers.close()

    if not riusciti:
        error_console.print("\n[red]No ticker could be analysed.[/red]")
        raise typer.Exit(code=1)

    console.print()
    console.print(_tabella_confronto(riusciti))
    if falliti:
        console.print(f"\n[yellow]Not analysed: {', '.join(t for t, _ in falliti)}[/yellow]")


def _tabella_confronto(reports: list[Report]) -> Table:
    table = Table(title="Comparison", header_style="bold")
    table.add_column("Ticker")
    table.add_column("Price", justify="right")
    table.add_column("Rating")
    table.add_column("Runway", justify="right")
    table.add_column("Dilution", justify="right")
    table.add_column("Squeeze", justify="right")
    table.add_column("Expected ROI", justify="right")

    # Ordinati per rendimento atteso: il confronto serve a scegliere.
    for r in sorted(reports, key=lambda x: -x.expected_value.rows[0].expected_roi_pct):
        m = r.financial_metrics
        colore = {"BUY": "green", "HOLD": "yellow", "SELL": "red"}[r.rating]
        roi = r.expected_value.rows[0].expected_roi_pct
        table.add_row(
            r.ticker,
            f"${r.current_price:,.4f}",
            f"[{colore}]{r.rating}[/{colore}]",
            f"{m.cash_runway_months:,.1f}m" if m.cash_runway_months is not None else "—",
            f"{m.dilution_risk_score:,.0f}" if m.dilution_risk_score is not None else "—",
            f"{m.short_squeeze_score:,.0f}" if m.short_squeeze_score is not None else "—",
            f"[{'green' if roi > 0 else 'red'}]{roi:+.1f}%[/]",
        )
    return table


@app.command()
def screen(
    max_price: Annotated[
        float, typer.Option("--max-price", help="Maximum share price in dollars")
    ] = 10.0,
    max_market_cap: Annotated[
        float, typer.Option("--max-market-cap", help="Maximum market capitalisation in dollars")
    ] = 500_000_000,
    catalyst_window: Annotated[
        int, typer.Option("--catalyst-window", help="Catalyst window in months")
    ] = 6,
    risk: Annotated[
        str,
        typer.Option(
            "--risk",
            help=(
                "Profilo di rischio: speculativo (ignora la cassa nell'ordinamento), "
                "bilanciato, prudente"
            ),
        ),
    ] = "bilanciato",
    min_phase: Annotated[
        str, typer.Option("--min-phase", help="Minimum phase: PHASE1, PHASE2, PHASE3")
    ] = "PHASE2",
    limit: Annotated[
        int, typer.Option("--limit", help="How many candidates to return")
    ] = DEFAULT_MAX_CANDIDATES,
    max_universe: Annotated[
        int, typer.Option("--max-universe", help="Maximum number of stocks to examine")
    ] = DEFAULT_MAX_UNIVERSE,
    include_pharma: Annotated[
        bool,
        typer.Option(
            "--include-pharma",
            help="Aggiunge il SIC 2834: oltre 1.500 società, molto più lento",
        ),
    ] = False,
    output: Annotated[
        Path | None, typer.Option("--output", "-o", help="Save the result as JSON")
    ] = None,
    language: Annotated[
        str | None, typer.Option("--language", "-l", help="Lingua delle motivazioni: it o en")
    ] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Detailed logs")] = False,
) -> None:
    """Cerca nuove opportunità fra i biotech quotati secondo criteri.

    L'universo si ricava dall'anagrafica SEC per codice SIC: non esiste uno
    screener gratuito con API stabile. I filtri sono tutti su dati gratuiti e
    il modello linguistico interviene una sola volta, sulle sole finaliste.
    """
    appetite = RISK_APPETITES.get(risk.lower())
    if appetite is None:
        raise typer.BadParameter(
            f"profilo di rischio sconosciuto '{risk}'. Validi: {', '.join(RISK_APPETITES)}"
        )
    settings = _settings_for(None, language)
    _configura_log(settings, verbose)

    criteria = ScreenCriteria(
        max_price_usd=max_price,
        max_price_usd_exceptional=max_price * 1.5,
        market_cap_max_usd=max_market_cap,
        market_cap_max_usd_exceptional=max_market_cap * 4,
        min_pipeline_phase=min_phase.upper(),
        catalyst_window_months=catalyst_window,
    )
    sic = (*DEFAULT_SIC_CODES, PHARMA_SIC_CODE) if include_pharma else DEFAULT_SIC_CODES

    console.print(
        f"\n[bold]Screening for opportunities[/bold] — price ≤ ${max_price:,.2f}, "
        f"market cap ≤ ${max_market_cap:,.0f}, catalysts within {catalyst_window} months, "
        f"{appetite.name} profile"
    )
    with console.status("[dim]building the universe…[/dim]") as stato:

        def avanzamento(fase: str, fatto: int, totale: int) -> None:
            if fase == "titoli":
                stato.update(f"[dim]examining stocks {fatto}/{totale}…[/dim]")
            elif fase == "motivazioni":
                stato.update("[dim]analysing the finalists…[/dim]")

        try:
            risultato = run_screen(
                criteria=criteria,
                settings=settings,
                sic_codes=sic,
                max_candidates=limit,
                max_universe=max_universe,
                language=settings.report_language,
                appetite=appetite,
                on_progress=avanzamento,
            )
        except (DataProviderError, LLMError) as exc:
            error_console.print(f"\n[red]Screening failed:[/red] {exc}")
            raise typer.Exit(code=1) from exc

    if not risultato.candidates:
        console.print(
            "\n[yellow]No stock meets the criteria.[/yellow] "
            "Try widening the catalyst window or the price thresholds."
        )
        raise typer.Exit(code=0)

    console.print()
    console.print(_tabella_screen(risultato))
    for candidata in risultato.candidates:
        console.print(f"\n[bold]{candidata.ticker}[/bold] — {candidata.company_name}")
        if candidata.exceptional:
            console.print(
                "  [yellow]above the ordinary thresholds, included as an exception[/yellow]"
            )
        if candidata.financing_risk:
            console.print(f"  [yellow]⚠ {candidata.financing_risk}[/yellow]")
        if candidata.rationale:
            console.print(f"  {candidata.rationale}")
        for rischio in candidata.key_risks:
            console.print(f"  [dim]risk:[/dim] {rischio}")

    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(risultato.model_dump_json(indent=2, exclude_none=False), encoding="utf-8")
        console.print(f"\n[bold]Saved:[/bold] {output}")


def _tabella_screen(risultato: ScreenResult) -> Table:
    table = Table(title=f"{len(risultato.candidates)} candidates", header_style="bold")
    table.add_column("Ticker")
    table.add_column("Price", justify="right")
    table.add_column("Mkt cap", justify="right")
    table.add_column("Catalyst")
    table.add_column("Runway", justify="right")
    table.add_column("Score", justify="right")
    table.add_column("Cash")

    for c in risultato.candidates:
        data = c.catalyst.expected_date or c.catalyst.expected_date_window
        table.add_row(
            f"[bold]{c.ticker}[/bold]",
            f"${c.price:,.2f}",
            f"${c.market_cap_usd / 1_000_000:,.0f}M",
            str(data),
            f"{c.cash_runway_months:,.1f}m" if c.cash_runway_months is not None else "—",
            f"{c.attractiveness_score:,.0f}",
            "[yellow]needs refinancing[/yellow]" if c.financing_risk else "sufficient",
        )
    return table


if __name__ == "__main__":
    app()
