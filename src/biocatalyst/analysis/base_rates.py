"""Tassi storici di successo degli studi clinici, come termine di paragone.

Perché esiste questo modulo
---------------------------
Le probabilità dei tre scenari sono il numero meno fondato dell'intero report
e insieme quello che pesa di più: l'expected value si calcola su di esse. Prima
di questo modulo il modello scriveva "bull 40%" di sua iniziativa e il sistema
ci costruiva sopra un'aritmetica al centesimo — precisione senza fondamento.

Qui non si sostituisce il giudizio del modello: gli si mette accanto il tasso
storico, così lo scarto diventa visibile. Se il modello dà a una Fase 3 il 60%
di probabilità di successo mentre la base storica dice 58%, è una stima
ordinaria; se dà l'85%, deve motivarlo.

**Limite dichiarato, diverso dal resto del progetto.** Ogni altro dato qui
dentro arriva da un'API interrogabile e verificabile eseguendo il codice.
Questi numeri no: non esiste una fonte gratuita e interrogabile per i tassi di
transizione di fase. Sono valori di letteratura, trascritti a mano e fermi
all'anno della pubblicazione. Vanno riletti quando esce un aggiornamento, e il
report cita sempre la fonte accanto alla cifra perché il lettore possa
giudicarli.
"""

from __future__ import annotations

import re

from biocatalyst.models.analysis import PhaseBaseRate

#: Fonte dei tassi di transizione. Citata per esteso nel report.
SOURCE = "BIO, Informa Pharma Intelligence & QLS, «Clinical Development Success Rates 2011–2020»"

#: Fonte dei tassi per area terapeutica.
SOURCE_BY_AREA = SOURCE

#: Anno di riferimento dei dati: serve a far vedere quanto sono vecchi.
DATA_THROUGH_YEAR = 2020


#: Tassi complessivi, su tutte le aree terapeutiche. Sono i più citati della
#: letteratura e i più solidi: la casistica alla base è di decine di migliaia
#: di transizioni.
def _rate(phase: str, area: str, transition: float, approval: float | None) -> PhaseBaseRate:
    return PhaseBaseRate(
        phase=phase,
        area=area,
        transition_pct=transition,
        approval_pct=approval,
        source=SOURCE,
        data_through_year=DATA_THROUGH_YEAR,
    )


OVERALL: dict[str, PhaseBaseRate] = {
    "PHASE1": _rate("PHASE1", "all indications", 52.0, 7.9),
    "PHASE2": _rate("PHASE2", "all indications", 28.9, 15.1),
    "PHASE3": _rate("PHASE3", "all indications", 57.8, 52.4),
    "PHASE4": _rate("PHASE4", "all indications", 90.6, 90.6),
}

#: Probabilità di arrivare all'approvazione partendo dalla Fase 1, per area.
#: Si usano solo come contesto qualitativo ("l'oncologia è la disciplina con la
#: percentuale più bassa"), non per rimpiazzare i tassi di transizione: il
#: dettaglio per area e per fase insieme è meno solido e più variabile fra le
#: pubblicazioni.
APPROVAL_FROM_PHASE1_BY_AREA: dict[str, float] = {
    "oncology": 5.3,
    "hematology": 23.9,
    "infectious disease": 19.1,
    "metabolic": 15.4,
    "cardiovascular": 25.5,
    "neurology": 9.4,
    "psychiatry": 6.2,
    "autoimmune": 15.1,
    "respiratory": 12.8,
    "ophthalmology": 17.1,
}

#: Parole che identificano l'area terapeutica dalle condizioni dello studio.
#: Le sigle vanno confrontate come parole intere: "ALL" (leucemia linfoblastica
#: acuta) come sottostringa comparirebbe in "allergy" e "small".
_AREA_KEYWORDS: dict[str, tuple[str, ...]] = {
    "oncology": (
        "cancer",
        "carcinoma",
        "tumor",
        "tumour",
        "neoplasm",
        "melanoma",
        "sarcoma",
        "glioma",
        "glioblastoma",
        "oncology",
        "metastatic",
        "adenocarcinoma",
        "mesothelioma",
    ),
    "hematology": (
        "leukemia",
        "leukaemia",
        "lymphoma",
        "myeloma",
        "myelodysplastic",
        "anemia",
        "anaemia",
        "thrombocytopenia",
        "hemophilia",
        "haemophilia",
        "sickle cell",
        "aml",
        "cll",
        "cml",
        # "ALL" (leucemia linfoblastica acuta) è esclusa di proposito: come
        # parola intera coincide con l'inglese "all" e classificherebbe
        # "all solid tumors" fra i tumori del sangue.
        "mds",
        "myelofibrosis",
    ),
    "infectious disease": (
        "infection",
        "infectious",
        "hiv",
        "hepatitis",
        "influenza",
        "covid",
        "tuberculosis",
        "malaria",
        "sepsis",
        "bacterial",
        "viral",
    ),
    "neurology": (
        "alzheimer",
        "parkinson",
        "epilepsy",
        "multiple sclerosis",
        "als",
        "huntington",
        "migraine",
        "neuropathy",
        "dementia",
        "stroke",
        "muscular dystrophy",
    ),
    "psychiatry": (
        "depression",
        "schizophrenia",
        "bipolar",
        "anxiety",
        "ptsd",
        "addiction",
        "autism",
        "adhd",
    ),
    "cardiovascular": (
        "heart failure",
        "hypertension",
        "atherosclerosis",
        "myocardial",
        "cardiomyopathy",
        "arrhythmia",
        "thrombosis",
        "cardiovascular",
    ),
    "metabolic": (
        "diabetes",
        "obesity",
        "nash",
        "dyslipidemia",
        "hyperlipidemia",
        "metabolic syndrome",
        "gaucher",
        "fabry",
    ),
    "autoimmune": (
        "rheumatoid",
        "lupus",
        "psoriasis",
        "crohn",
        "colitis",
        "inflammatory bowel",
        "autoimmune",
        "vasculitis",
    ),
    "respiratory": ("asthma", "copd", "pulmonary fibrosis", "cystic fibrosis"),
    "ophthalmology": (
        "macular",
        "retinopathy",
        "glaucoma",
        "uveitis",
        "retinitis",
    ),
}


def detect_therapeutic_area(conditions: list[str]) -> str | None:
    """Area terapeutica dedotta dalle condizioni registrate su CT.gov.

    L'oncologia è valutata per ultima fra le due ematologiche affini: una
    leucemia è classificata come ematologia anche se il testo dice "cancer",
    perché i tassi di successo dei tumori del sangue sono nettamente più alti
    di quelli dei tumori solidi e confonderli darebbe il riferimento sbagliato.
    """
    testo = " ".join(conditions).lower()
    if not testo.strip():
        return None
    for area in ("hematology", *[a for a in _AREA_KEYWORDS if a != "hematology"]):
        for parola in _AREA_KEYWORDS[area]:
            if re.search(rf"\b{re.escape(parola)}s?\b", testo):
                return area
    return None


def highest_phase(phases: list[str]) -> str | None:
    """Fase più avanzata fra quelle dichiarate ("Phase 1/2" -> PHASE2)."""
    note = [p for p in phases if p in OVERALL]
    return max(note) if note else None


def base_rate_for(phases: list[str], conditions: list[str] | None = None) -> PhaseBaseRate | None:
    """Tasso storico di riferimento per uno studio.

    Restituisce il tasso di transizione complessivo della fase, con l'area
    terapeutica indicata quando riconosciuta. Non incrocia fase e area: quel
    dettaglio varia troppo fra le pubblicazioni per essere presentato come un
    numero solo.
    """
    fase = highest_phase(phases)
    if fase is None:
        return None
    base = OVERALL[fase]
    area = detect_therapeutic_area(conditions or [])
    if area is None:
        return base
    return _rate(
        fase,
        area,
        base.transition_pct,
        APPROVAL_FROM_PHASE1_BY_AREA.get(area, base.approval_pct),
    )
