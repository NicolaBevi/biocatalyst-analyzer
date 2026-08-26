"""Esportazione dei report in Markdown, JSON, HTML e PDF."""

from __future__ import annotations

import json
from pathlib import Path

from biocatalyst.models.report import Report
from biocatalyst.report.html import render_html
from biocatalyst.report.markdown import render_markdown
from biocatalyst.report.pdf import PDFRenderingError, render_pdf


def render_json(report: Report, indent: int = 2) -> str:
    """JSON completo del report: tutti i campi, comprese le metriche e le fonti."""
    return json.dumps(json.loads(report.model_dump_json()), ensure_ascii=False, indent=indent)


#: Formati salvati per default da `save_all_formats`.
DEFAULT_FORMATS: tuple[str, ...] = (".md", ".json", ".pdf")

#: Cartella radice dei report generati.
DEFAULT_REPORTS_DIR = Path("reports")


def report_directory(report: Report, base_dir: Path = DEFAULT_REPORTS_DIR) -> Path:
    """Cartella dedicata a un ticker: `reports/ENSC/`."""
    return base_dir / report.ticker.upper()


def report_filename(report: Report, extension: str) -> str:
    """Nome file autodescrittivo: `ENSC_2026-08-26_it.pdf`.

    Include ticker e data anche se la cartella li ripete, così il file resta
    identificabile quando viene spostato o allegato a un'email. La data evita
    che due analisi dello stesso titolo in giorni diversi si sovrascrivano.
    """
    suffix = extension if extension.startswith(".") else f".{extension}"
    return f"{report.ticker.upper()}_{report.report_date.isoformat()}_{report.language}{suffix}"


def save_all_formats(
    report: Report,
    base_dir: Path = DEFAULT_REPORTS_DIR,
    formats: tuple[str, ...] = DEFAULT_FORMATS,
) -> list[Path]:
    """Salva il report in più formati dentro `reports/<TICKER>/`."""
    directory = report_directory(report, base_dir)
    return [save_report(report, directory / report_filename(report, ext)) for ext in formats]


def save_report(report: Report, destination: Path) -> Path:
    """Salva il report nel formato dedotto dall'estensione del file.

    Formati riconosciuti: `.md`, `.json`, `.html`, `.pdf`.
    """
    suffix = destination.suffix.lower()
    destination.parent.mkdir(parents=True, exist_ok=True)

    if suffix == ".pdf":
        return render_pdf(report, destination)

    renderers = {
        ".md": render_markdown,
        ".markdown": render_markdown,
        ".json": render_json,
        ".html": render_html,
    }
    renderer = renderers.get(suffix)
    if renderer is None:
        raise ValueError(
            f"Estensione '{suffix}' non supportata. Usa una fra: .md, .json, .html, .pdf"
        )
    destination.write_text(renderer(report), encoding="utf-8")
    return destination


__all__ = [
    "DEFAULT_FORMATS",
    "DEFAULT_REPORTS_DIR",
    "PDFRenderingError",
    "render_html",
    "render_json",
    "render_markdown",
    "render_pdf",
    "report_directory",
    "report_filename",
    "save_all_formats",
    "save_report",
]
