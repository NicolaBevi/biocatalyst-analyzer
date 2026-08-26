"""Estrazione e ordinamento dei catalizzatori clinici.

Deterministico per scelta: quali studi abbiano una lettura dati attesa, quanto
sia imminente e quanto pesi sul titolo è una questione di date e di fasi, non
di giudizio. All'LLM resta la valutazione qualitativa.

Due nozioni di dominio codificate qui, entrambe nate da un caso reale (SELLAS,
studio REGAL di Fase 3 su galinpepimut-S):

1. **Uno studio in ritardo non è uno studio concluso.** Se la data di
   completamento primario è *stimata*, è già passata, e lo studio risulta
   ancora attivo, la lettura dei dati non è avvenuta: è **in ritardo**, quindi
   potenzialmente imminente. Scartarlo — come faceva la prima versione di
   questo modulo — significa perdere di vista l'asset che muove il titolo.

2. **Negli studi a eventi il ritardo è un'informazione, non un contrattempo.**
   Uno studio con endpoint di sopravvivenza si chiude quando si è verificato
   un numero prestabilito di eventi. Se gli eventi arrivano più lentamente del
   previsto lo studio dura di più, e su un braccio sperimentale questo può
   voler dire che i pazienti stanno vivendo più a lungo. Non è una certezza —
   un ritardo può nascere anche da problemi di arruolamento o operativi — ma è
   una lettura che il report deve poter fare, e per farla deve prima *vedere*
   lo studio.
"""

from __future__ import annotations

import re
from datetime import date

from biocatalyst.models.analysis import Catalyst
from biocatalyst.models.raw_data import ClinicalTrial

#: Stati che indicano uno studio ancora in corso: solo per questi la data di
#: completamento primario rappresenta un evento non ancora avvenuto.
ACTIVE_TRIAL_STATUSES = frozenset(
    {
        "RECRUITING",
        "ACTIVE_NOT_RECRUITING",
        "NOT_YET_RECRUITING",
        "ENROLLING_BY_INVITATION",
    }
)

#: Endpoint che si misurano contando eventi nel tempo: lo studio si chiude al
#: raggiungimento di un numero prestabilito di eventi, non a una data fissa.
_EVENT_DRIVEN_PHRASES = (
    "overall survival",
    "progression-free survival",
    "progression free survival",
    "event-free survival",
    "event free survival",
    "disease-free survival",
    "disease free survival",
    "relapse-free survival",
    "relapse free survival",
    "recurrence-free survival",
    "time to progression",
    "time to event",
    "time to death",
    "duration of response",
    "survival rate",
)

#: Sigle degli stessi endpoint. Vanno confrontate come parole intere: "os"
#: come sottostringa comparirebbe in "dose", "response", "diagnosis".
_EVENT_DRIVEN_ABBREVIATIONS = frozenset({"os", "pfs", "efs", "dfs", "rfs", "ttp", "dor"})

#: Le fasi avanzate pesano di più sul prezzo: una Fase 3 è vicina al mercato,
#: una Fase 1 è un'ipotesi. Usato per scegliere l'asset di riferimento.
PHASE_MATERIALITY: dict[str, int] = {
    "PHASE4": 4,
    "PHASE3": 3,
    "PHASE2": 2,
    "PHASE1": 1,
    "EARLY_PHASE1": 0,
}


def is_event_driven(trial: ClinicalTrial) -> bool:
    """Vero se l'endpoint primario si misura contando eventi nel tempo."""
    measure = (trial.primary_outcome_measure or "").lower()
    if not measure:
        return False
    if any(frase in measure for frase in _EVENT_DRIVEN_PHRASES):
        return True
    parole = set(re.split(r"[^a-z0-9]+", measure))
    return bool(parole & _EVENT_DRIVEN_ABBREVIATIONS)


def is_pending(trial: ClinicalTrial, today: date | None = None) -> bool:
    """Vero se dallo studio ci si attende ancora una lettura dei dati.

    Uno studio attivo con data *stimata* già passata è in ritardo, non
    concluso: la lettura deve ancora arrivare. Una data *effettiva* passata
    significa invece che il completamento primario è avvenuto davvero.
    """
    if trial.overall_status not in ACTIVE_TRIAL_STATUSES:
        return False
    if trial.primary_completion_date is None:
        return False
    if trial.primary_completion_date_type == "ACTUAL":
        return trial.primary_completion_date >= (today or date.today())
    return True


def overdue_days(trial: ClinicalTrial, today: date | None = None) -> int:
    """Da quanti giorni la data stimata di completamento è stata superata."""
    reference = today or date.today()
    if trial.primary_completion_date is None or trial.primary_completion_date >= reference:
        return 0
    return (reference - trial.primary_completion_date).days


def materiality(trial: ClinicalTrial) -> int:
    """Quanto lo studio pesa sul titolo, dalla fase più avanzata dichiarata."""
    return max((PHASE_MATERIALITY.get(p.upper(), -1) for p in trial.phase), default=-1)


def catalysts_from_trials(
    trials: list[ClinicalTrial],
    today: date | None = None,
    window_months: int | None = None,
) -> list[Catalyst]:
    """Trasforma gli studi con una lettura ancora attesa in catalizzatori.

    L'ordinamento è per imminenza: gli studi in ritardo vengono per primi,
    perché la loro lettura può arrivare in qualunque momento.

    `window_months` limita ai catalizzatori attesi entro N mesi. Gli studi già
    in ritardo restano sempre inclusi: sono più imminenti di qualunque data
    futura, non meno.
    """
    reference = today or date.today()

    attesi: list[tuple[int, date, ClinicalTrial]] = []
    for trial in trials:
        if not is_pending(trial, reference):
            continue
        completion = trial.primary_completion_date
        assert completion is not None  # garantito da is_pending  # noqa: S101

        ritardo = overdue_days(trial, reference)
        fuori_finestra = (
            ritardo == 0
            and window_months is not None
            and _months_between(reference, completion) > window_months
        )
        if fuori_finestra:
            continue
        # Chiave di ordinamento: prima gli scaduti (0), poi i futuri (1).
        attesi.append((0 if ritardo else 1, completion, trial))

    attesi.sort(key=lambda item: (item[0], item[1], item[2].nct_id))

    catalysts: list[Catalyst] = []
    for rank, (_, completion, trial) in enumerate(attesi, start=1):
        ritardo = overdue_days(trial, reference)
        eventi = is_event_driven(trial)
        catalysts.append(
            Catalyst(
                name=f"{_phase_label(trial)}: {trial.brief_title}",
                catalyst_type="clinical_readout",
                expected_date=completion,
                expected_date_window=_nota_temporale(trial, ritardo, eventi),
                source=f"ClinicalTrials.gov {trial.nct_id}",
                imminence_rank=rank,
                is_overdue=ritardo > 0,
                overdue_days=ritardo or None,
                is_event_driven=eventi,
                phase_materiality=materiality(trial),
            )
        )
    return catalysts


def _nota_temporale(trial: ClinicalTrial, ritardo: int, eventi: bool) -> str | None:
    """Testo che qualifica la data: stimata, in ritardo, e cosa può significare."""
    if ritardo > 0:
        mesi = ritardo / 30.44
        base = (
            f"data stimata superata da {ritardo} giorni ({mesi:.1f} mesi): "
            f"lo studio risulta ancora attivo, la lettura è attesa"
        )
        if eventi:
            base += (
                ". Endpoint a eventi: un ritardo può indicare che gli eventi si "
                "accumulano più lentamente del previsto"
            )
        return base
    if trial.primary_completion_date_type == "ESTIMATED":
        return "data stimata dallo sponsor"
    return None


def _phase_label(trial: ClinicalTrial) -> str:
    if not trial.phase:
        return "Studio clinico"
    readable = "/".join(
        p.replace("PHASE", "Fase ").replace("EARLY_Fase 1", "Fase 1 precoce") for p in trial.phase
    )
    return readable.replace("NA", "Fase non applicabile")


def _months_between(start: date, end: date) -> int:
    return (end.year - start.year) * 12 + (end.month - start.month)
