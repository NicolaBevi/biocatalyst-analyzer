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
        "market_cap": "Market capitalisation",
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
            "dichiarazioni dello sponsor e slittano di frequente."
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
            "runway (60% weight), the presence of an ATM programme in the filings (25%) and the "
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
            "only and currency risk is not modelled."
        ),
        "catalysts": (
            "Expected price-moving events, extracted from registered clinical trials and sorted "
            "by proximity in time. Dates marked as estimated are sponsor statements and slip "
            "frequently."
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
