FROM python:3.11-slim

# Librerie di sistema richieste da WeasyPrint per il rendering PDF (Pango/Cairo).
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# Layer separato per le dipendenze: cache riutilizzabile finché pyproject/uv.lock non cambiano.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8501

CMD ["uv", "run", "streamlit", "run", "src/biocatalyst/app.py", "--server.address=0.0.0.0"]
