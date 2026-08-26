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
from biocatalyst.config import LLMProviderName, Settings, get_settings
from biocatalyst.data.base import DataProviderError
from biocatalyst.data.factory import build_data_providers
from biocatalyst.llm.base import LLMError
from biocatalyst.log import configure_logging
from biocatalyst.models.report import Report
from biocatalyst.report import (
    DEFAULT_FORMATS,
    DEFAULT_REPORTS_DIR,
    save_all_formats,
    save_report,
)

app = typer.Typer(
    name="biocatalyst",
    help="Report di due diligence su aziende biotech/pharma NASDAQ e NYSE.",
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
    table.add_row("Prezzo", f"${report.current_price:,.4f}")
    table.add_row("Giudizio", f"[{colore} bold]{report.rating}[/{colore} bold]")
    m = report.financial_metrics
    if m.cash_runway_months is not None:
        table.add_row("Autonomia di cassa", f"{m.cash_runway_months:,.1f} mesi")
    if m.dilution_risk_score is not None:
        table.add_row("Rischio diluizione", f"{m.dilution_risk_score:,.0f}/100")
    roi = report.expected_value.rows[0]
    table.add_row(
        f"Valore atteso su ${roi.investment_usd:,.0f}",
        f"${roi.expected_value_usd:,.2f} ({roi.expected_roi_pct:+.1f}%)",
    )
    table.add_row("Catalizzatore", report.main_catalyst[:70])
    return table


@app.command()
def version() -> None:
    """Mostra la versione installata."""
    console.print(f"biocatalyst-analyzer {__version__}")


@app.command()
def analyze(
    ticker: Annotated[str, typer.Argument(help="Ticker da analizzare, es. ENSC")],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="File singolo di destinazione. Se omesso salva in reports/<TICKER>/.",
        ),
    ] = None,
    formats: Annotated[
        str,
        typer.Option("--formats", "-f", help="Formati separati da virgola: md,json,html,pdf"),
    ] = ",".join(f.lstrip(".") for f in DEFAULT_FORMATS),
    language: Annotated[
        str | None, typer.Option("--language", "-l", help="Lingua del report: it oppure en")
    ] = None,
    provider: Annotated[
        str | None,
        typer.Option("--provider", "-p", help="Forza un provider LLM per tutti gli agenti"),
    ] = None,
    no_cache: Annotated[
        bool, typer.Option("--no-cache", help="Ignora la cache e reinterroga tutte le fonti")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Mostra i log dettagliati degli agenti")
    ] = False,
) -> None:
    """Due diligence completa su un ticker."""
    # Ogni parametro va validato PRIMA di costruire i provider: un formato
    # sbagliato scoperto a valle costerebbe un'analisi completa a pagamento.
    formati = _parse_formats(formats) if output is None else ()
    settings = _settings_for(provider, language)
    _configura_log(settings, verbose)

    providers = build_data_providers(settings, cache_enabled=not no_cache)
    try:
        console.print(
            f"\n[bold]Analisi di {ticker.upper()}[/bold] (lingua: {settings.report_language})"
        )
        report = _esegui(ticker, settings, providers, mostra_avanzamento=True)

        if output is not None:
            scritti = [save_report(report, output)]
        else:
            scritti = save_all_formats(report, DEFAULT_REPORTS_DIR, formati)

        console.print()
        console.print(_riassunto(report))
        console.print("\n[bold]File scritti:[/bold]")
        for percorso in scritti:
            console.print(f"  {percorso}")

        if report.source_quality.warnings:
            console.print(
                f"\n[yellow]⚠ {len(report.source_quality.warnings)} avvisi sui dati[/yellow]"
            )
            for avviso in report.source_quality.warnings:
                console.print(f"  [yellow]•[/yellow] {avviso}")
    except (DataProviderError, LLMError, AgentError) as exc:
        error_console.print(f"\n[red]Analisi non riuscita:[/red] {exc}")
        raise typer.Exit(code=1) from exc
    finally:
        providers.close()


@app.command()
def compare(
    tickers: Annotated[list[str], typer.Argument(help="Due o più ticker da confrontare")],
    language: Annotated[
        str | None, typer.Option("--language", "-l", help="Lingua dei report: it oppure en")
    ] = None,
    provider: Annotated[
        str | None, typer.Option("--provider", "-p", help="Forza un provider LLM")
    ] = None,
    save: Annotated[
        bool, typer.Option("--save/--no-save", help="Salva anche i report completi")
    ] = True,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Mostra i log dettagliati degli agenti")
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
                console.print(f"  [red]non riuscito:[/red] {exc}")
                falliti.append((ticker.upper(), str(exc)))
    finally:
        providers.close()

    if not riusciti:
        error_console.print("\n[red]Nessun ticker analizzato con successo.[/red]")
        raise typer.Exit(code=1)

    console.print()
    console.print(_tabella_confronto(riusciti))
    if falliti:
        console.print(f"\n[yellow]Non analizzati: {', '.join(t for t, _ in falliti)}[/yellow]")


def _tabella_confronto(reports: list[Report]) -> Table:
    table = Table(title="Confronto", header_style="bold")
    table.add_column("Ticker")
    table.add_column("Prezzo", justify="right")
    table.add_column("Giudizio")
    table.add_column("Runway", justify="right")
    table.add_column("Diluizione", justify="right")
    table.add_column("Squeeze", justify="right")
    table.add_column("ROI atteso", justify="right")

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
        float, typer.Option("--max-price", help="Prezzo massimo per azione")
    ] = 10.0,
    sector: Annotated[
        str | None, typer.Option("--sector", help="Area terapeutica, es. oncology")
    ] = None,
    catalyst_window: Annotated[
        int, typer.Option("--catalyst-window", help="Finestra dei catalizzatori in giorni")
    ] = 180,
) -> None:
    """Ricerca di nuove opportunità secondo criteri (in sviluppo)."""
    console.print(
        "[yellow]La modalità screen non è ancora disponibile.[/yellow]\n\n"
        "Richiede la costruzione di un universo di titoli biotech a partire dai "
        "codici SIC 2836/8731 della SEC, ed è la fase successiva dello sviluppo.\n\n"
        f"Criteri che sarebbero stati applicati: prezzo ≤ ${max_price:,.2f}, "
        f"area terapeutica {sector or 'qualsiasi'}, catalizzatori entro {catalyst_window} giorni."
    )
    raise typer.Exit(code=2)


if __name__ == "__main__":
    app()
