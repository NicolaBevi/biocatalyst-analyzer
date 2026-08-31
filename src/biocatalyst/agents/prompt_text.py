"""Impalcatura dei prompt, nelle due lingue.

Il system prompt diceva "write the report in English" mentre l'intero
messaggio utente era in italiano — intestazioni, etichette dei dati,
istruzioni finali. Il modello a volte seguiva la lingua del messaggio invece
di quella dell'istruzione, e il report usciva metà in una lingua e metà
nell'altra. Con la cache delle risposte la scelta sbagliata restava poi
congelata per un giorno.

Qui la tensione è tolta alla radice: il prompt è nella stessa lingua del
report. Due test verificano che ogni chiave esista in entrambe le lingue e che
i segnaposto di `.format()` coincidano, altrimenti una traduzione andrebbe a
divergere in silenzio — è già successo con `i18n.py`.
"""

from __future__ import annotations

from typing import Any

from biocatalyst.models.report import ReportLanguage

PROMPTS: dict[str, dict[ReportLanguage, str]] = {
    # --- comuni --------------------------------------------------------------
    "na": {"it": "n/d", "en": "n/a"},
    "unavailable": {"it": "non disponibile", "en": "not available"},
    "unspecified": {"it": "non specificata", "en": "unspecified"},
    "unverified": {"it": "non verificato", "en": "not checked"},
    "yes": {"it": "sì", "en": "yes"},
    "no": {"it": "no", "en": "no"},
    "none_m": {"it": "- nessuno", "en": "- none"},
    "none_f": {"it": "- nessuna", "en": "- none"},
    # --- scrittore: blocchi --------------------------------------------------
    "w.overdue_tag": {"it": "[IN RITARDO]", "en": "[OVERDUE]"},
    "w.event_tag": {"it": "[ENDPOINT A EVENTI]", "en": "[EVENT-DRIVEN ENDPOINT]"},
    "w.source": {"it": "fonte", "en": "source"},
    "w.phase_na": {"it": "fase n/d", "en": "phase n/a"},
    "w.months": {"it": "mesi", "en": "months"},
    "w.completion": {"it": "completamento", "en": "completion"},
    "w.no_trials": {
        "it": "- nessuno studio registrato su ClinicalTrials.gov",
        "en": "- no trial registered on ClinicalTrials.gov",
    },
    "w.no_catalysts": {
        "it": "- nessun catalizzatore futuro identificato dai trial registrati",
        "en": "- no future catalyst identified from the registered trials",
    },
    "w.short_note": {
        "it": (
            " (dato riferito al {date}: FINRA lo rileva due volte al mese, quindi è "
            "strutturalmente arretrato)"
        ),
        "en": (" (as of {date}: FINRA measures it twice a month, so it is structurally lagging)"),
    },
    "w.base_rate": {
        "it": (
            "\nTASSO STORICO DI SUCCESSO (riferimento di letteratura, non una previsione "
            "su questa società)\n"
            "{label}: storicamente il {transition:.0f}% degli studi a questo stadio supera "
            "la fase.{approval} Fonte: {source}, dati fino al {year}.\n"
            "Usalo come ancoraggio per la probabilità dello scenario rialzista: se la tua "
            "stima se ne discosta molto, la motivazione deve stare nelle condizioni dello "
            "scenario. Non è un vincolo — questo studio può meritare più o meno della "
            "media — ma uno scostamento grande senza motivo è un errore.\n"
        ),
        "en": (
            "\nHISTORICAL SUCCESS RATE (literature reference, not a forecast about this "
            "company)\n"
            "{label}: historically {transition:.0f}% of trials at this stage clear the "
            "phase.{approval} Source: {source}, data through {year}.\n"
            "Use it to anchor the bull scenario probability: if your estimate departs "
            "widely from it, the reason must be in the scenario conditions. It is not a "
            "constraint — this trial may deserve more or less than the average — but a "
            "large unexplained departure is an error.\n"
        ),
    },
    "w.base_rate_approval": {
        "it": " La probabilità di arrivare all'approvazione partendo da qui è del {pct:.0f}%.",
        "en": " The probability of reaching approval from here is {pct:.0f}%.",
    },
    "w.history": {
        "it": (
            "\nSTORICO DELLE DATE DELLO STUDIO DI RIFERIMENTO ({nct}) — dato misurato sul "
            "registro CT.gov, non stimato\n"
            "La data di completamento è stata modificata {n} volte: {moves}.{slip}\n"
            "Cita questo andamento quando parli del ritardo: distingue un rinvio isolato "
            "da una tendenza, e il lettore deve poterla vedere.\n"
        ),
        "en": (
            "\nDECLARED-DATE HISTORY FOR THE LEAD TRIAL ({nct}) — measured on the CT.gov "
            "registry, not estimated\n"
            "The completion date has been revised {n} times: {moves}.{slip}\n"
            "Cite this pattern when you discuss the delay: it separates a one-off "
            "postponement from a trend, and the reader must be able to see it.\n"
        ),
    },
    "w.history_move": {
        "it": "il {date} da {previous} a {new}",
        "en": "on {date} from {previous} to {new}",
    },
    "w.history_slip": {
        "it": " Slittamento complessivo dalla prima data annunciata: {months:.0f} mesi.",
        "en": " Cumulative slippage from the first announced date: {months:.0f} months.",
    },
    "w.clinical": {
        "it": (
            "\nVALUTAZIONE CLINICA DELLO STUDIO DI RIFERIMENTO\n"
            "Disegno: {design}\n"
            "Endpoint primario: {endpoint}\n"
            "Popolazione e comparatore: {population}\n"
            "Potenza statistica: {power}\n"
            "Precedenti storici: {precedent}\n"
        ),
        "en": (
            "\nCLINICAL ASSESSMENT OF THE LEAD TRIAL\n"
            "Design: {design}\n"
            "Primary endpoint: {endpoint}\n"
            "Population and comparator: {population}\n"
            "Statistical power: {power}\n"
            "Historical precedent: {precedent}\n"
        ),
    },
    "w.tam": {
        "it": (
            "\nMERCATO POTENZIALE\n"
            "Indicazione: {indication}\n"
            "Prevalenza (stimata dall'analista): {prevalence}\n"
            "Prezzo comparabile (stimato dall'analista): {pricing}\n"
            "Note metodologiche: {notes}\n"
        ),
        "en": (
            "\nADDRESSABLE MARKET\n"
            "Indication: {indication}\n"
            "Prevalence (analyst estimate): {prevalence}\n"
            "Comparable pricing (analyst estimate): {pricing}\n"
            "Methodology notes: {notes}\n"
        ),
    },
    "w.verified_pricing": {
        "it": (
            "PREZZO VERIFICATO (dato misurato, fonte CMS — prevale sulla stima qui sopra): "
            "{drug}, ${amount:,.0f} di spesa media annua per beneficiario Medicare "
            "(Part {part}, {year}).\n"
        ),
        "en": (
            "VERIFIED PRICING (measured, source CMS — takes precedence over the estimate "
            "above): {drug}, ${amount:,.0f} average annual spend per Medicare beneficiary "
            "(Part {part}, {year}).\n"
        ),
    },
    "w.treated_population": {
        "it": (
            "POPOLAZIONE TRATTATA (dato misurato): {count:,} beneficiari Medicare in "
            "terapia con {drug} nel {year}. È un limite inferiore alla popolazione totale, "
            "non la prevalenza della malattia: se la stima di prevalenza qui sopra è di "
            "ordini di grandezza diversa, segnalalo.\n"
        ),
        "en": (
            "TREATED POPULATION (measured): {count:,} Medicare beneficiaries on {drug} in "
            "{year}. This is a lower bound on the total population, not disease "
            "prevalence: if the prevalence estimate above is orders of magnitude away from "
            "it, say so.\n"
        ),
    },
    "w.pricing_instruction": {
        "it": (
            "Quando citi un prezzo di riferimento usa la cifra verificata e dì che viene "
            "da CMS. Se la stima dell'analista se ne discosta molto, spiega la differenza "
            "(listino contro spesa netta) invece di ignorarla.\n"
        ),
        "en": (
            "When you quote a reference price use the verified figure and say it comes "
            "from CMS. If the analyst estimate departs widely from it, explain the "
            "difference (list price versus net spend) rather than ignoring it.\n"
        ),
    },
    "w.market": {
        "it": (
            "\nCONTESTO DI MERCATO\n"
            "Note macro: {macro}\n"
            "Fatti verificati:\n{facts}\n"
            "Speculazioni di mercato:\n{speculation}\n"
        ),
        "en": (
            "\nMARKET CONTEXT\n"
            "Macro notes: {macro}\n"
            "Verified facts:\n{facts}\n"
            "Market speculation:\n{speculation}\n"
        ),
    },
    "w.main": {
        "it": """Redigi il report di due diligence per {header}.

DATI DI MERCATO
Prezzo corrente: ${price}
Capitalizzazione: ${market_cap}
Flottante: {float_shares} azioni
Short sul flottante: {short_pct}{short_note}
Giorni di copertura: {days_to_cover}
Target medio analisti: ${analyst_target}

METRICHE FINANZIARIE (calcolate, riferite al {as_of})
Burn rate trimestrale: ${burn}
Cash runway: {runway}
Short squeeze score: {squeeze}
Dilution risk score: {dilution}
ATM offering nei filing: {atm}
Warrant nei filing: {warrant}

PIPELINE CLINICA REGISTRATA (tutti gli studi noti)
{pipeline}

CATALIZZATORI ATTESI (studi da cui si aspetta ancora una lettura)
{catalysts}
{blocks}
DATI NON REPERITI
{missing}

Produci il report.

Nella panoramica della pipeline cita TUTTI gli asset rilevanti elencati sopra,
non solo quello approfondito: chi legge deve capire cosa compone il valore
della società. Se uno studio è marcato IN RITARDO spiegane il significato, e se
è anche a ENDPOINT A EVENTI valuta esplicitamente le due letture possibili
(eventi più lenti del previsto, oppure problemi operativi o di arruolamento)
senza sceglierne una come certa.

Ricorda: probabilità che sommano a 1.0, prezzi obiettivo in dollari coerenti
con il prezzo corrente, nessun calcolo di percentuali o valori attesi.
Scrivi ogni sezione in italiano.""",
        "en": """Write the due diligence report for {header}.

MARKET DATA
Current price: ${price}
Market cap: ${market_cap}
Float: {float_shares} shares
Short interest on float: {short_pct}{short_note}
Days to cover: {days_to_cover}
Mean analyst target: ${analyst_target}

FINANCIAL METRICS (computed, as of {as_of})
Quarterly burn rate: ${burn}
Cash runway: {runway}
Short squeeze score: {squeeze}
Dilution risk score: {dilution}
ATM offering in the filings: {atm}
Warrants in the filings: {warrant}

REGISTERED CLINICAL PIPELINE (every known trial)
{pipeline}

EXPECTED CATALYSTS (trials still awaiting a readout)
{catalysts}
{blocks}
DATA NOT RETRIEVED
{missing}

Produce the report.

In the pipeline overview cite EVERY relevant asset listed above, not only the
one analyzed in depth: the reader must understand what makes up the company's
value. If a trial is marked OVERDUE explain what that means, and if it is also
EVENT-DRIVEN explicitly weigh both possible readings (events accruing more
slowly than expected, or operational and enrollment problems) without
presenting either as certain.

Remember: probabilities summing to 1.0, target prices in dollars consistent
with the current price, no percentage or expected-value arithmetic.
Write every section in English.""",
    },
    # --- analista ------------------------------------------------------------
    "a.overdue": {
        "it": (
            "- ATTENZIONE: la data stimata di completamento è superata da {days} giorni "
            "e lo studio risulta ancora attivo: la lettura dei dati è attesa, non "
            "avvenuta.\n"
        ),
        "en": (
            "- WARNING: the estimated completion date passed {days} days ago and the "
            "trial is still listed as active: the readout is pending, not delivered.\n"
        ),
    },
    "a.event_driven": {
        "it": (
            "- L'endpoint primario è a eventi: la durata dipende dal numero di eventi "
            "verificatisi, non dal calendario. Valuta entrambe le letture possibili di un "
            "ritardo (eventi più lenti del previsto, oppure difficoltà operative) senza "
            "presentarne una come certa.\n"
        ),
        "en": (
            "- The primary endpoint is event-driven: duration depends on how many events "
            "have occurred, not on the calendar. Weigh both possible readings of a delay "
            "(events accruing more slowly than expected, or operational difficulties) "
            "without presenting either as certain.\n"
        ),
    },
    "a.history": {
        "it": (
            "- STORICO DELLE DATE (fonte: registro CT.gov, dato misurato): la data di "
            "completamento è stata modificata {n} volte — {moves}.{slip} Tieni conto di "
            "questo andamento nel valutare il ritardo: un rinvio isolato e una serie di "
            "rinvii ripetuti non hanno lo stesso significato.\n"
        ),
        "en": (
            "- DECLARED-DATE HISTORY (source: CT.gov registry, measured): the completion "
            "date has been revised {n} times — {moves}.{slip} Take this pattern into "
            "account when judging the delay: a one-off postponement and a run of repeated "
            "ones do not mean the same thing.\n"
        ),
    },
    "a.history_slip": {
        "it": (
            " Dalla prima data annunciata ({first}) a quella attuale ({current}) sono "
            "{months:.0f} mesi di slittamento."
        ),
        "en": (
            " From the first announced date ({first}) to the current one ({current}) that "
            "is {months:.0f} months of slippage."
        ),
    },
    "a.main": {
        "it": """Azienda: {company}

Studio di riferimento (quello col catalizzatore più vicino):
- Identificativo: {nct}
- Titolo: {title}
- Fase: {phase}
- Stato: {status}
- Numerosità: {enrollment} ({enrollment_type})
- Endpoint primario: {endpoint}
- Completamento atteso: {completion}
- Patologia: {condition}
{notes}
Valuta criticamente lo studio e stima il mercato potenziale del farmaco.
Nel campo comparable_drug_name indica il NOME COMMERCIALE di un solo farmaco
già approvato e commercializzato negli Stati Uniti che serva da riferimento di
prezzo per questa indicazione.
Rispondi in italiano.""",
        "en": """Company: {company}

Lead trial (the one with the nearest catalyst):
- Identifier: {nct}
- Title: {title}
- Phase: {phase}
- Status: {status}
- Enrollment: {enrollment} ({enrollment_type})
- Primary endpoint: {endpoint}
- Expected completion: {completion}
- Condition: {condition}
{notes}
Assess the trial critically and estimate the drug's addressable market.
In the comparable_drug_name field give the BRAND NAME of a single drug already
approved and marketed in the United States that serves as a pricing reference
for this indication.
Answer in English.""",
    },
    "a.enrollment_type_na": {"it": "tipo non indicato", "en": "type not stated"},
    # --- notizie -------------------------------------------------------------
    "n.main": {
        "it": """Società: {company}

Andamento del settore biotech:
{sector}

Notizie sul titolo degli ultimi {days} giorni:
{headlines}

Sintetizza il contesto di mercato. Nelle note macro considera il clima per le
small cap biotech (tassi di interesse, orientamento FDA, attività di fusioni e
acquisizioni nel settore). Rispondi in italiano.""",
        "en": """Company: {company}

Biotech sector performance:
{sector}

News on the stock over the last {days} days:
{headlines}

Summarize the market context. In the macro notes consider the climate for
small-cap biotech (interest rates, FDA posture, M&A activity in the sector).
Answer in English.""",
    },
    "n.no_sector": {"it": "- dato non disponibile", "en": "- data not available"},
    "n.no_news": {"it": "- nessuna notizia disponibile", "en": "- no news available"},
}


def pt(language: ReportLanguage, key: str, **params: Any) -> str:
    """Testo di prompt nella lingua del report.

    Una chiave assente restituisce la chiave stessa: un prompt con dentro
    `w.main` è vistoso e si trova subito, mentre un `KeyError` a metà pipeline
    farebbe perdere l'intera analisi già pagata.
    """
    voce = PROMPTS.get(key)
    if voce is None:
        return key
    testo = voce.get(language) or voce["en"]
    return testo.format(**params) if params else testo
