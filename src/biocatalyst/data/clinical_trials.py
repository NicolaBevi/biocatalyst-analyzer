"""ClinicalTrials.gov API v2 (l'API v1 classica è stata ritirata a giugno 2024).

Due particolarità della fonte, gestite qui:
1. `query.spons` cerca sia tra gli sponsor principali sia tra i collaboratori:
   una società compare anche in studi altrui. Il filtro sul lead sponsor
   effettivo va quindi rifatto lato client.
2. Le date stimate possono essere parziali ("2027-04"): sono normalizzate al
   primo giorno del mese da `parse_flexible_date`.
3. Lo storico delle revisioni di un record sta su `/api/int/`, che **non fa
   parte dell'API v2 documentata**: è l'endpoint usato dalla pagina web del
   registro. Vale la pena appoggiarcisi perché il dato non è ottenibile
   altrimenti ed è molto informativo (vedi `get_schedule_history`), ma essendo
   interno può cambiare senza preavviso: ogni errore qui è trattato come
   "storia non disponibile" e non blocca mai il resto dell'analisi.
"""

from __future__ import annotations

import hashlib
from datetime import date
from typing import Any, ClassVar

from biocatalyst.data.base import (
    DataProviderError,
    HTTPDataProvider,
    RateLimiter,
    parse_flexible_date,
)
from biocatalyst.data.cache import DataCache
from biocatalyst.log import get_logger
from biocatalyst.models.raw_data import (
    ClinicalTrial,
    ScheduleRevision,
    TrialScheduleHistory,
)

logger = get_logger(__name__)

STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"
HISTORY_URL = "https://clinicaltrials.gov/api/int/studies/{nct_id}/history"
HISTORY_VERSION_URL = "https://clinicaltrials.gov/api/int/studies/{nct_id}/history/{version}"

#: Modulo che contiene le date di completamento. Verificato su REGAL: ogni
#: cambio della data risulta segnalato da questa etichetta, quindi le altre
#: versioni si possono saltare senza perdere informazione (10 richieste
#: diventano 3). La versione 0 non ha etichette perché è il deposito iniziale.
STATUS_MODULE_LABEL = "Study Status"

#: Una versione già pubblicata non cambia più: si può conservare a lungo.
#: Solo l'indice delle versioni va riletto per scoprire quelle nuove.
IMMUTABLE_VERSION_TTL = 30 * 86_400

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

    def get_schedule_history(self, nct_id: str) -> TrialScheduleHistory | None:
        """Storico delle date di completamento dichiarate per uno studio.

        Risponde a una domanda che il solo dato corrente non può risolvere: un
        ritardo è un episodio o un andamento? Su REGAL la data è stata spostata
        tre volte, da dicembre 2021 a dicembre 2025.

        Restituisce None se lo storico non è disponibile: è un
        approfondimento, non deve mai far fallire l'analisi.
        """
        try:
            indice = self._get_json(
                HISTORY_URL.format(nct_id=nct_id),
                ttl_seconds=self.trial_ttl_seconds,
                cache_key=f"ctgov:histindex:{nct_id}",
            )
        except DataProviderError as exc:
            logger.info("storico_studio_non_disponibile", nct_id=nct_id, errore=str(exc)[:200])
            return None

        versioni = indice.get("changes") or []
        if not versioni:
            return None

        da_leggere = [
            i
            for i, v in enumerate(versioni)
            if i == 0 or STATUS_MODULE_LABEL in (v.get("moduleLabels") or [])
        ]

        cambi: list[ScheduleRevision] = []
        prima: date | None = None
        precedente: date | None = None
        corrente: date | None = None

        for i in da_leggere:
            dichiarata = self._declared_completion(nct_id, i)
            if i == da_leggere[0]:
                prima = dichiarata
            elif dichiarata != precedente:
                cambi.append(
                    ScheduleRevision(
                        revised_on=parse_flexible_date(versioni[i].get("date")) or date.today(),
                        previous_date=precedente,
                        new_date=dichiarata,
                    )
                )
            precedente = dichiarata
            corrente = dichiarata

        return TrialScheduleHistory(
            nct_id=nct_id,
            revisions_total=len(versioni),
            first_declared_date=prima,
            current_declared_date=corrente,
            changes=cambi,
        )

    def _declared_completion(self, nct_id: str, version: int) -> date | None:
        """Data di completamento primario dichiarata in una singola versione."""
        try:
            payload = self._get_json(
                HISTORY_VERSION_URL.format(nct_id=nct_id, version=version),
                ttl_seconds=IMMUTABLE_VERSION_TTL,
                cache_key=f"ctgov:histver:{nct_id}:{version}",
            )
        except DataProviderError:
            return None
        stato = (payload.get("study", {}).get("protocolSection", {}).get("statusModule", {})) or {}
        struttura = stato.get("primaryCompletionDateStruct") or {}
        return parse_flexible_date(struttura.get("date"))


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
