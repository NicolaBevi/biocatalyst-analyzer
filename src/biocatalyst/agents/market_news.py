"""Agente 3: contesto di mercato e notizie.

Il compito delicato di questo agente è tenere separati i fatti verificati dalle
voci di mercato: il modello riceve istruzioni esplicite in tal senso e lo
schema di output ha due campi distinti, così la distinzione sopravvive fino al
report invece di sciogliersi nella prosa.
"""

from __future__ import annotations

from typing import Any, ClassVar

from biocatalyst.agents.base import (
    KEY_MARKET_CONTEXT,
    KEY_RAW_DATA,
    BaseAgent,
    append_missing,
)
from biocatalyst.agents.prompts import MARKET_SYSTEM
from biocatalyst.data.base import collect_safely
from biocatalyst.data.factory import DataProviders
from biocatalyst.i18n import t
from biocatalyst.llm.base import BaseLLMProvider, LLMError, Message
from biocatalyst.llm.structured import complete_structured
from biocatalyst.log import get_logger
from biocatalyst.models.analysis import MarketContext
from biocatalyst.models.raw_data import CompanyRawData, NewsItem, SectorSentiment
from biocatalyst.models.report import ReportLanguage

logger = get_logger(__name__)


class MarketNewsAgent(BaseAgent):
    name: ClassVar[str] = "MarketNews"
    requires: ClassVar[tuple[str, ...]] = (KEY_RAW_DATA,)

    def __init__(
        self,
        provider: BaseLLMProvider,
        providers: DataProviders,
        language: ReportLanguage = "en",
        max_tokens: int = 8_000,
        temperature: float | None = 0.0,
        seed: int | None = 1,
        news_days: int = 30,
        sentiment_days: int = 30,
    ) -> None:
        self.provider = provider
        self.providers = providers
        self.language = language
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.seed = seed
        self.news_days = news_days
        self.sentiment_days = sentiment_days

    def _run(self, context: dict[str, Any]) -> dict[str, Any]:
        raw: CompanyRawData = context[KEY_RAW_DATA]
        missing: list[str] = []

        news = collect_safely(
            t(self.language, "src.news"),
            lambda: self.providers.news.get_company_news(raw.ticker, days_back=self.news_days),
            missing,
        )
        sentiment = collect_safely(
            t(self.language, "src.sector_etf"),
            lambda: self.providers.market.get_sector_sentiment(self.sentiment_days),
            missing,
        )

        market_context = self._summarise(raw, news or [], sentiment or [], missing)
        context[KEY_MARKET_CONTEXT] = market_context
        append_missing(context, missing)
        return context

    def _summarise(
        self,
        raw: CompanyRawData,
        news: list[NewsItem],
        sentiment: list[SectorSentiment],
        missing: list[str],
    ) -> MarketContext:
        headlines = "\n".join(
            f"- [{item.published_at:%Y-%m-%d}] {item.source}: {item.headline}" for item in news[:25]
        )
        sector_lines = "\n".join(
            f"- {s.symbol}: {s.price_change_pct:+.1f}% negli ultimi {s.period_days} giorni "
            f"(al {s.as_of})"
            for s in sentiment
        )
        prompt = (
            f"Società: {raw.company_name or raw.ticker} ({raw.ticker})\n\n"
            f"Andamento del settore biotech:\n{sector_lines or '- dato non disponibile'}\n\n"
            f"Notizie sul titolo degli ultimi {self.news_days} giorni:\n"
            f"{headlines or '- nessuna notizia disponibile'}\n\n"
            "Sintetizza il contesto di mercato. Nelle note macro considera il "
            "clima per le small cap biotech (tassi di interesse, orientamento "
            "FDA, attività di fusioni e acquisizioni nel settore)."
        )

        try:
            summary = complete_structured(
                self.provider,
                MARKET_SYSTEM[self.language],
                [Message(role="user", content=prompt)],
                MarketContext,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                seed=self.seed,
            )
        except LLMError as exc:
            logger.warning("contesto_mercato_fallito", errore=str(exc)[:300])
            missing.append(t(self.language, "agent.market_failed", error=exc))
            return MarketContext(
                sector_sentiment=sentiment,
                macro_notes=t(self.language, "agent.market_unavailable"),
            )

        # Il sentiment è un dato misurato, non una deduzione del modello:
        # si sovrascrive con i valori reali per evitare che venga alterato.
        return summary.model_copy(update={"sector_sentiment": sentiment})
