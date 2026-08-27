"""Orchestrazione sequenziale dei quattro agenti."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from biocatalyst.agents.analyst import ClinicalFinancialAnalystAgent
from biocatalyst.agents.base import KEY_REPORT, KEY_TICKER, AgentError, BaseAgent
from biocatalyst.agents.data_collector import DataCollectorAgent
from biocatalyst.agents.market_news import MarketNewsAgent
from biocatalyst.agents.report_writer import ReportWriterAgent
from biocatalyst.config import Settings, get_settings
from biocatalyst.data.factory import DataProviders, build_data_providers
from biocatalyst.llm.factory import provider_for_agent
from biocatalyst.log import get_logger
from biocatalyst.models.report import Report, ReportLanguage

logger = get_logger(__name__)

#: Chiamato prima di ogni agente con (indice, totale, nome): serve alla UI
#: Streamlit per mostrare quale agente sta lavorando.
ProgressCallback = Callable[[int, int, str], None]


def build_pipeline(
    providers: DataProviders,
    settings: Settings | None = None,
    language: ReportLanguage | None = None,
) -> list[BaseAgent]:
    settings = settings or get_settings()
    language = language or settings.report_language
    return [
        DataCollectorAgent(providers, language),
        ClinicalFinancialAnalystAgent(provider_for_agent("analyst", settings), language),
        MarketNewsAgent(provider_for_agent("news", settings), providers, language),
        ReportWriterAgent(provider_for_agent("writer", settings), providers, language),
    ]


def analyze(
    ticker: str,
    providers: DataProviders | None = None,
    settings: Settings | None = None,
    on_progress: ProgressCallback | None = None,
    language: ReportLanguage | None = None,
) -> Report:
    """Esegue la pipeline completa su un ticker e restituisce il report.

    Se `providers` non è fornito ne costruisce (e chiude) uno proprio.
    """
    settings = settings or get_settings()
    owns_providers = providers is None
    providers = providers or build_data_providers(settings)

    try:
        agents = build_pipeline(providers, settings, language)
        context: dict[str, Any] = {KEY_TICKER: ticker.upper()}

        for index, agent in enumerate(agents, start=1):
            if on_progress is not None:
                on_progress(index, len(agents), agent.name)
            context = agent.run(context)

        report = context.get(KEY_REPORT)
        if not isinstance(report, Report):
            raise AgentError("La pipeline è terminata senza produrre un report.")
        logger.info("pipeline_completata", ticker=report.ticker, rating=report.rating)
        return report
    finally:
        if owns_providers:
            providers.close()
