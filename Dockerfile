# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

# Librerie di sistema richieste da WeasyPrint per generare il PDF.
# L'elenco è ricavato dalle librerie che WeasyPrint risolve davvero via
# ctypes (gobject, pango, pangoft2, harfbuzz, fontconfig, gio, cairo), non
# copiato da una guida: le versioni recenti hanno smesso di usare
# gdk-pixbuf, quindi installarlo sarebbe peso inutile.
# glib non è nominato di proposito: arriva come dipendenza di pango, e il suo
# nome di pacchetto cambia fra Debian e Ubuntu recenti (libglib2.0-0t64).
# fonts-liberation fornisce i caratteri: senza, il PDF esce con i riquadri.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpango-1.0-0 \
        libpangoft2-1.0-0 \
        libharfbuzz0b \
        libfontconfig1 \
        libcairo2 \
        fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Le dipendenze in un layer separato: cambiano molto meno spesso del codice,
# quindi la cache di build regge fra una modifica e l'altra.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY README.md ./
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# I report generati finiscono qui: montare un volume su questa cartella per
# conservarli fuori dal contenitore.
RUN mkdir -p /app/reports /app/.cache \
    && useradd --create-home --uid 1000 biocatalyst \
    && chown -R biocatalyst:biocatalyst /app
USER biocatalyst

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; \
sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4).status == 200 else 1)"

# Interfaccia web per default. Per la CLI:
#   docker run --rm --env-file .env biocatalyst analyze ENSC
ENTRYPOINT []
CMD ["streamlit", "run", "src/biocatalyst/app.py", \
     "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
