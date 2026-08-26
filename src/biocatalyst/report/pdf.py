"""Rendering PDF via WeasyPrint.

WeasyPrint compone il PDF da HTML e CSS, quindi il foglio di stile qui sotto
è ciò che determina l'aspetto del documento. Richiede le librerie di sistema
Pango e Cairo, incluse nel Dockerfile: se mancano, l'import fallisce con un
messaggio poco leggibile, perciò viene tradotto in un errore esplicito.
"""

from __future__ import annotations

from pathlib import Path

from biocatalyst.models.report import Report
from biocatalyst.report.html import render_html


class PDFRenderingError(RuntimeError):
    """WeasyPrint non è utilizzabile in questo ambiente."""


CSS = """
@page { size: A4; margin: 2cm 1.8cm; @bottom-center {
    content: counter(page) " / " counter(pages);
    font-size: 9pt; color: #888; } }
body { font-family: "Liberation Sans", "DejaVu Sans", sans-serif;
       font-size: 10.5pt; line-height: 1.5; color: #1a1a1a; }
h1 { font-size: 20pt; margin: 0 0 4pt; color: #0f3d5c; }
h2 { font-size: 13pt; margin: 18pt 0 6pt; padding-bottom: 3pt;
     border-bottom: 1.5pt solid #0f3d5c; color: #0f3d5c; }
h3 { font-size: 11.5pt; margin: 12pt 0 4pt; color: #21618c; }
table { width: 100%; border-collapse: collapse; margin: 8pt 0; font-size: 10pt; }
th, td { border: 0.5pt solid #ccc; padding: 5pt 7pt; text-align: left; }
th { background: #eef4f8; font-weight: 600; }
.intestazione { background: #f5f8fa; border-left: 4pt solid #0f3d5c;
                padding: 10pt 14pt; margin-bottom: 14pt; }
.intestazione p { margin: 2pt 0; }
.nota { background: #fafafa; border-left: 3pt solid #b8c9d4; padding: 6pt 10pt;
        margin: 6pt 0 10pt; font-size: 9pt; color: #4a5a66; font-style: italic; }
.avviso { background: #fff6e5; border-left: 4pt solid #e08b00; padding: 8pt 12pt;
          margin: 10pt 0; font-size: 9.5pt; }
.scenario { margin: 6pt 0; padding: 7pt 10pt; background: #f7f9fb;
            border-left: 3pt solid #21618c; }
.rating { font-size: 13pt; font-weight: 700; }
.disclaimer { margin-top: 20pt; padding-top: 8pt; border-top: 0.5pt solid #ccc;
              font-size: 8.5pt; color: #666; }
ul { margin: 4pt 0 4pt 14pt; padding: 0; }
"""


def render_pdf(report: Report, destination: Path) -> Path:
    """Scrive il report come PDF e restituisce il percorso del file."""
    try:
        import weasyprint
    except OSError as exc:  # pragma: no cover - dipende dall'ambiente di esecuzione
        raise PDFRenderingError(
            "WeasyPrint richiede le librerie di sistema Pango e Cairo, che non "
            "risultano installate. Su Debian/Ubuntu: "
            "sudo apt-get install libpango-1.0-0 libpangocairo-1.0-0 libcairo2. "
            f"Dettaglio: {exc}"
        ) from exc

    destination.parent.mkdir(parents=True, exist_ok=True)
    weasyprint.HTML(string=render_html(report)).write_pdf(
        str(destination), stylesheets=[weasyprint.CSS(string=CSS)]
    )
    return destination
