"""Dati di mercato via yfinance: quotazione, float, short interest, bilancio sintetico.

Due avvertenze che questo modulo incapsula:

1. `Ticker.info` è un dizionario senza schema garantito: per i titoli poco
   seguiti (i micro-cap biotech sono il caso tipico) singoli campi possono
   mancare o valere None. Ogni accesso passa da `_safe_float`, mai da `[...]`.
2. `shortPercentOfFloat` arriva come frazione (0.0125 = 1,25%). Viene
   normalizzato subito a percentuale: trattarlo come tale a valle
   sbaglierebbe di 100 volte lo short squeeze score.

Lo short interest è inoltre vecchio di 2-3 settimane per costruzione, perché
FINRA lo rileva due volte al mese: `short_interest_date` riporta la data di
riferimento effettiva e va sempre mostrata accanto al valore.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import yfinance as yf

from biocatalyst.data.base import DataNotFoundError, DataProviderError, DataUnavailableError
from biocatalyst.data.cache import DataCache
from biocatalyst.log import get_logger
from biocatalyst.models.raw_data import MarketData, PricePoint, SectorSentiment

logger = get_logger(__name__)

#: ETF usati come termometro del settore biotech (Requisito 3, Agente 3).
BIOTECH_SECTOR_ETFS = ("XBI", "IBB")


def _safe_float(info: dict[str, Any], key: str) -> float | None:
    """Legge un campo numerico tollerando assenza, None e valori non numerici."""
    value = info.get(key)
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        logger.debug("campo_non_numerico", campo=key, valore=repr(value))
        return None
    return result


def _epoch_to_date(info: dict[str, Any], key: str) -> date | None:
    """`dateShortInterest` arriva come timestamp Unix, non come data ISO."""
    value = info.get(key)
    if value is None:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=UTC).date()
    except (TypeError, ValueError, OSError):
        logger.debug("timestamp_non_valido", campo=key, valore=repr(value))
        return None


class MarketDataProvider:
    """Wrapper su yfinance con cache e degradazione controllata."""

    def __init__(
        self,
        cache: DataCache | None = None,
        price_ttl_seconds: int = 900,
        history_period: str = "6mo",
    ) -> None:
        self.cache = cache
        self.price_ttl_seconds = price_ttl_seconds
        self.history_period = history_period

    def _fetch_info(self, ticker: str) -> dict[str, Any]:
        def fetch() -> dict[str, Any]:
            try:
                info = yf.Ticker(ticker).info
            except Exception as exc:  # yfinance non espone una gerarchia di errori stabile
                raise DataUnavailableError(f"yfinance non risponde per {ticker}: {exc}") from exc
            if not info or not isinstance(info, dict):
                raise DataNotFoundError(f"nessun dato di mercato per {ticker}")
            return info

        if self.cache is None:
            return fetch()
        return self.cache.get_or_fetch(f"yf:info:{ticker.upper()}", self.price_ttl_seconds, fetch)

    def get_market_data(self, ticker: str) -> MarketData:
        info = self._fetch_info(ticker)

        short_fraction = _safe_float(info, "shortPercentOfFloat")

        return MarketData(
            price=_safe_float(info, "currentPrice") or _safe_float(info, "regularMarketPrice"),
            market_cap_usd=_safe_float(info, "marketCap"),
            shares_outstanding=_safe_float(info, "sharesOutstanding"),
            float_shares=_safe_float(info, "floatShares"),
            shares_short=_safe_float(info, "sharesShort"),
            short_ratio_days=_safe_float(info, "shortRatio"),
            # Da frazione a percentuale: yfinance restituisce 0.0125 per l'1,25%.
            short_percent_of_float=None if short_fraction is None else short_fraction * 100,
            short_interest_date=_epoch_to_date(info, "dateShortInterest"),
            average_volume=_safe_float(info, "averageVolume"),
            analyst_target_mean=_safe_float(info, "targetMeanPrice"),
            total_cash_usd=_safe_float(info, "totalCash"),
            total_debt_usd=_safe_float(info, "totalDebt"),
            price_history=self.get_price_history(ticker),
        )

    def get_company_name(self, ticker: str) -> str | None:
        info = self._fetch_info(ticker)
        name = info.get("longName") or info.get("shortName")
        return str(name) if name else None

    def get_price_history(self, ticker: str) -> list[PricePoint]:
        def fetch() -> list[dict[str, Any]]:
            try:
                frame = yf.Ticker(ticker).history(period=self.history_period)
            except Exception as exc:
                raise DataUnavailableError(
                    f"storico prezzi non disponibile per {ticker}: {exc}"
                ) from exc
            rows: list[dict[str, Any]] = []
            for index, row in frame.iterrows():
                close = row.get("Close")
                if close is None:
                    continue
                rows.append({"trade_date": index.date().isoformat(), "close": float(close)})
            return rows

        if self.cache is None:
            raw = fetch()
        else:
            raw = self.cache.get_or_fetch(
                f"yf:history:{ticker.upper()}:{self.history_period}",
                self.price_ttl_seconds,
                fetch,
            )
        return [
            PricePoint(trade_date=date.fromisoformat(r["trade_date"]), close=r["close"])
            for r in raw
            if r["close"] > 0
        ]

    def get_sector_sentiment(self, period_days: int = 30) -> list[SectorSentiment]:
        """Variazione percentuale di XBI e IBB sulla finestra richiesta.

        Un ETF che non risponde non deve far fallire l'intero contesto di
        mercato: viene saltato e annotato nei log.
        """
        results: list[SectorSentiment] = []
        for symbol in BIOTECH_SECTOR_ETFS:
            try:
                results.append(self._sector_sentiment_for(symbol, period_days))
            except DataProviderError as exc:
                logger.warning("sentiment_settore_non_disponibile", etf=symbol, errore=str(exc))
        return results

    def _sector_sentiment_for(self, symbol: str, period_days: int) -> SectorSentiment:
        def fetch() -> dict[str, Any]:
            try:
                frame = yf.Ticker(symbol).history(period=f"{period_days}d")
            except Exception as exc:
                raise DataUnavailableError(f"storico {symbol} non disponibile: {exc}") from exc
            closes = [float(c) for c in frame["Close"].tolist() if c is not None]
            if len(closes) < 2:
                raise DataNotFoundError(
                    f"storico {symbol} troppo corto per calcolare la variazione"
                )
            return {
                "first": closes[0],
                "last": closes[-1],
                "as_of": frame.index[-1].date().isoformat(),
            }

        if self.cache is None:
            raw = fetch()
        else:
            raw = self.cache.get_or_fetch(
                f"yf:sector:{symbol}:{period_days}", self.price_ttl_seconds, fetch
            )

        change_pct = (raw["last"] - raw["first"]) / raw["first"] * 100
        return SectorSentiment(
            symbol=symbol,
            period_days=period_days,
            price_change_pct=change_pct,
            as_of=date.fromisoformat(raw["as_of"]),
        )
