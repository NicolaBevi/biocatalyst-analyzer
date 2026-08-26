"""Cache su disco con TTL differenziati per tipo di dato.

I prezzi invecchiano in minuti, i filing e i trial in giorni: usare un TTL
unico costringerebbe a scegliere tra dati stantii e chiamate inutili.
Si mette in cache la risposta grezza (dict JSON), non i modelli Pydantic, così
un'evoluzione degli schemi non invalida la cache già scritta.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import diskcache

from biocatalyst.log import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class DataCache:
    def __init__(self, directory: Path, enabled: bool = True) -> None:
        self.enabled = enabled
        self.directory = directory
        self._cache: diskcache.Cache | None = None
        if enabled:
            directory.mkdir(parents=True, exist_ok=True)
            self._cache = diskcache.Cache(str(directory))

    def get_or_fetch(self, key: str, ttl_seconds: int, fetch: Callable[[], T]) -> T:
        """Restituisce il valore in cache se fresco, altrimenti invoca `fetch`.

        Un errore sollevato da `fetch` si propaga e non viene mai messo in
        cache: un fallimento transitorio non deve restare congelato per ore.
        """
        if self._cache is None:
            return fetch()

        cached = self._cache.get(key, default=None)
        if cached is not None:
            logger.debug("cache_hit", chiave=key)
            return cached  # type: ignore[no-any-return]  # diskcache non è tipizzato

        logger.debug("cache_miss", chiave=key, ttl=ttl_seconds)
        value = fetch()
        self._cache.set(key, value, expire=ttl_seconds)
        return value

    def clear(self) -> None:
        if self._cache is not None:
            self._cache.clear()

    def close(self) -> None:
        if self._cache is not None:
            self._cache.close()

    def __enter__(self) -> DataCache:
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()
