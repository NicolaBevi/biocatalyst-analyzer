from __future__ import annotations

import typer

from biocatalyst import __version__

app = typer.Typer(
    name="biocatalyst",
    help="BioCatalyst Analyzer — due diligence su aziende biotech/pharma NASDAQ/NYSE.",
    no_args_is_help=True,
)


@app.command()
def version() -> None:
    """Mostra la versione installata."""
    typer.echo(f"biocatalyst-analyzer {__version__}")


if __name__ == "__main__":
    app()
