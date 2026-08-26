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
    "PDFRenderingError",
    "render_html",
    "render_json",
    "render_markdown",
    "render_pdf",
    "save_report",
]
