"""Spesa Medicare per singolo farmaco (CMS), per ancorare il TAM a dati reali.

La stima del mercato potenziale è l'unica parte del report che poggiava
interamente sulla memoria del modello: "una terapia comparabile costa circa
X" era un'affermazione non verificabile. CMS pubblica la spesa Medicare
effettiva per ogni farmaco, compresa la **spesa media annua per
beneficiario** — un prezzo reale, di fonte governativa, citabile.

Il modello resta libero di scegliere *quale* farmaco sia il comparatore
giusto (è un giudizio di dominio); il sistema ne verifica il prezzo. Se il
farmaco non compare nei dati Medicare la verifica risulta assente e viene
dichiarata, invece di far passare la cifra del modello per un dato.

Due limiti da tenere presenti, entrambi riportati nel report:
- copre la sola popolazione Medicare (over 65 e disabili), quindi non è il
  prezzo di listino né il prezzo per un paziente commerciale;
- la spesa è al netto degli sconti negoziati solo in parte, quindi va letta
  come ordine di grandezza.
"""

from __future__ import annotations

from typing import Any, ClassVar

from biocatalyst.data.base import HTTPDataProvider, RateLimiter
from biocatalyst.data.cache import DataCache
from biocatalyst.log import get_logger
from biocatalyst.models.raw_data import DrugSpending

logger = get_logger(__name__)

#: Part D = farmaci in farmacia, Part B = farmaci somministrati in ambulatorio
#: (dove sta gran parte dell'oncologia infusa). Si cercano entrambi.
PART_D_URL = "https://data.cms.gov/data-api/v1/dataset/7e0b4365-fd63-4a29-8f5e-e0ac9f66a81b/data"
PART_B_URL = "https://data.cms.gov/data-api/v1/dataset/76a714ad-3a2c-43ac-b76d-9dadf8f7d890/data"

#: I due dataset usano nomi di campo leggermente diversi per la stessa misura.
_SPEND_PER_BENE_FIELDS = ("Avg_Spnd_Per_Bene_{year}", "Avg_Spndng_Per_Bene_{year}")

#: Dal più recente: si prende il primo anno con un valore utilizzabile.
CANDIDATE_YEARS = (2024, 2023, 2022, 2021, 2020)


class DrugPricingProvider(HTTPDataProvider):
    """Spesa Medicare per farmaco, dai dataset pubblici CMS (nessuna API key)."""

    rate_limiter: ClassVar[RateLimiter] = RateLimiter(0.3)

    def __init__(
        self,
        cache: DataCache | None = None,
        timeout: int = 30,
        max_retries: int = 3,
        ttl_seconds: int = 86_400,
    ) -> None:
        super().__init__(cache=cache, timeout=timeout, max_retries=max_retries)
        self.ttl_seconds = ttl_seconds

    def get_spending(self, drug_name: str) -> DrugSpending | None:
        """Spesa Medicare per un farmaco. None se non compare nei dati.

        Il nome può essere commerciale (Keytruda) o generico (pembrolizumab):
        si cercano entrambi i campi, prima in Part D e poi in Part B.
        """
        pulito = drug_name.strip()
        if not pulito:
            return None

        for url, parte in ((PART_D_URL, "D"), (PART_B_URL, "B")):
            for campo in ("Brnd_Name", "Gnrc_Name"):
                riga = self._search(url, campo, pulito)
                if riga is not None:
                    spesa = _to_spending(riga, parte)
                    if spesa is not None:
                        return spesa
        logger.info("farmaco_non_in_medicare", farmaco=pulito)
        return None

    def _search(self, url: str, field: str, value: str) -> dict[str, Any] | None:
        payload = self._get_json(
            url,
            params={f"filter[{field}]": value, "size": 1},
            ttl_seconds=self.ttl_seconds,
            cache_key=f"cms:{url[-8:]}:{field}:{value.lower()}",
        )
        if isinstance(payload, list) and payload:
            first: dict[str, Any] = payload[0]
            return first
        return None


def _to_spending(row: dict[str, Any], part: str) -> DrugSpending | None:
    """Estrae l'anno più recente con una spesa per beneficiario utilizzabile."""
    for year in CANDIDATE_YEARS:
        for template in _SPEND_PER_BENE_FIELDS:
            valore = row.get(template.format(year=year))
            if valore in (None, "", 0, "0"):
                continue
            try:
                per_bene = float(valore)
            except (TypeError, ValueError):
                continue
            if per_bene <= 0:
                continue
            return DrugSpending(
                brand_name=row.get("Brnd_Name") or "",
                generic_name=row.get("Gnrc_Name") or None,
                year=year,
                avg_spend_per_beneficiary_usd=per_bene,
                total_spend_usd=_safe_float(row.get(f"Tot_Spndng_{year}")),
                beneficiaries=_safe_int(row.get(f"Tot_Benes_{year}")),
                medicare_part=part,  # type: ignore[arg-type]
            )
    return None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(float(value)) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
