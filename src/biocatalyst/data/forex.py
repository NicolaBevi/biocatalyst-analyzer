"""Tasso EUR/USD via Frankfurter (dati di riferimento BCE, nessuna API key).

Serve alla tabella Expected Value, che il requisito vuole in euro citando
tasso e data di riferimento.

Nei fine settimana e nei festivi la BCE non pubblica: l'API restituisce
silenziosamente l'ultimo giorno lavorativo utile. Per questo si legge sempre
la data indicata nella risposta invece di assumere quella richiesta.
"""

from __future__ import annotations

from datetime import date
from typing import ClassVar

from biocatalyst.data.base import (
    DataParseError,
    HTTPDataProvider,
    RateLimiter,
)
from biocatalyst.data.cache import DataCache
from biocatalyst.log import get_logger

logger = get_logger(__name__)

FRANKFURTER_BASE = "https://api.frankfurter.dev/v1"


class ExchangeRate:
    __slots__ = ("rate", "rate_date")

    def __init__(self, rate: float, rate_date: date) -> None:
        self.rate = rate
        self.rate_date = rate_date

    def __repr__(self) -> str:
        return f"ExchangeRate(rate={self.rate}, rate_date={self.rate_date.isoformat()})"


class ForexProvider(HTTPDataProvider):
    rate_limiter: ClassVar[RateLimiter] = RateLimiter(0.2)

    def __init__(
        self,
        cache: DataCache | None = None,
        timeout: int = 30,
        max_retries: int = 3,
        ttl_seconds: int = 86_400,
    ) -> None:
        super().__init__(cache=cache, timeout=timeout, max_retries=max_retries)
        self.ttl_seconds = ttl_seconds

    def get_eur_usd(self, on_date: date | None = None) -> ExchangeRate:
        """Quanti dollari vale un euro. `on_date=None` chiede l'ultimo disponibile."""
        segment = on_date.isoformat() if on_date else "latest"
        payload = self._get_json(
            f"{FRANKFURTER_BASE}/{segment}",
            params={"base": "EUR", "symbols": "USD"},
            ttl_seconds=self.ttl_seconds,
            cache_key=f"frankfurter:eurusd:{segment}",
        )

        rate = payload.get("rates", {}).get("USD")
        # La data della risposta può precedere quella richiesta (weekend/festivi):
        # è quella che va citata nel report.
        effective = payload.get("date")
        if rate is None or effective is None:
            raise DataParseError(f"risposta Frankfurter senza tasso EUR/USD: {payload}")

        try:
            return ExchangeRate(rate=float(rate), rate_date=date.fromisoformat(effective))
        except (TypeError, ValueError) as exc:
            raise DataParseError(f"tasso EUR/USD non interpretabile: {payload}") from exc
