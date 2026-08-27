"""Modalità screen: ricerca di nuove opportunità.

Pipeline a stadi, progettata attorno al costo: ogni stadio scarta titoli
usando solo dati gratuiti, e l'LLM interviene **una sola volta alla fine**
sui pochi finalisti. Eseguire la pipeline completa di analisi su 175 società
costerebbe centinaia di chiamate a pagamento per trovarne cinque.

1. Universo    — anagrafica SEC per codice SIC (nessun costo)
2. Prezzo e capitalizzazione — yfinance (nessun costo)
3. Catalizzatori — ClinicalTrials.gov (nessun costo)
4. Autonomia di cassa — SEC XBRL, solo per chi ha un catalizzatore
5. Ordinamento  — punteggio deterministico
6. Motivazione  — una chiamata LLM per tutti i finalisti insieme
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

from biocatalyst.analysis import (
    cash_runway_months,
    catalysts_from_trials,
    latest_cash,
    quarterly_burn_rate,
)
from biocatalyst.analysis.screening import (
    BALANCED,
    RiskAppetite,
    attractiveness_score,
    financing_risk_note,
    meets_phase_requirement,
    passes_price_and_size,
)
from biocatalyst.config import Settings, get_settings
from biocatalyst.data.base import DataProviderError
from biocatalyst.data.factory import DataProviders, build_data_providers
from biocatalyst.data.universe import DEFAULT_SIC_CODES, UniverseProvider
from biocatalyst.i18n import t
from biocatalyst.llm.base import LLMError, Message
from biocatalyst.llm.factory import provider_for_agent
from biocatalyst.llm.structured import complete_structured
from biocatalyst.log import get_logger
from biocatalyst.models.analysis import Catalyst
from biocatalyst.models.raw_data import ClinicalTrial
from biocatalyst.models.report import ReportLanguage
from biocatalyst.models.screening import ScreenCandidate, ScreenCriteria, ScreenResult

logger = get_logger(__name__)

#: Quante candidate restituire, come da requisito (5-8).
DEFAULT_MAX_CANDIDATES = 8

#: Tetto di sicurezza sui titoli esaminati: ogni titolo costa chiamate di rete
#: e tempo, e l'universo può crescere.
DEFAULT_MAX_UNIVERSE = 200

ScreenProgress = Callable[[str, int, int], None]

SCREEN_SYSTEM: dict[ReportLanguage, str] = {
    "it": """Sei un analista biotech. Per ciascuna società fornita scrivi una
motivazione sintetica (3-5 righe) del perché possa interessare a un investitore
e da due a tre rischi concreti.

Sii conservativo: i rischi devono essere specifici, non generici. Se i dati
forniti non bastano per una valutazione, dillo apertamente nella motivazione.
Non inventare dati clinici o finanziari che non ti sono stati dati.
Rispondi in italiano.""",
    "en": """You are a biotech analyst. For each company provided, write a
concise rationale (3-5 lines) explaining why it might interest an investor, and
two to three concrete risks.

Be conservative: risks must be specific, not generic. If the data provided is
insufficient for an assessment, say so openly in the rationale. Do not invent
clinical or financial data you were not given. Respond in English.""",
}


class CandidateNarrative(BaseModel):
    """Ciò che l'LLM aggiunge a una candidata già selezionata dal codice."""

    ticker: str
    rationale: str
    key_risks: list[str] = Field(default_factory=list)
    indication: str = ""


class ScreenNarratives(BaseModel):
    candidates: list[CandidateNarrative] = Field(default_factory=list)


def screen(
    criteria: ScreenCriteria | None = None,
    providers: DataProviders | None = None,
    settings: Settings | None = None,
    sic_codes: tuple[str, ...] = DEFAULT_SIC_CODES,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    max_universe: int = DEFAULT_MAX_UNIVERSE,
    language: ReportLanguage | None = None,
    appetite: RiskAppetite = BALANCED,
    on_progress: ScreenProgress | None = None,
) -> ScreenResult:
    """Esegue la ricerca e restituisce le candidate ordinate per attrattività."""
    settings = settings or get_settings()
    criteria = criteria or ScreenCriteria()
    language = language or settings.report_language
    owns_providers = providers is None
    providers = providers or build_data_providers(settings)

    def avanza(fase: str, fatto: int, totale: int) -> None:
        if on_progress is not None:
            on_progress(fase, fatto, totale)

    try:
        universe_provider = UniverseProvider(
            user_agent=settings.sec_edgar_user_agent,
            cache=providers.cache,
            timeout=settings.http_request_timeout_seconds,
            ttl_seconds=settings.cache_ttl_filing_seconds,
        )
        avanza("universo", 0, 1)
        universo = universe_provider.get_universe(sic_codes)
        tickers = sorted(universo)[:max_universe]
        logger.info("screen_universo", totale=len(universo), esaminati=len(tickers))

        selezionate = _filtra(tickers, universo, criteria, providers, avanza, appetite, language)
        selezionate.sort(key=lambda c: -c.attractiveness_score)
        finaliste = selezionate[:max_candidates]

        if finaliste:
            avanza("motivazioni", 0, 1)
            _aggiungi_motivazioni(finaliste, settings, language)

        return ScreenResult(
            criteria=criteria,
            candidates=finaliste,
            generated_at=datetime.now(UTC),
        )
    finally:
        if owns_providers:
            providers.close()


def _filtra(
    tickers: list[str],
    universo: dict[str, str],
    criteria: ScreenCriteria,
    providers: DataProviders,
    avanza: Callable[[str, int, int], None],
    appetite: RiskAppetite,
    language: ReportLanguage = "en",
) -> list[ScreenCandidate]:
    candidate: list[ScreenCandidate] = []
    totale = len(tickers)

    for indice, ticker in enumerate(tickers, start=1):
        avanza("titoli", indice, totale)
        try:
            candidato = _valuta_titolo(
                ticker, universo[ticker], criteria, providers, appetite, language
            )
        except DataProviderError as exc:
            # Un titolo che non risponde non deve fermare la ricerca sugli altri.
            logger.debug("titolo_saltato", ticker=ticker, motivo=str(exc)[:120])
            continue
        if candidato is not None:
            candidate.append(candidato)

    logger.info("screen_filtrati", esaminati=totale, superano=len(candidate))
    return candidate


def _valuta_titolo(
    ticker: str,
    company_name: str,
    criteria: ScreenCriteria,
    providers: DataProviders,
    appetite: RiskAppetite,
    language: ReportLanguage = "en",
) -> ScreenCandidate | None:
    # Stadio 2: prezzo e capitalizzazione, il filtro più economico.
    market = providers.market.get_market_data(ticker)
    esito = passes_price_and_size(market.price, market.market_cap_usd, criteria)
    if not esito.passed:
        return None

    # Stadio 3: serve un catalizzatore entro la finestra richiesta.
    sponsor = company_name.split(",")[0].strip()
    trials = providers.clinical_trials.get_trials_by_sponsor(sponsor)
    catalizzatori = catalysts_from_trials(
        trials, window_months=criteria.catalyst_window_months, language=language
    )
    if not catalizzatori:
        return None

    catalizzatore = catalizzatori[0]
    trial = _trial_del_catalizzatore(trials, catalizzatore)
    fasi = trial.phase if trial else []
    if fasi and not meets_phase_requirement(fasi, criteria.min_pipeline_phase):
        return None

    # Stadio 4: autonomia di cassa, solo per chi è arrivato fin qui.
    runway = _runway(ticker, providers)

    punteggio = attractiveness_score(
        catalyst=catalizzatore,
        criteria=criteria,
        market_cap=market.market_cap_usd,
        cash_runway_months=runway,
        phases=fasi,
        appetite=appetite,
    )

    assert market.price is not None and market.market_cap_usd is not None  # noqa: S101
    return ScreenCandidate(
        ticker=ticker,
        company_name=company_name,
        sector=t(language, "screen.sector"),
        price=market.price,
        market_cap_usd=market.market_cap_usd,
        main_drug=trial.brief_title if trial else t(language, "screen.drug_unknown"),
        indication=(
            ", ".join(trial.condition)
            if trial and trial.condition
            else t(language, "screen.indication_unknown")
        ),
        catalyst=catalizzatore,
        float_shares=market.float_shares,
        short_percent_of_float=market.short_percent_of_float,
        days_to_cover=market.short_ratio_days,
        cash_runway_months=runway,
        financing_risk=financing_risk_note(runway, catalizzatore, language=language),
        attractiveness_score=punteggio,
        exceptional=esito.exceptional,
    )


def _trial_del_catalizzatore(
    trials: list[ClinicalTrial], catalizzatore: Catalyst
) -> ClinicalTrial | None:
    nct = catalizzatore.source.split()[-1]
    return next((t for t in trials if t.nct_id == nct), None)


def _runway(ticker: str, providers: DataProviders) -> float | None:
    try:
        financials = providers.sec.get_quarterly_financials(ticker)
    except DataProviderError:
        return None
    cassa = latest_cash(financials)
    burn = quarterly_burn_rate(financials)
    return cash_runway_months(cassa[0] if cassa else None, burn)


def _aggiungi_motivazioni(
    candidate: list[ScreenCandidate],
    settings: Settings,
    language: ReportLanguage,
) -> None:
    """Una sola chiamata LLM per tutte le finaliste.

    Chiederle una per una moltiplicherebbe il costo per il numero di candidate
    senza migliorare le risposte: il contesto necessario è per titolo, ma il
    prompt di sistema e le istruzioni sono identici.
    """
    righe = []
    for c in candidate:
        data = c.catalyst.expected_date or c.catalyst.expected_date_window
        runway = f"{c.cash_runway_months:.1f} mesi" if c.cash_runway_months else "non disponibile"
        riga = (
            f"- {c.ticker} ({c.company_name}): prezzo ${c.price:,.2f}, "
            f"capitalizzazione ${c.market_cap_usd:,.0f}, autonomia di cassa {runway}, "
            f"studio '{c.main_drug}' su {c.indication}, catalizzatore atteso {data}"
        )
        if c.financing_risk:
            riga += f"\n  ATTENZIONE FINANZIARIA: {c.financing_risk}"
        righe.append(riga)

    prompt = (
        "Società selezionate dallo screening:\n"
        + "\n".join(righe)
        + "\n\nPer ciascuna indica il ticker, una motivazione sintetica e i rischi chiave.\n"
        "Dove compare un'attenzione finanziaria, valuta il compromesso in modo esplicito: "
        "la diluizione riduce il rialzo potenziale ma non lo annulla, mentre l'esaurimento "
        "della cassa senza accesso al capitale può interrompere lo studio. Sono due rischi "
        "diversi e vanno distinti."
    )

    try:
        provider = provider_for_agent("analyst", settings)
        risposta = complete_structured(
            provider,
            SCREEN_SYSTEM[language],
            [Message(role="user", content=prompt)],
            ScreenNarratives,
            max_tokens=8_000,
        )
    except LLMError as exc:
        logger.warning("motivazioni_screen_fallite", errore=str(exc)[:300])
        for c in candidate:
            c.rationale = t(language, "screen.rationale_failed")
        return

    per_ticker: dict[str, CandidateNarrative] = {n.ticker.upper(): n for n in risposta.candidates}
    for c in candidate:
        narrativa = per_ticker.get(c.ticker.upper())
        if narrativa is None:
            c.rationale = t(language, "screen.rationale_missing")
            continue
        c.rationale = narrativa.rationale
        c.key_risks = narrativa.key_risks
        if narrativa.indication and c.indication == t(language, "screen.indication_unknown"):
            c.indication = narrativa.indication


def screen_summary(result: ScreenResult) -> dict[str, Any]:
    """Riepilogo compatto, utile a CLI e UI."""
    return {
        "candidate": len(result.candidates),
        "generato": result.generated_at.isoformat(),
        "criteri": result.criteria.model_dump(),
    }
