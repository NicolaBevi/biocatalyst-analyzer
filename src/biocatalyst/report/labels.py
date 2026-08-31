"""Etichette e spiegazioni del report, in italiano e inglese.

Il report è destinato a chi non ha necessariamente familiarità con il gergo
del settore: accanto a ogni metrica compare una riga che dice **cosa
significa** e **come va letta**. Le spiegazioni sono testo fisso, non generato
dall'LLM, perché descrivono il metodo di calcolo del sistema e devono restare
identiche fra un report e l'altro.
"""

from __future__ import annotations

from biocatalyst.models.report import ReportLanguage

LABELS: dict[ReportLanguage, dict[str, str]] = {
    "it": {
        "report_title": "Report di due diligence",
        "generated_on": "Analisi generata il",
        "data_retrieved": "Dati interrogati il",
        "price": "Prezzo",
        "rating": "Giudizio",
        "analyst_target": "Target medio analisti",
        "main_catalyst": "Catalizzatore principale",
        "sec_pipeline": "Pipeline e risultati clinici",
        "sec_financial": "Analisi finanziaria",
        "sec_catalyst": "Catalizzatore principale",
        "sec_scenarios": "Scenari",
        "sec_ev": "Valore atteso",
        "sec_acquisition": "Probabilità di acquisizione",
        "sec_strategy": "Strategia operativa",
        "sec_sources": "Fonti e qualità del dato",
        "market_cap": "Capitalizzazione",
        "float_shares": "Flottante",
        "short_float": "Short sul flottante",
        "days_to_cover": "Giorni di copertura",
        "squeeze_score": "Punteggio short squeeze",
        "cash": "Liquidità disponibile",
        "burn_rate": "Consumo di cassa trimestrale",
        "runway": "Autonomia di cassa",
        "dilution_score": "Punteggio rischio diluizione",
        "atm": "ATM offering nei filing",
        "warrants": "Warrant nei filing",
        "tam": "Mercato potenziale",
        "months": "mesi",
        "scenario_bull": "RIALZISTA",
        "scenario_base": "CENTRALE",
        "scenario_bear": "RIBASSISTA",
        "probability": "probabilità",
        "target": "obiettivo",
        "conditions": "Condizioni necessarie",
        "investment": "Investimento",
        "shares": "Azioni acquistabili",
        "expected_value": "Valore atteso",
        "expected_roi": "Rendimento atteso",
        "reference_rate": "Cambio di riferimento",
        "potential_acquirers": "Potenziali acquirenti",
        "comparable_deals": "Operazioni comparabili recenti",
        "sources_consulted": "Fonti consultate",
        "missing_data": "Dati non reperiti",
        "unverified_figures": "Cifre non verificate dal sistema",
        "warnings": "Avvisi sulla qualità del dato",
        "none": "nessuno",
        "not_available": "non disponibile",
        "yes": "sì",
        "no": "no",
        "not_checked": "non verificato",
        "catalysts_list": "Catalizzatori attesi",
        "verified_facts": "Fatti verificati",
        "speculation": "Speculazioni di mercato",
        "sector_trend": "Andamento del settore",
        "estimated_date": "data stimata dallo sponsor",
        "overdue": "IN RITARDO",
        "event_driven": "endpoint a eventi",
        "verified_pricing": "Prezzo verificato (spesa Medicare)",
        "per_beneficiary": "per beneficiario/anno",
        "treated_population": "Popolazione trattata (Medicare)",
        "beneficiaries_unit": "beneficiari",
        "schedule_history": "Storico delle date dichiarate",
        "base_rate": "Tasso storico di successo (riferimento)",
        "base_rate_transition": "Studi che superano questa fase",
        "base_rate_approval": "Studi che arrivano all'approvazione",
        "base_rate_source": "Fonte",
        "first_declared": "Prima data annunciata",
        "current_declared": "Data attuale",
        "times_postponed": "Rinvii",
        "total_slip": "Slittamento complessivo",
        "glossary": "Come leggere questo report",
        "disclaimer_title": "Avvertenza",
    },
    "en": {
        "report_title": "Due diligence report",
        "generated_on": "Analysis generated on",
        "data_retrieved": "Data retrieved on",
        "price": "Price",
        "rating": "Rating",
        "analyst_target": "Mean analyst target",
        "main_catalyst": "Main catalyst",
        "sec_pipeline": "Pipeline and clinical results",
        "sec_financial": "Financial analysis",
        "sec_catalyst": "Main catalyst",
        "sec_scenarios": "Scenarios",
        "sec_ev": "Expected value",
        "sec_acquisition": "Acquisition likelihood",
        "sec_strategy": "Trading strategy",
        "sec_sources": "Sources and data quality",
        "market_cap": "Market capitalization",
        "float_shares": "Float",
        "short_float": "Short interest as % of float",
        "days_to_cover": "Days to cover",
        "squeeze_score": "Short squeeze score",
        "cash": "Cash on hand",
        "burn_rate": "Quarterly cash burn",
        "runway": "Cash runway",
        "dilution_score": "Dilution risk score",
        "atm": "ATM offering in filings",
        "warrants": "Warrants in filings",
        "tam": "Addressable market",
        "months": "months",
        "scenario_bull": "BULL",
        "scenario_base": "BASE",
        "scenario_bear": "BEAR",
        "probability": "probability",
        "target": "target",
        "conditions": "Required conditions",
        "investment": "Investment",
        "shares": "Shares purchasable",
        "expected_value": "Expected value",
        "expected_roi": "Expected return",
        "reference_rate": "Reference exchange rate",
        "potential_acquirers": "Potential acquirers",
        "comparable_deals": "Recent comparable deals",
        "sources_consulted": "Sources consulted",
        "missing_data": "Data not retrieved",
        "unverified_figures": "Figures the system could not verify",
        "warnings": "Data quality warnings",
        "none": "none",
        "not_available": "not available",
        "yes": "yes",
        "no": "no",
        "not_checked": "not checked",
        "catalysts_list": "Expected catalysts",
        "verified_facts": "Verified facts",
        "speculation": "Market speculation",
        "sector_trend": "Sector performance",
        "estimated_date": "date estimated by the sponsor",
        "overdue": "OVERDUE",
        "event_driven": "event-driven endpoint",
        "verified_pricing": "Verified pricing (Medicare spending)",
        "per_beneficiary": "per beneficiary per year",
        "treated_population": "Treated population (Medicare)",
        "beneficiaries_unit": "beneficiaries",
        "schedule_history": "History of declared dates",
        "base_rate": "Historical success rate (reference)",
        "base_rate_transition": "Trials that clear this phase",
        "base_rate_approval": "Trials that reach approval",
        "base_rate_source": "Source",
        "first_declared": "First announced date",
        "current_declared": "Current date",
        "times_postponed": "Postponements",
        "total_slip": "Total slippage",
        "glossary": "How to read this report",
        "disclaimer_title": "Disclaimer",
    },
}

#: Spiegazione di ogni metrica: cosa misura e come va letta.
EXPLANATIONS: dict[ReportLanguage, dict[str, str]] = {
    "it": {
        "runway": (
            "Per quanti mesi la liquidità disponibile copre il ritmo di consumo attuale. "
            "Sotto i 12 mesi un aumento di capitale diventa probabile, sotto i 6 quasi certo: "
            "è il dato che più spesso determina una diluizione degli azionisti esistenti."
        ),
        "burn_rate": (
            "Media della perdita netta degli ultimi quattro trimestri. È un'approssimazione: "
            "include poste non monetarie (rivalutazione di warrant, compensi in azioni) che "
            "possono gonfiarla o sgonfiarla. Il consumo di cassa operativo esatto richiederebbe "
            "il rendiconto finanziario, non esposto dalle API usate."
        ),
        "squeeze_score": (
            "Indicatore da 0 a 100 del potenziale di short squeeze, calcolato combinando "
            "percentuale di flottante venduta allo scoperto (peso 45%), giorni di copertura "
            "(35%) e scarsità del flottante (20%). Non è una probabilità: serve a confrontare "
            "titoli fra loro."
        ),
        "dilution_score": (
            "Indicatore da 0 a 100 del rischio che gli azionisti vengano diluiti, calcolato da "
            "autonomia di cassa (peso 60%), presenza di un programma ATM nei filing (25%) e "
            "presenza di warrant (15%)."
        ),
        "days_to_cover": (
            "Quanti giorni di scambi medi servirebbero a chi è short per ricomprare tutte le "
            "azioni vendute allo scoperto. Più è alto, più è difficile uscire senza far salire "
            "il prezzo."
        ),
        "short_interest": (
            "FINRA rileva le posizioni corte solo due volte al mese e le pubblica con circa una "
            "settimana di ritardo: questo dato è quindi vecchio di due o tre settimane presso "
            "qualunque fonte, gratuita o a pagamento. La data di riferimento è indicata accanto "
            "al valore."
        ),
        "scenarios": (
            "I tre scenari sono forniti dal modello linguistico insieme alle rispettive "
            "probabilità, che sommano a 1. Le variazioni percentuali rispetto al prezzo "
            "corrente sono invece calcolate dal sistema."
        ),
        "expected_value": (
            "Valore atteso dell'investimento: media dei prezzi obiettivo pesata per le "
            "probabilità dei tre scenari, moltiplicata per le azioni acquistabili. Il calcolo è "
            "aritmetico e svolto dal sistema, non dal modello linguistico. È in dollari, la "
            "valuta in cui il titolo quota; il cambio EUR/USD è riportato solo come riferimento "
            "e il rischio di cambio non è modellato."
        ),
        "catalysts": (
            "Eventi attesi che possono muovere il prezzo, estratti dagli studi clinici "
            "registrati e ordinati per vicinanza temporale. Le date indicate come stimate sono "
            "dichiarazioni dello sponsor e slittano di frequente. Uno studio marcato IN RITARDO "
            "ha superato la data stimata pur risultando ancora attivo: la lettura non è "
            "avvenuta ed è quindi potenzialmente imminente. Se lo studio ha un endpoint a "
            "eventi (sopravvivenza), la sua durata dipende dal numero di eventi verificatisi e "
            "non dal calendario: un ritardo può indicare eventi più lenti del previsto, ma "
            "anche difficoltà operative."
        ),
        "verified_pricing": (
            "Il modello sceglie quale farmaco sia il comparatore di prezzo; questa cifra "
            "però non viene da lui, ma dai dati di spesa Medicare pubblicati da CMS: è la "
            "spesa media annua effettivamente sostenuta per un beneficiario trattato con "
            "quel farmaco. Copre la sola popolazione Medicare, quindi è un ordine di "
            "grandezza e non un prezzo di listino. Se manca, significa che il farmaco "
            "citato non compare nei dati Medicare e la stima resta non verificata."
        ),
        "schedule_history": (
            "ClinicalTrials.gov conserva ogni revisione della scheda di uno studio: questa "
            "tabella ricostruisce come la data di completamento attesa è cambiata nel tempo. "
            "Serve a distinguere un rinvio isolato — che può capitare a qualsiasi studio — da "
            "una serie di rinvii, che descrive uno studio più lento del previsto fin "
            "dall'inizio. È un dato misurato sul registro, non una deduzione: "
            "l'interpretazione resta al lettore."
        ),
        "unverified_figures": (
            "Queste cifre compaiono nel testo del report ma non corrispondono a nessun dato "
            "raccolto dalle fonti: vengono dalla conoscenza del modello linguistico. Non "
            "sono per forza sbagliate — spesso sono corrette — ma nessuno le ha verificate, "
            "e stampate accanto alle altre sembrerebbero avere la stessa solidità. È "
            "l'elenco di ciò che conviene controllare prima di farci affidamento. Il "
            "controllo è una rete, non una garanzia: fra i molti valori misurati di un "
            "report una cifra può coincidere per caso con un dato che non c'entra, quindi "
            "un elenco vuoto non dimostra che ogni numero sia fondato."
        ),
        "base_rate": (
            "Quota storica di studi che, arrivati a questo stadio, hanno superato la fase. "
            "Serve a dare un metro alle probabilità degli scenari qui sopra, che il modello "
            "linguistico stabilisce con un giudizio: se assegna allo scenario rialzista una "
            "probabilità molto lontana da questa, la differenza deve essere motivata dalle "
            "condizioni dello scenario. Attenzione: **non è la probabilità che il titolo "
            "salga**, ed è una media di settore che non conosce questo studio in "
            "particolare. A differenza degli altri dati del report non arriva da un'API "
            "interrogabile ma da una pubblicazione, citata qui sotto con l'anno: va "
            "considerata un ordine di grandezza."
        ),
        "treated_population": (
            "Numero di beneficiari Medicare effettivamente trattati con il farmaco "
            "comparabile nell'anno indicato. Non è la prevalenza della malattia, ma un "
            "riscontro misurato sulla popolazione realmente in terapia: se la stima di "
            "prevalenza qui sopra è di ordini di grandezza diversa, vale la pena chiedersi "
            "perché. Copre i soli assistiti Medicare, quindi è un limite inferiore."
        ),
        "tam": (
            "Stima del mercato potenziale del farmaco principale, prodotta dal modello "
            "linguistico a partire da dati di prevalenza e prezzi di terapie comparabili. È una "
            "stima di ordine di grandezza, non un dato di bilancio."
        ),
    },
    "en": {
        "runway": (
            "How many months the available cash covers at the current burn rate. Below 12 "
            "months a capital raise becomes likely, below 6 near certain: this is the figure "
            "that most often drives dilution of existing shareholders."
        ),
        "burn_rate": (
            "Average net loss over the last four quarters. It is an approximation: it includes "
            "non-cash items (warrant revaluation, share-based compensation) that can inflate or "
            "deflate it. Exact operating cash burn would require the cash flow statement, which "
            "the APIs used here do not expose."
        ),
        "squeeze_score": (
            "A 0-100 indicator of short squeeze potential, combining short interest as a "
            "percentage of float (45% weight), days to cover (35%) and float scarcity (20%). "
            "It is not a probability: it exists to rank stocks against one another."
        ),
        "dilution_score": (
            "A 0-100 indicator of the risk that shareholders get diluted, derived from cash "
            "runway (60% weight), the presence of an ATM program in the filings (25%) and the "
            "presence of warrants (15%)."
        ),
        "days_to_cover": (
            "How many average trading days short sellers would need to buy back every shorted "
            "share. The higher it is, the harder it is to exit without pushing the price up."
        ),
        "short_interest": (
            "FINRA measures short positions only twice a month and publishes them about a week "
            "later: this figure is therefore two to three weeks old at any source, free or paid. "
            "The reference date is shown next to the value."
        ),
        "scenarios": (
            "The three scenarios and their probabilities, which sum to 1, are supplied by the "
            "language model. The percentage changes against the current price are computed by "
            "the system."
        ),
        "expected_value": (
            "Expected value of the investment: the probability-weighted average of the three "
            "target prices, multiplied by the number of shares purchasable. The arithmetic is "
            "performed by the system, not by the language model. It is denominated in US "
            "dollars, the currency the stock trades in; the EUR/USD rate is shown for reference "
            "only and currency risk is not modeled."
        ),
        "catalysts": (
            "Expected price-moving events, extracted from registered clinical trials and sorted "
            "by proximity in time. Dates marked as estimated are sponsor statements and slip "
            "frequently. A trial marked OVERDUE has passed its estimated date while still being "
            "listed as active: the readout has not happened and is therefore potentially "
            "imminent. If the trial has an event-driven endpoint (survival), its duration "
            "depends on how many events have occurred rather than on the calendar: a delay may "
            "point to slower-than-expected events, but also to operational difficulties."
        ),
        "verified_pricing": (
            "The model chooses which drug serves as the pricing comparator; this figure, "
            "however, does not come from the model but from the Medicare spending data "
            "published by CMS: it is the average annual amount actually spent on one "
            "beneficiary treated with that drug. It covers the Medicare population only, "
            "so it is an order of magnitude rather than a list price. If absent, the drug "
            "cited is not in the Medicare data and the estimate remains unverified."
        ),
        "schedule_history": (
            "ClinicalTrials.gov keeps every revision of a study record: this table "
            "reconstructs how the expected completion date changed over time. It separates a "
            "one-off postponement — which can happen to any trial — from a series of them, "
            "which describes a study that has been running slower than planned from the "
            "start. It is measured from the registry, not inferred: the interpretation is "
            "left to the reader."
        ),
        "unverified_figures": (
            "These figures appear in the report text but match no data collected from the "
            "sources: they come from the language model's own knowledge. They are not "
            "necessarily wrong — often they are right — but nobody has verified them, and "
            "printed alongside the rest they would look equally solid. This is the list "
            "worth checking before relying on it. The check is a net, not a guarantee: among "
            "the many measured values in a report a figure can coincide by chance with an "
            "unrelated one, so an empty list does not prove every number is grounded."
        ),
        "base_rate": (
            "The share of trials that historically cleared this phase once they reached "
            "this stage. It gives a yardstick for the scenario probabilities above, which "
            "the language model sets by judgment: if it assigns the bull case a "
            "probability far from this figure, the gap should be justified by the scenario "
            "conditions. Note: this is **not the probability that the stock goes up**, and "
            "it is an industry average that knows nothing about this particular trial. "
            "Unlike the other figures in this report it does not come from a queryable API "
            "but from a publication, cited below with its year: treat it as an order of "
            "magnitude."
        ),
        "treated_population": (
            "Number of Medicare beneficiaries actually treated with the comparable drug in "
            "the year shown. This is not disease prevalence but a measured count of the "
            "population genuinely on therapy: if the prevalence estimate above is orders of "
            "magnitude away from it, that is worth questioning. It covers Medicare enrollees "
            "only, so it is a lower bound."
        ),
        "tam": (
            "Estimate of the lead drug's addressable market, produced by the language model "
            "from prevalence data and the pricing of comparable therapies. It is an "
            "order-of-magnitude estimate, not an accounting figure."
        ),
    },
}

DISCLAIMER: dict[ReportLanguage, str] = {
    "it": (
        "Questo report ha finalità puramente informative. È generato in parte da modelli "
        "linguistici e da dati di fonti pubbliche, e non costituisce consulenza finanziaria, "
        "raccomandazione di investimento o invito a investire. Verifica sempre i dati con le "
        "fonti primarie prima di qualsiasi decisione."
    ),
    "en": (
        "This report is for informational purposes only. It is generated in part by language "
        "models and from public data sources, and does not constitute financial advice, an "
        "investment recommendation or an invitation to invest. Always verify the figures "
        "against primary sources before making any decision."
    ),
}


def label(language: ReportLanguage, key: str) -> str:
    return LABELS[language].get(key, key)


def explanation(language: ReportLanguage, key: str) -> str:
    return EXPLANATIONS[language].get(key, "")
