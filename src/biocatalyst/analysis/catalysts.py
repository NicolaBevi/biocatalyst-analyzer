"""Estrazione e ordinamento dei catalizzatori per imminenza temporale.

Deterministico per scelta: quali trial abbiano una lettura dati attesa e in
che ordine arrivi è una questione di date, non di giudizio. All'LLM resta la
valutazione qualitativa del singolo catalizzatore.
"""

from __future__ import annotations

from datetime import date

from biocatalyst.models.analysis import Catalyst
from biocatalyst.models.raw_data import ClinicalTrial

#: Stati che indicano uno studio ancora in corso: solo per questi la data di
#: completamento primario rappresenta un evento futuro.
ACTIVE_TRIAL_STATUSES = frozenset(
    {
        "RECRUITING",
        "ACTIVE_NOT_RECRUITING",
        "NOT_YET_RECRUITING",
        "ENROLLING_BY_INVITATION",
    }
)


def catalysts_from_trials(
    trials: list[ClinicalTrial],
    today: date | None = None,
    window_months: int | None = None,
) -> list[Catalyst]:
    """Trasforma i trial ancora attivi in catalizzatori ordinati per data.

    `window_months` limita ai catalizzatori attesi entro N mesi; None li
    include tutti. Gli studi conclusi o interrotti sono esclusi: la loro data
    di completamento è passata e non costituisce un evento atteso.
    """
    reference = today or date.today()

    upcoming: list[tuple[date, ClinicalTrial]] = []
    for trial in trials:
        if trial.overall_status not in ACTIVE_TRIAL_STATUSES:
            continue
        completion = trial.primary_completion_date
        if completion is None or completion < reference:
            continue
        if window_months is not None and _months_between(reference, completion) > window_months:
            continue
        upcoming.append((completion, trial))

    upcoming.sort(key=lambda item: (item[0], item[1].nct_id))

    catalysts: list[Catalyst] = []
    for rank, (completion, trial) in enumerate(upcoming, start=1):
        catalysts.append(
            Catalyst(
                name=f"{_phase_label(trial)}: {trial.brief_title}",
                catalyst_type="clinical_readout",
                expected_date=completion,
                # Le date stimate di ClinicalTrials.gov slittano spesso: la
                # distinzione fra stimata ed effettiva va portata nel report.
                expected_date_window=(
                    "data stimata dallo sponsor"
                    if trial.primary_completion_date_type == "ESTIMATED"
                    else None
                ),
                source=f"ClinicalTrials.gov {trial.nct_id}",
                imminence_rank=rank,
            )
        )
    return catalysts


def _phase_label(trial: ClinicalTrial) -> str:
    if not trial.phase:
        return "Studio clinico"
    readable = "/".join(
        p.replace("PHASE", "Fase ").replace("EARLY_Fase 1", "Fase 1 precoce") for p in trial.phase
    )
    return readable.replace("NA", "Fase non applicabile")


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)
