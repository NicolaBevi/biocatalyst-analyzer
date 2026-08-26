"""ClinicalTrials.gov API v2 (l'API v1 classica è stata ritirata a giugno 2024).

Due particolarità della fonte, gestite qui:
1. `query.spons` cerca sia tra gli sponsor principali sia tra i collaboratori:
   una società compare anche in studi altrui. Il filtro sul lead sponsor
   effettivo va quindi rifatto lato client.
2. Le date stimate possono essere parziali ("2027-04"): sono normalizzate al
   primo giorno del mese da `parse_flexible_date`.
"""

from __future__ import annotations

import hashlib
from typing import Any, ClassVar

from biocatalyst.data.base import (
    HTTPDataProvider,
    RateLimiter,
    parse_flexible_date,
)
from biocatalyst.data.cache import DataCache
from biocatalyst.log import get_logger
from biocatalyst.models.raw_data import ClinicalTrial

logger = get_logger(__name__)

STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"

#: La chiave di cache include l'impronta dei campi richiesti: aggiungerne uno
#: senza cambiarla farebbe servire all'infinito la risposta vecchia, priva del
#: campo nuovo, e il dato risulterebbe assente senza alcun errore.
_FIELDS_LIST = (
    "NCTId",
    "BriefTitle",
    "OverallStatus",
    "Phase",
    "LeadSponsorName",
    "EnrollmentCount",
    "EnrollmentType",
    "StartDate",
    "PrimaryCompletionDate",
    "PrimaryCompletionDateType",
    "Condition",
    "PrimaryOutcomeMeasure",
)
REQUESTED_FIELDS = ",".join(_FIELDS_LIST)
FIELDS_FINGERPRINT = hashlib.sha1(REQUESTED_FIELDS.encode()).hexdigest()[:8]


class ClinicalTrialsProvider(HTTPDataProvider):
    # L'ente non pubblica un limite ufficiale: ~1 req/s è la cortesia
    # raccomandata dalla comunità di sviluppatori.
    rate_limiter: ClassVar[RateLimiter] = RateLimiter(1.0)

    def __init__(
        self,
        cache: DataCache | None = None,
        timeout: int = 30,
        max_retries: int = 3,
        trial_ttl_seconds: int = 86_400,
    ) -> None:
        super().__init__(cache=cache, timeout=timeout, max_retries=max_retries)
        self.trial_ttl_seconds = trial_ttl_seconds

    def get_trials_by_sponsor(
        self, sponsor: str, page_size: int = 100, lead_sponsor_only: bool = True
    ) -> list[ClinicalTrial]:
        payload = self._get_json(
            STUDIES_URL,
            params={
                "query.spons": sponsor,
                "fields": REQUESTED_FIELDS,
                "pageSize": page_size,
                "countTotal": "true",
            },
            ttl_seconds=self.trial_ttl_seconds,
            cache_key=f"ctgov:spons:{sponsor.lower()}:{page_size}:{FIELDS_FINGERPRINT}",
        )

        trials: list[ClinicalTrial] = []
        for study in payload.get("studies", []):
            trial = _parse_study(study)
            if trial is None:
                continue
            if lead_sponsor_only and not _is_lead_sponsor(trial.lead_sponsor, sponsor):
                # query.spons trova anche gli studi in cui la società è solo
                # collaboratore: non fanno parte della sua pipeline.
                continue
            trials.append(trial)
        return trials


def _is_lead_sponsor(lead_sponsor: str | None, wanted: str) -> bool:
    if not lead_sponsor:
        return False
    return wanted.strip().lower() in lead_sponsor.strip().lower()


def _parse_study(study: dict[str, Any]) -> ClinicalTrial | None:
    protocol = study.get("protocolSection", {})
    identification = protocol.get("identificationModule", {})
    nct_id = identification.get("nctId")
    if not nct_id:
        return None

    status = protocol.get("statusModule", {})
    design = protocol.get("designModule", {})
    enrollment = design.get("enrollmentInfo", {}) or {}
    outcomes = protocol.get("outcomesModule", {})
    primary_outcomes = outcomes.get("primaryOutcomes") or []
    completion = status.get("primaryCompletionDateStruct", {}) or {}
    inizio = status.get("startDateStruct", {}) or {}
    sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
    lead_sponsor = (sponsor_module.get("leadSponsor") or {}).get("name")

    enrollment_type = enrollment.get("type")
    if enrollment_type not in ("ACTUAL", "ESTIMATED"):
        enrollment_type = None

    completion_type = completion.get("type")
    if completion_type not in ("ACTUAL", "ESTIMATED"):
        completion_type = None

    return ClinicalTrial(
        nct_id=nct_id,
        brief_title=identification.get("briefTitle", ""),
        phase=design.get("phases") or [],
        overall_status=status.get("overallStatus", "UNKNOWN"),
        enrollment_count=enrollment.get("count"),
        enrollment_type=enrollment_type,
        primary_outcome_measure=(primary_outcomes[0].get("measure") if primary_outcomes else None),
        start_date=parse_flexible_date(inizio.get("date")),
        primary_completion_date=parse_flexible_date(completion.get("date")),
        primary_completion_date_type=completion_type,
        condition=protocol.get("conditionsModule", {}).get("conditions") or [],
        lead_sponsor=lead_sponsor,
    )
