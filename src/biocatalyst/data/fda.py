"""openFDA: approvazioni farmaci (endpoint Drugs@FDA).

Copre solo le approvazioni. Le orphan drug designation NON sono esposte da
openFDA né da nessun'altra API FDA: l'unica fonte ufficiale è un form web
(accessdata.fda.gov/scripts/opdlisting/oopd/) senza endpoint JSON, quindi sono
volutamente fuori dall'MVP (vedi CLAUDE.md).

Le date arrivano nel formato compatto "20160523", non ISO con trattini.
"""

from __future__ import annotations

from typing import Any, ClassVar

from biocatalyst.data.base import (
    DataNotFoundError,
    HTTPDataProvider,
    RateLimiter,
    parse_flexible_date,
    translates_validation_errors,
)
from biocatalyst.data.cache import DataCache
from biocatalyst.log import get_logger
from biocatalyst.models.raw_data import FDAApproval

logger = get_logger(__name__)

DRUGSFDA_URL = "https://api.fda.gov/drug/drugsfda.json"


class FDAProvider(HTTPDataProvider):
    # Senza API key: 240 richieste/minuto e 1.000 al giorno per IP.
    # 0.25s (~4 req/s) resta ampiamente sotto il limite al minuto.
    rate_limiter: ClassVar[RateLimiter] = RateLimiter(0.25)

    def __init__(
        self,
        cache: DataCache | None = None,
        timeout: int = 30,
        max_retries: int = 3,
        ttl_seconds: int = 86_400,
    ) -> None:
        super().__init__(cache=cache, timeout=timeout, max_retries=max_retries)
        self.ttl_seconds = ttl_seconds

    @translates_validation_errors
    def get_approvals_by_sponsor(self, sponsor: str, limit: int = 20) -> list[FDAApproval]:
        """Approvazioni note per uno sponsor.

        openFDA risponde 404 quando la ricerca non produce risultati: per una
        biotech clinical-stage senza farmaci approvati è l'esito normale, non
        un errore, quindi viene tradotto in lista vuota.
        """
        try:
            payload = self._get_json(
                DRUGSFDA_URL,
                params={"search": f'sponsor_name:"{sponsor}"', "limit": limit},
                ttl_seconds=self.ttl_seconds,
                cache_key=f"openfda:sponsor:{sponsor.lower()}:{limit}",
            )
        except DataNotFoundError:
            logger.info("nessuna_approvazione_fda", sponsor=sponsor)
            return []

        approvals: list[FDAApproval] = []
        for result in payload.get("results", []):
            approvals.extend(_parse_application(result))
        return approvals


def _parse_application(result: dict[str, Any]) -> list[FDAApproval]:
    application_number = result.get("application_number")
    sponsor_name = result.get("sponsor_name")
    if not application_number or not sponsor_name:
        return []

    products = result.get("products") or []
    submissions = result.get("submissions") or []

    # Si tiene la prima approvazione ("AP") come data di riferimento.
    approval_date = None
    submission_type = "UNKNOWN"
    for submission in submissions:
        if submission.get("submission_status") == "AP":
            approval_date = parse_flexible_date(submission.get("submission_status_date"))
            submission_type = submission.get("submission_type", "UNKNOWN")
            break

    approvals: list[FDAApproval] = []
    for product in products:
        product_name = product.get("brand_name") or product.get("active_ingredients", [{}])[0].get(
            "name"
        )
        if not product_name:
            continue
        approvals.append(
            FDAApproval(
                application_number=application_number,
                sponsor_name=sponsor_name,
                submission_type=submission_type,
                approval_date=approval_date,
                product_name=product_name,
                marketing_status=product.get("marketing_status"),
            )
        )
    return approvals
