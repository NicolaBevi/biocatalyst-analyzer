"""Fondamenta comuni ai data provider: errori, rate limiting, client HTTP.

Regola trasversale del progetto: se una fonte non risponde, il report deve
comunque essere generato segnalando il dato mancante. Per questo i provider
sollevano `DataProviderError` e il chiamante usa `collect_safely`, che
trasforma il fallimento in una voce di `missing_data` invece che in un crash.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from datetime import date
from functools import wraps
from typing import Any, ClassVar, ParamSpec, TypeVar

import httpx
from pydantic import ValidationError
from tenacity import (
    RetryCallState,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from biocatalyst.data.cache import DataCache
from biocatalyst.log import get_logger

logger = get_logger(__name__)

T = TypeVar("T")
P = ParamSpec("P")
R = TypeVar("R")


class DataProviderError(Exception):
    """Errore generico di una fonte dati."""


class DataNotFoundError(DataProviderError):
    """La fonte ha risposto ma non ha dati per questa entità (404). Non ritentabile."""


class DataAuthError(DataProviderError):
    """API key mancante o rifiutata (401/403). Non ritentabile."""


class DataRateLimitError(DataProviderError):
    """Rate limit della fonte superato (429). Ritentabile."""


class DataUnavailableError(DataProviderError):
    """Fonte irraggiungibile o in errore (timeout, rete, 5xx). Ritentabile."""


class DataParseError(DataProviderError):
    """La risposta è arrivata ma non ha la forma attesa. Non ritentabile."""


def translates_validation_errors(func: Callable[P, R]) -> Callable[P, R]:
    """Traduce un `ValidationError` di Pydantic in `DataParseError`.

    Un valore fuori dai vincoli dei nostri modelli è un problema della fonte,
    non un bug nostro, e va trattato come tutti gli altri guasti di una fonte:
    `collect_safely` lo annota fra i dati mancanti e il report si genera lo
    stesso, lo screen salta quel titolo e prosegue con gli altri.

    Nasce da un caso reale: la SEC riporta le spese di R&S di Lineage Cell
    Therapeutics col segno negativo, il modello aveva un `ge=0`, e l'intera
    scansione dello screen si interrompeva su quell'unica società fra le 175
    esaminate. Il vincolo sbagliato è stato tolto, ma il difetto vero era che
    un dato inatteso potesse fermare tutto.

    Non cattura nient'altro: un `TypeError` o un `KeyError` resta un bug
    nostro e deve restare visibile, com'è già per `collect_safely`.
    """

    @wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except ValidationError as exc:
            errori = "; ".join(
                f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:3]
            )
            raise DataParseError(
                f"la risposta di {func.__qualname__} non rispetta lo schema atteso: {errori}"
            ) from exc

    return wrapper


RETRYABLE_DATA_ERRORS: tuple[type[DataProviderError], ...] = (
    DataRateLimitError,
    DataUnavailableError,
)


class RateLimiter:
    """Limitatore a intervallo minimo, condivisibile tra provider.

    La SEC applica il suo limite di 10 req/s per indirizzo IP sommando tutti i
    sottodomini (www, data, efts): un limitatore per-provider non basterebbe,
    serve una singola istanza condivisa tra tutti i client che parlano con
    quell'host. Thread-safe perché Streamlit può servire sessioni concorrenti.
    """

    def __init__(self, min_interval_seconds: float) -> None:
        self.min_interval_seconds = min_interval_seconds
        self._lock = threading.Lock()
        self._last_call: float = 0.0

    def wait(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_call
            remaining = self.min_interval_seconds - elapsed
            if remaining > 0:
                time.sleep(remaining)
            self._last_call = time.monotonic()


def parse_flexible_date(value: str | None) -> date | None:
    """Interpreta le date parziali restituite da alcune fonti.

    ClinicalTrials.gov restituisce sia "2030-05-31" sia "2027-04" (solo
    anno-mese) per le date stimate, e openFDA usa il formato compatto
    "20160523": `date.fromisoformat` da solo fallirebbe sul secondo caso.
    Una data anno-mese viene normalizzata al primo giorno del mese.
    """
    if not value:
        return None
    try:
        if len(value) == 7 and "-" in value:  # "2027-04"
            return date.fromisoformat(f"{value}-01")
        return date.fromisoformat(value)  # gestisce sia "2030-05-31" sia "20160523"
    except ValueError:
        logger.warning("data_non_interpretabile", valore=value)
        return None


def collect_safely(
    label: str,
    fetch: Callable[[], T],
    missing_data: list[str],
) -> T | None:
    """Esegue `fetch`; se la fonte fallisce annota il buco e restituisce None.

    È il punto in cui si realizza il requisito "il report si genera comunque":
    un dato non reperito diventa una riga esplicita in `missing_data`, mai una
    stima silenziosa.
    """
    try:
        return fetch()
    except DataProviderError as exc:
        message = f"{label}: {exc}"
        missing_data.append(message)
        logger.warning("dato_non_reperito", fonte=label, errore=str(exc))
        return None


class HTTPDataProvider:
    """Base per i provider che parlano HTTP/JSON.

    Centralizza rate limiting, retry con backoff e traduzione degli errori,
    così ogni fonte concreta implementa solo il proprio parsing.
    """

    base_url: ClassVar[str] = ""
    #: Condiviso a livello di classe: tutte le istanze di uno stesso provider
    #: (e, per la SEC, tutti i suoi sottodomini) rispettano lo stesso limite.
    rate_limiter: ClassVar[RateLimiter] = RateLimiter(0.0)

    retry_initial_wait: ClassVar[float] = 1.0
    retry_max_wait: ClassVar[float] = 20.0

    def __init__(
        self,
        cache: DataCache | None = None,
        timeout: int = 30,
        max_retries: int = 3,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.cache = cache
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.headers = headers or {}

    def _request_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        """Singola richiesta HTTP, senza cache e senza retry (li gestisce _get_json)."""
        self.rate_limiter.wait()
        try:
            response = httpx.get(
                url,
                params=params,
                headers=self.headers,
                timeout=self.timeout,
                follow_redirects=True,
            )
        except httpx.TimeoutException as exc:
            raise DataUnavailableError(f"timeout dopo {self.timeout}s su {url}") from exc
        except httpx.TransportError as exc:
            raise DataUnavailableError(f"errore di rete su {url}: {exc}") from exc

        if response.status_code == 404:
            raise DataNotFoundError(f"nessun dato disponibile ({url})")
        if response.status_code in (401, 403):
            raise DataAuthError(f"accesso negato ({response.status_code}) su {url}")
        if response.status_code == 429:
            raise DataRateLimitError(f"rate limit della fonte superato su {url}")
        if response.status_code >= 500:
            raise DataUnavailableError(f"errore server {response.status_code} su {url}")
        if response.status_code >= 400:
            raise DataProviderError(f"errore HTTP {response.status_code} su {url}")

        try:
            return response.json()
        except ValueError as exc:
            raise DataParseError(f"risposta non JSON da {url}") from exc

    def _get_json(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        ttl_seconds: int | None = None,
        cache_key: str | None = None,
    ) -> Any:
        """Richiesta con cache (se `cache_key` è dato) e retry sugli errori transitori."""

        def fetch() -> Any:
            retryer: Retrying = Retrying(
                stop=stop_after_attempt(self.max_retries),
                wait=wait_exponential_jitter(
                    initial=self.retry_initial_wait, max=self.retry_max_wait
                ),
                retry=retry_if_exception_type(RETRYABLE_DATA_ERRORS),
                before_sleep=self._log_retry,
                reraise=True,
            )
            return retryer(self._request_json, url, params)

        if self.cache is None or cache_key is None or ttl_seconds is None:
            return fetch()
        return self.cache.get_or_fetch(cache_key, ttl_seconds, fetch)

    def _log_retry(self, retry_state: RetryCallState) -> None:
        exc = retry_state.outcome.exception() if retry_state.outcome else None
        logger.warning(
            "data_provider_retry",
            provider=type(self).__name__,
            tentativo=retry_state.attempt_number,
            tentativi_totali=self.max_retries,
            errore=type(exc).__name__ if exc else None,
            dettaglio=str(exc) if exc else None,
        )
