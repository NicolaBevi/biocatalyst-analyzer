"""Catalogo dei messaggi rivolti all'utente, in inglese e italiano.

Serve perché i testi generati dal codice — non dall'LLM — comparivano nel
report nella lingua in cui erano stati scritti, a prescindere dalla lingua
scelta: un report in inglese conteneva "cassa non disponibile nei filing
XBRL" fra i dati mancanti. Tenerli sparsi in sei moduli li avrebbe fatti
divergere di nuovo alla prima modifica.

Ogni voce esiste in entrambe le lingue: un test lo verifica confrontando le
chiavi, così una traduzione dimenticata fallisce in CI invece di comparire
nel report.
"""

from __future__ import annotations

from typing import Any

from biocatalyst.models.report import ReportLanguage

MESSAGES: dict[str, dict[ReportLanguage, str]] = {
    # --- Etichette delle fonti (compaiono in "dati non reperiti") ------------
    "src.company_name_sec": {
        "en": "company name (SEC)",
        "it": "nome società (SEC)",
    },
    "src.company_name_yf": {
        "en": "company name (yfinance)",
        "it": "nome società (yfinance)",
    },
    "src.market_data": {
        "en": "market data (yfinance)",
        "it": "dati di mercato (yfinance)",
    },
    "src.financials": {
        "en": "quarterly financials (SEC XBRL)",
        "it": "bilanci trimestrali (SEC XBRL)",
    },
    "src.filing_signals": {
        "en": "ATM/warrant signals (SEC full-text search)",
        "it": "segnali ATM/warrant (ricerca full-text SEC)",
    },
    "src.trials": {
        "en": "clinical trials (ClinicalTrials.gov)",
        "it": "trial clinici (ClinicalTrials.gov)",
    },
    "src.approvals": {
        "en": "drug approvals (openFDA)",
        "it": "approvazioni farmaci (openFDA)",
    },
    "src.news": {
        "en": "company news (Finnhub)",
        "it": "notizie sul titolo (Finnhub)",
    },
    "src.sector_etf": {
        "en": "sector ETF performance (XBI/IBB)",
        "it": "andamento ETF di settore (XBI/IBB)",
    },
    "src.fx": {
        "en": "reference EUR/USD rate (Frankfurter)",
        "it": "cambio EUR/USD di riferimento (Frankfurter)",
    },
    "collect.no_company_name": {
        "en": "clinical trials and FDA approvals: cannot be queried without the company name",
        "it": "trial clinici e approvazioni FDA: non interrogabili senza la ragione sociale",
    },
    # --- Note sulle metriche finanziarie ------------------------------------
    "metrics.no_cash": {
        "en": "cash not available in the XBRL filings",
        "it": "cassa non disponibile nei filing XBRL",
    },
    "metrics.no_burn": {
        "en": ("burn rate not computable: fewer than two quarters with a reported net result"),
        "it": (
            "burn rate non calcolabile: meno di due trimestri con risultato economico disponibile"
        ),
    },
    "metrics.burn_zero": {
        "en": "burn rate is zero: the company is on average profitable over recent quarters",
        "it": "burn rate nullo: l'azienda risulta mediamente in utile sui trimestri recenti",
    },
    "metrics.runway_undefined": {
        "en": "cash runway undefined because the burn rate is zero",
        "it": "cash runway non definito perché il burn rate è nullo",
    },
    "metrics.runway_missing": {
        "en": "cash runway not computable: cash or burn rate missing",
        "it": "cash runway non calcolabile: mancano cassa o burn rate",
    },
    "metrics.no_squeeze": {
        "en": (
            "short squeeze score not computable: no short interest or float data "
            "(common for micro-caps)"
        ),
        "it": (
            "short squeeze score non calcolabile: nessun dato su short interest o "
            "flottante (frequente per i micro-cap)"
        ),
    },
    "metrics.no_dilution": {
        "en": "dilution risk score not computable: runway and filing signals both missing",
        "it": "dilution risk score non calcolabile: mancano runway e segnali dai filing",
    },
    # --- Avvisi sulla qualità del dato --------------------------------------
    "warn.target_too_high": {
        "en": (
            "Mean analyst target (${target:,.2f}) is {ratio:.1f} times the current price "
            "(${price:,.2f}): likely stale after a reverse split or a sharp decline. "
            "Verify at the source before relying on it."
        ),
        "it": (
            "Target medio analisti (${target:,.2f}) pari a {ratio:.1f} volte il prezzo "
            "corrente (${price:,.2f}): valore probabilmente non aggiornato dopo un "
            "raggruppamento di azioni o un forte ribasso. Da verificare alla fonte."
        ),
    },
    "warn.target_too_low": {
        "en": (
            "Mean analyst target (${target:,.2f}) is {ratio:.2f} times the current price "
            "(${price:,.2f}): anomalous, likely stale. Verify at the source before "
            "relying on it."
        ),
        "it": (
            "Target medio analisti (${target:,.2f}) pari a {ratio:.2f} volte il prezzo "
            "corrente (${price:,.2f}): valore anomalo, probabilmente non aggiornato. "
            "Da verificare alla fonte."
        ),
    },
    "warn.short_interest_stale": {
        "en": (
            "Short interest is {days} days old: FINRA measures it twice a month, so the "
            "figure is structurally lagging at any source, not just this one."
        ),
        "it": (
            "Lo short interest è riferito a {days} giorni fa: FINRA lo rileva due volte "
            "al mese, quindi il dato è strutturalmente arretrato per qualunque fonte, "
            "non solo per questa."
        ),
    },
    # --- Note temporali sui catalizzatori -----------------------------------
    "cat.overdue": {
        "en": (
            "estimated date passed {days} days ago ({months:.1f} months): the trial is "
            "still listed as active, the readout is pending"
        ),
        "it": (
            "data stimata superata da {days} giorni ({months:.1f} mesi): lo studio "
            "risulta ancora attivo, la lettura è attesa"
        ),
    },
    "cat.overdue_share": {
        "en": ", i.e. {share:.0f}% of the planned duration of {planned:.0f} months",
        "it": ", pari al {share:.0f}% della durata pianificata di {planned:.0f} mesi",
    },
    "cat.event_driven_note": {
        "en": (
            ". Event-driven endpoint: the duration depends on how many events have "
            "occurred rather than on the calendar, so a delay may indicate that events "
            "are accruing more slowly than modeled"
        ),
        "it": (
            ". Endpoint a eventi: la durata dipende dal numero di eventi verificatisi, "
            "non dal calendario, quindi un ritardo può indicare che gli eventi si "
            "accumulano più lentamente del previsto"
        ),
    },
    "cat.estimated": {
        "en": "date estimated by the sponsor",
        "it": "data stimata dallo sponsor",
    },
    "cat.phase_unknown": {"en": "Clinical trial", "it": "Studio clinico"},
    "cat.phase_na": {"en": "Phase not applicable", "it": "Fase non applicabile"},
    "cat.phase_prefix": {"en": "Phase ", "it": "Fase "},
    "cat.phase_early": {"en": "Early Phase 1", "it": "Fase 1 precoce"},
    "cat.none_found": {
        "en": (
            "no future catalyst identified from the registered trials (no active study "
            "with a pending primary completion date)"
        ),
        "it": (
            "nessun catalizzatore futuro identificato dai trial registrati (nessuno "
            "studio attivo con data di completamento primario attesa)"
        ),
    },
    # --- Esiti degli agenti --------------------------------------------------
    "agent.no_lead_trial": {
        "en": "clinical assessment and TAM not produced: no reference study available",
        "it": "valutazione clinica e TAM non prodotti: nessuno studio di riferimento disponibile",
    },
    "agent.assessment_failed": {
        "en": "clinical assessment and TAM estimate not produced: {error}",
        "it": "valutazione clinica e stima del TAM non prodotte: {error}",
    },
    "agent.market_failed": {
        "en": "market context analysis not produced: {error}",
        "it": "analisi del contesto di mercato non prodotta: {error}",
    },
    "agent.market_unavailable": {
        "en": "Market context unavailable: the summary was not produced.",
        "it": "Contesto di mercato non disponibile: la sintesi non è stata prodotta.",
    },
    # --- TAM non disponibile --------------------------------------------------
    "tam.indication_unknown": {"en": "not determined", "it": "non determinata"},
    "tam.not_available": {"en": "not available", "it": "non disponibile"},
    "tam.not_produced": {
        "en": (
            "TAM estimate not produced: no usable reference study, or the model call "
            "did not succeed."
        ),
        "it": (
            "Stima del TAM non prodotta: nessuno studio di riferimento utilizzabile "
            "o chiamata al modello non riuscita."
        ),
    },
    # --- Screening ------------------------------------------------------------
    "screen.financing_risk": {
        "en": (
            "Cash covers {runway:.1f} months against the {gap:.1f} months remaining to the "
            "catalyst: {uncovered:.1f} months uncovered. A capital raise before the readout "
            "is likely and will dilute existing shareholders. Note the worse tail: without "
            "access to capital the trial can be halted, which is a different and more "
            "serious risk than dilution alone."
        ),
        "it": (
            "La liquidità copre {runway:.1f} mesi contro i {gap:.1f} che mancano al "
            "catalizzatore: {uncovered:.1f} mesi scoperti. Un aumento di capitale prima "
            "della lettura dei dati è probabile e diluirà gli azionisti attuali. "
            "Attenzione alla coda peggiore: senza accesso al capitale lo studio può "
            "essere interrotto, il che è un rischio diverso e più grave della sola "
            "diluizione."
        ),
    },
    "screen.rationale_failed": {
        "en": (
            "Rationale not produced: the model call did not succeed. The quantitative "
            "data remains valid."
        ),
        "it": (
            "Motivazione non prodotta: la chiamata al modello non è riuscita. "
            "I dati quantitativi restano validi."
        ),
    },
    "screen.rationale_missing": {
        "en": "The model did not return a rationale for this stock.",
        "it": "Motivazione non fornita dal modello per questo titolo.",
    },
    "screen.sector": {"en": "Biotechnology", "it": "Biotecnologie"},
    "screen.drug_unknown": {"en": "not determined", "it": "non determinato"},
    "screen.indication_unknown": {"en": "not determined", "it": "non determinata"},
}


def t(language: ReportLanguage, key: str, **params: Any) -> str:
    """Messaggio localizzato. Una chiave sconosciuta torna com'è, invece di
    sollevare: un testo grezzo in pagina è meno grave di un report non generato."""
    voce = MESSAGES.get(key)
    if voce is None:
        return key
    testo = voce.get(language) or voce["en"]
    return testo.format(**params) if params else testo
