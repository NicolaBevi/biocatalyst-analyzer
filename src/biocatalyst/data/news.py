"""Notizie sul ticker via Finnhub.

Finnhub è stato scelto al posto di NewsAPI perché il tier gratuito di
quest'ultimo vieta esplicitamente l'uso al di fuori di un ambiente di
sviluppo, anche non commerciale: incompatibile con un'app pubblicata.
Richiede una API key gratuita (https://finnhub.io/register).
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any, ClassVar

from pydantic import SecretStr

from biocatalyst.data.base import (
    DataAuthError,
    HTTPDataProvider,
    RateLimiter,
    translates_validation_errors,
)
from biocatalyst.data.cache import DataCache
from biocatalyst.log import get_logger
from biocatalyst.models.raw_data import NewsItem

logger = get_logger(__name__)

COMPANY_NEWS_URL = "https://finnhub.io/api/v1/company-news"


class NewsProvider(HTTPDataProvider):
    # Tier gratuito: 60 chiamate al minuto.
    rate_limiter: ClassVar[RateLimiter] = RateLimiter(1.05)

    def __init__(
        self,
        api_key: SecretStr | None,
        cache: DataCache | None = None,
        timeout: int = 30,
        max_retries: int = 3,
        ttl_seconds: int = 900,
    ) -> None:
        super().__init__(cache=cache, timeout=timeout, max_retries=max_retries)
        self._api_key = api_key
        self.ttl_seconds = ttl_seconds

    @translates_validation_errors
    def get_company_news(self, ticker: str, days_back: int = 30) -> list[NewsItem]:
        if self._api_key is None:
            raise DataAuthError(
                "FINNHUB_API_KEY non configurata: registrati gratuitamente su "
                "https://finnhub.io/register e inseriscila nel file .env"
            )

        to_date = date.today()
        from_date = to_date - timedelta(days=days_back)
        payload = self._get_json(
            COMPANY_NEWS_URL,
            params={
                "symbol": ticker.upper(),
                "from": from_date.isoformat(),
                "to": to_date.isoformat(),
                "token": self._api_key.get_secret_value(),
            },
            ttl_seconds=self.ttl_seconds,
            # La chiave di cache non contiene mai il token.
            cache_key=f"finnhub:news:{ticker.upper()}:{from_date}:{to_date}",
        )

        if not isinstance(payload, list):
            logger.warning("risposta_finnhub_inattesa", tipo=type(payload).__name__)
            return []

        items: list[NewsItem] = []
        for entry in payload:
            item = _parse_news(entry)
            if item is not None:
                items.append(item)
        return items


def _parse_news(entry: dict[str, Any]) -> NewsItem | None:
    headline = entry.get("headline")
    url = entry.get("url")
    published = entry.get("datetime")
    if not headline or not url or published is None:
        return None
    try:
        published_at = datetime.fromtimestamp(int(published), tz=UTC)
    except (TypeError, ValueError, OSError):
        return None
    return NewsItem(
        headline=headline,
        source=entry.get("source", "Finnhub"),
        url=url,
        published_at=published_at,
        summary=entry.get("summary") or None,
    )
