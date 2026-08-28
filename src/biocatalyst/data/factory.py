"""Costruzione dei data provider a partire dalla configurazione.

Tutti i provider condividono una sola istanza di `DataCache`: TTL diversi
convivono nello stesso archivio perché la scadenza è per singola chiave.
"""

from __future__ import annotations

from dataclasses import dataclass

from biocatalyst.config import Settings, get_settings
from biocatalyst.data.cache import DataCache
from biocatalyst.data.clinical_trials import ClinicalTrialsProvider
from biocatalyst.data.drug_pricing import DrugPricingProvider
from biocatalyst.data.fda import FDAProvider
from biocatalyst.data.forex import ForexProvider
from biocatalyst.data.market import MarketDataProvider
from biocatalyst.data.news import NewsProvider
from biocatalyst.data.sec import SECProvider


@dataclass(frozen=True)
class DataProviders:
    """Tutte le fonti dati pronte all'uso, con la cache condivisa."""

    cache: DataCache
    market: MarketDataProvider
    sec: SECProvider
    clinical_trials: ClinicalTrialsProvider
    fda: FDAProvider
    news: NewsProvider
    forex: ForexProvider
    drug_pricing: DrugPricingProvider

    def close(self) -> None:
        self.cache.close()


def build_data_providers(
    settings: Settings | None = None, cache_enabled: bool = True
) -> DataProviders:
    settings = settings or get_settings()
    cache = DataCache(settings.cache_dir, enabled=cache_enabled)

    return DataProviders(
        cache=cache,
        market=MarketDataProvider(
            cache=cache,
            price_ttl_seconds=settings.cache_ttl_price_seconds,
        ),
        sec=SECProvider(
            user_agent=settings.sec_edgar_user_agent,
            cache=cache,
            timeout=settings.http_request_timeout_seconds,
            filing_ttl_seconds=settings.cache_ttl_filing_seconds,
        ),
        clinical_trials=ClinicalTrialsProvider(
            cache=cache,
            timeout=settings.http_request_timeout_seconds,
            trial_ttl_seconds=settings.cache_ttl_trial_seconds,
        ),
        fda=FDAProvider(
            cache=cache,
            timeout=settings.http_request_timeout_seconds,
            ttl_seconds=settings.cache_ttl_filing_seconds,
        ),
        news=NewsProvider(
            api_key=settings.finnhub_api_key,
            cache=cache,
            timeout=settings.http_request_timeout_seconds,
            ttl_seconds=settings.cache_ttl_price_seconds,
        ),
        drug_pricing=DrugPricingProvider(
            cache=cache,
            timeout=settings.http_request_timeout_seconds,
            ttl_seconds=settings.cache_ttl_filing_seconds,
        ),
        forex=ForexProvider(
            cache=cache,
            timeout=settings.http_request_timeout_seconds,
            ttl_seconds=settings.cache_ttl_filing_seconds,
        ),
    )
