"""Agente 4: scrittura del report finale.

È l'unico agente che vede tutto il contesto accumulato.

Punto centrale del progetto: `ReportDraft` — lo schema che il modello deve
compilare — **non contiene alcun campo aritmetico**. Niente variazioni
percentuali, niente valore atteso, niente ROI. Il modello fornisce solo
probabilità, prezzi obiettivo e prosa; ogni calcolo avviene poi in
`analysis/`. Così la regola "l'aritmetica la fa il codice" non è affidata a
un'istruzione nel prompt, ma resa strutturalmente impossibile da violare.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from biocatalyst.agents.base import (
    KEY_ANALYSIS,
    KEY_MARKET_CONTEXT,
    KEY_MISSING_DATA,
    KEY_RAW_DATA,
    KEY_REPORT,
    AgentError,
    BaseAgent,
)
from biocatalyst.agents.prompts import WRITER_SYSTEM
from biocatalyst.analysis import (
    ScenarioInput,
    build_expected_value_analysis,
    build_scenario_analysis,
    collect_data_warnings,
)
from biocatalyst.analysis.claims import collect_known_values, unverified_figures
from biocatalyst.data.base import collect_safely
from biocatalyst.data.factory import DataProviders
from biocatalyst.i18n import t
from biocatalyst.llm.base import BaseLLMProvider, Message
from biocatalyst.llm.structured import complete_structured
from biocatalyst.log import get_logger
from biocatalyst.models.analysis import AnalysisBundle, MarketContext, TAMEstimate
from biocatalyst.models.raw_data import ClinicalTrial, CompanyRawData
from biocatalyst.models.report import (
    AcquisitionAssessment,
    Rating,
    Report,
    ReportLanguage,
    ReportSections,
    SourceEntry,
    SourceQuality,
)

logger = get_logger(__name__)


class ScenarioDraft(BaseModel):
    """Uno scenario come lo fornisce il modello: nessun campo calcolato."""

    probability: float = Field(ge=0, le=1, description="Probabilità fra 0 e 1")
    target_price: float = Field(gt=0, description="Prezzo obiettivo in USD")
    conditions: str = Field(description="Condizioni necessarie perché si realizzi")


class ReportDraft(BaseModel):
    """Ciò che il modello produce. Volutamente privo di ogni valore aritmetico."""

    rating: Rating
    main_catalyst: str = Field(description="Nome del catalizzatore principale")
    pipeline_and_clinical_results: str = Field(
        description="Panoramica della pipeline e focus sull'asset col catalizzatore più vicino"
    )
    catalyst_analysis: str = Field(
        description=(
            "Analisi del catalizzatore principale: tempistica, fonte, probabilità di esito positivo"
        )
    )
    operational_strategy: str = Field(
        description=(
            "Strategia operativa: sell the news, livelli di prezzo, timing di ingresso e uscita"
        )
    )
    bull: ScenarioDraft
    base: ScenarioDraft
    bear: ScenarioDraft
    acquisition_probability_pct: float = Field(ge=0, le=100)
    potential_acquirers: list[str] = Field(default_factory=list)
    comparable_deals: list[str] = Field(default_factory=list)


class ReportWriterAgent(BaseAgent):
    name: ClassVar[str] = "ReportWriter"
    requires: ClassVar[tuple[str, ...]] = (KEY_RAW_DATA, KEY_ANALYSIS)

    def __init__(
        self,
        provider: BaseLLMProvider,
        providers: DataProviders,
        language: ReportLanguage = "en",
        max_tokens: int = 16_000,
    ) -> None:
        self.provider = provider
        self.providers = providers
        self.language = language
        self.max_tokens = max_tokens

    def _run(self, context: dict[str, Any]) -> dict[str, Any]:
        raw: CompanyRawData = context[KEY_RAW_DATA]
        analysis: AnalysisBundle = context[KEY_ANALYSIS]
        market_context: MarketContext | None = context.get(KEY_MARKET_CONTEXT)
        missing: list[str] = list(context.get(KEY_MISSING_DATA, []))

        price = raw.market_data.price if raw.market_data else None
        if price is None:
            raise AgentError(
                f"Impossibile redigere il report per {raw.ticker}: manca il prezzo corrente, "
                f"su cui si basano scenari ed expected value."
            )

        draft = complete_structured(
            self.provider,
            WRITER_SYSTEM[self.language],
            [Message(role="user", content=_build_prompt(raw, analysis, market_context, price))],
            ReportDraft,
            max_tokens=self.max_tokens,
        )

        # Da qui in poi è tutta aritmetica del codice.
        scenarios = build_scenario_analysis(
            current_price=price,
            bull=ScenarioInput(
                draft.bull.probability, draft.bull.target_price, draft.bull.conditions
            ),
            base=ScenarioInput(
                draft.base.probability, draft.base.target_price, draft.base.conditions
            ),
            bear=ScenarioInput(
                draft.bear.probability, draft.bear.target_price, draft.bear.conditions
            ),
        )

        # Il cambio non entra più nel calcolo (l'expected value è in dollari):
        # resta un riferimento per il lettore in area euro, quindi la sua
        # assenza non blocca più il report.
        rate = collect_safely(
            t(self.language, "src.fx"),
            lambda: self.providers.forex.get_eur_usd(),
            missing,
        )
        expected_value = build_expected_value_analysis(
            current_price_usd=price,
            scenarios=scenarios,
            eur_usd_rate=rate.rate if rate else None,
            rate_date=rate.rate_date if rate else None,
        )

        warnings = collect_data_warnings(
            analyst_target=raw.market_data.analyst_target_mean if raw.market_data else None,
            current_price=price,
            short_interest_days_old=_giorni_di_ritardo(raw),
            language=self.language,
        )

        report = Report(
            ticker=raw.ticker,
            company_name=raw.company_name,
            report_date=date.today(),
            generated_at=raw.retrieved_at,
            language=self.language,
            current_price=price,
            rating=draft.rating,
            average_analyst_target=raw.market_data.analyst_target_mean if raw.market_data else None,
            main_catalyst=draft.main_catalyst,
            sections=ReportSections(
                pipeline_and_clinical_results=draft.pipeline_and_clinical_results,
                catalyst_analysis=draft.catalyst_analysis,
                operational_strategy=draft.operational_strategy,
            ),
            financial_metrics=analysis.metrics,
            market_snapshot=raw.market_data,
            catalysts=analysis.catalysts,
            schedule_history=analysis.schedule_history,
            base_rate=analysis.base_rate,
            scenarios=scenarios,
            expected_value=expected_value,
            acquisition=AcquisitionAssessment(
                probability_pct=draft.acquisition_probability_pct,
                potential_acquirers=draft.potential_acquirers,
                comparable_deals=draft.comparable_deals,
            ),
            tam=analysis.tam or _tam_non_disponibile(self.language),
            source_quality=SourceQuality(
                sources_consulted=_sources(raw),
                missing_data=sorted(set(missing)),
                warnings=warnings,
            ),
        )
        report.source_quality.unverified_figures = _unverified(report, raw, analysis)

        context[KEY_REPORT] = report
        return context


def _unverified(report: Report, raw: CompanyRawData, analysis: AnalysisBundle) -> list[str]:
    """Cifre della prosa che non hanno riscontro in nessun dato raccolto.

    Il confronto avviene contro tutto ciò che il sistema ha misurato o
    calcolato, dati grezzi compresi: la numerosità di uno studio sta lì e non
    nel report, e senza guardarci risulterebbe "non verificata" pur essendo
    nostra.
    """
    noti = collect_known_values(report, raw, analysis)
    testo = "\n".join(
        (
            report.sections.pipeline_and_clinical_results,
            report.sections.catalyst_analysis,
            report.sections.operational_strategy,
        )
    )
    return [f"{f.text} — {f.context}" for f in unverified_figures(testo, noti)]


def _riga_pipeline(trial: ClinicalTrial) -> str:
    """Una riga per studio nella panoramica della pipeline."""
    tipo = trial.primary_completion_date_type
    qualifica = f" ({tipo.lower()})" if tipo else ""
    fasi = "/".join(trial.phase) or "fase n/d"
    return (
        f"- {trial.nct_id} | {fasi} | {trial.overall_status} | "
        f"completamento {trial.primary_completion_date or 'n/d'}{qualifica}"
        f" | {trial.brief_title[:90]}"
    )


def _giorni_di_ritardo(raw: CompanyRawData) -> int | None:
    """Da quanti giorni è fermo il dato sullo short interest."""
    if raw.market_data is None or raw.market_data.short_interest_date is None:
        return None
    return (datetime.now(UTC).date() - raw.market_data.short_interest_date).days


def _tam_non_disponibile(language: ReportLanguage = "en") -> TAMEstimate:
    """Segnaposto esplicito: dichiara l'assenza invece di lasciare il campo vuoto."""
    return TAMEstimate(
        indication=t(language, "tam.indication_unknown"),
        prevalence_estimate=t(language, "tam.not_available"),
        pricing_comparable=t(language, "tam.not_available"),
        methodology_notes=t(language, "tam.not_produced"),
    )


def _sources(raw: CompanyRawData) -> list[SourceEntry]:
    sources = [SourceEntry(name="yfinance (Yahoo Finance)", retrieved_at=raw.retrieved_at)]
    if raw.quarterly_financials:
        sources.append(SourceEntry(name="SEC EDGAR XBRL", retrieved_at=raw.retrieved_at))
    if raw.filing_signals:
        sources.append(
            SourceEntry(name="SEC EDGAR full-text search", retrieved_at=raw.retrieved_at)
        )
    if raw.clinical_trials:
        sources.append(SourceEntry(name="ClinicalTrials.gov API v2", retrieved_at=raw.retrieved_at))
    if raw.fda_approvals:
        sources.append(SourceEntry(name="openFDA Drugs@FDA", retrieved_at=raw.retrieved_at))
    return sources


def _build_prompt(
    raw: CompanyRawData,
    analysis: AnalysisBundle,
    market_context: MarketContext | None,
    price: float,
) -> str:
    m = analysis.metrics
    md = raw.market_data

    def num(value: float | None, unit: str = "", decimals: int = 2) -> str:
        return "non disponibile" if value is None else f"{value:,.{decimals}f}{unit}"

    catalysts = "\n".join(
        f"- #{c.imminence_rank} {c.expected_date}"
        + (" [IN RITARDO]" if c.is_overdue else "")
        + (" [ENDPOINT A EVENTI]" if c.is_event_driven else "")
        + f" — {c.name} (fonte: {c.source}"
        + (f"; {c.expected_date_window}" if c.expected_date_window else "")
        + ")"
        for c in analysis.catalysts[:8]
    )

    riferimento = ""
    br = analysis.base_rate
    if br is not None:
        riferimento = (
            f"\nTASSO STORICO DI SUCCESSO (riferimento di letteratura, non una previsione "
            f"su questa società)\n"
            f"{br.label}: storicamente il {br.transition_pct:.0f}% degli studi a questo "
            f"stadio supera la fase."
        )
        if br.approval_pct is not None:
            riferimento += (
                f" La probabilità di arrivare all'approvazione partendo da qui è del "
                f"{br.approval_pct:.0f}%."
            )
        riferimento += (
            f" Fonte: {br.source}, dati fino al {br.data_through_year}.\n"
            "Usalo come ancoraggio per la probabilità dello scenario rialzista: se la tua "
            "stima se ne discosta molto, la motivazione deve stare nelle condizioni dello "
            "scenario. Non è un vincolo — questo studio può meritare più o meno della "
            "media — ma uno scostamento grande senza motivo è un errore.\n"
        )

    storico = ""
    h = analysis.schedule_history
    if h is not None and h.changes:
        mosse = "; ".join(
            f"il {c.revised_on} da {c.previous_date} a {c.new_date}" for c in h.changes
        )
        mesi = h.total_slip_months
        storico = (
            f"\nSTORICO DELLE DATE DELLO STUDIO DI RIFERIMENTO ({h.nct_id}) — dato misurato "
            f"sul registro CT.gov, non stimato\n"
            f"La data di completamento è stata modificata {len(h.changes)} volte: {mosse}."
        )
        if mesi is not None and mesi > 0:
            storico += f" Slittamento complessivo dalla prima data annunciata: {mesi:.0f} mesi.\n"
        else:
            storico += "\n"
        storico += (
            "Cita questo andamento quando parli del ritardo: distingue un rinvio isolato "
            "da una tendenza, e il lettore deve poterla vedere.\n"
        )

    # Tutta la pipeline registrata, non solo gli studi con un catalizzatore
    # atteso: la panoramica deve elencare ogni asset, altrimenti il report
    # sembra riguardare una società con un solo farmaco.
    pipeline = "\n".join(
        _riga_pipeline(t)
        for t in sorted(
            raw.clinical_trials,
            key=lambda t: (
                t.primary_completion_date is None,
                t.primary_completion_date or date.min,
            ),
            reverse=True,
        )[:12]
    )

    clinical = ""
    if analysis.clinical_assessment is not None:
        a = analysis.clinical_assessment
        clinical = (
            f"\nVALUTAZIONE CLINICA DELLO STUDIO DI RIFERIMENTO\n"
            f"Disegno: {a.study_design_summary}\n"
            f"Endpoint primario: {a.primary_endpoint_evaluation}\n"
            f"Popolazione e comparatore: {a.population_and_comparator_evaluation}\n"
            f"Potenza statistica: {a.statistical_power_evaluation}\n"
            f"Precedenti storici: {a.historical_precedent_comparison}\n"
        )

    tam_text = ""
    if analysis.tam is not None:
        tam_text = (
            f"\nMERCATO POTENZIALE\n"
            f"Indicazione: {analysis.tam.indication}\n"
            f"Prevalenza (stimata dall'analista): {analysis.tam.prevalence_estimate}\n"
            f"Prezzo comparabile (stimato dall'analista): {analysis.tam.pricing_comparable}\n"
            f"Note metodologiche: {analysis.tam.methodology_notes}\n"
        )
        # Il prezzo verificato arriva dai dati CMS *dopo* la risposta
        # dell'analista: senza passarlo qui, il testo del report ripeterebbe la
        # cifra stimata mentre la tabella accanto mostra quella misurata.
        vp = analysis.tam.verified_pricing
        if vp is not None:
            tam_text += (
                f"PREZZO VERIFICATO (dato misurato, fonte CMS — prevale sulla stima "
                f"qui sopra): {vp.brand_name}, "
                f"${vp.avg_spend_per_beneficiary_usd:,.0f} di spesa media annua per "
                f"beneficiario Medicare (Part {vp.medicare_part}, {vp.year}).\n"
            )
            if vp.beneficiaries is not None:
                tam_text += (
                    f"POPOLAZIONE TRATTATA (dato misurato): {vp.beneficiaries:,} beneficiari "
                    f"Medicare in terapia con {vp.brand_name} nel {vp.year}. È un limite "
                    f"inferiore alla popolazione totale, non la prevalenza della malattia: "
                    f"se la stima di prevalenza qui sopra è di ordini di grandezza diversa, "
                    f"segnalalo.\n"
                )
            tam_text += (
                "Quando citi un prezzo di riferimento usa la cifra verificata e dì che "
                "viene da CMS. Se la stima dell'analista se ne discosta molto, spiega la "
                "differenza (listino contro spesa netta) invece di ignorarla.\n"
            )

    market_text = ""
    if market_context is not None:
        fatti = "\n".join(f"- {f}" for f in market_context.verified_facts[:8])
        voci = "\n".join(f"- {s}" for s in market_context.market_speculation[:8])
        market_text = (
            f"\nCONTESTO DI MERCATO\n"
            f"Note macro: {market_context.macro_notes}\n"
            f"Fatti verificati:\n{fatti or '- nessuno'}\n"
            f"Speculazioni di mercato:\n{voci or '- nessuna'}\n"
        )

    atm_text = "non verificato"
    warrant_text = "non verificato"
    if raw.filing_signals is not None:
        atm_text = "sì" if raw.filing_signals.atm_offering_mentioned else "no"
        warrant_text = "sì" if raw.filing_signals.warrant_mentioned else "no"

    short_note = ""
    if md and md.short_interest_date:
        short_note = (
            f" (dato riferito al {md.short_interest_date}: FINRA lo rileva due volte al mese, "
            f"quindi è strutturalmente arretrato)"
        )

    intestazione = f"{raw.company_name or raw.ticker} ({raw.ticker})"
    return f"""Redigi il report di due diligence per {intestazione}.

DATI DI MERCATO
Prezzo corrente: ${price}
Capitalizzazione: ${num(md.market_cap_usd if md else None, decimals=0)}
Flottante: {num(md.float_shares if md else None, decimals=0)} azioni
Short sul flottante: {num(md.short_percent_of_float if md else None, "%")}{short_note}
Giorni di copertura: {num(md.short_ratio_days if md else None)}
Target medio analisti: ${num(md.analyst_target_mean if md else None)}

METRICHE FINANZIARIE (calcolate, riferite al {m.as_of})
Burn rate trimestrale: ${num(m.quarterly_burn_rate_usd, decimals=0)}
Cash runway: {num(m.cash_runway_months, " mesi")}
Short squeeze score: {num(m.short_squeeze_score, "/100")}
Dilution risk score: {num(m.dilution_risk_score, "/100")}
ATM offering nei filing: {atm_text}
Warrant nei filing: {warrant_text}

PIPELINE CLINICA REGISTRATA (tutti gli studi noti)
{pipeline or "- nessuno studio registrato su ClinicalTrials.gov"}

CATALIZZATORI ATTESI (studi da cui si aspetta ancora una lettura)
{catalysts or "- nessun catalizzatore futuro identificato dai trial registrati"}
{riferimento}{storico}{clinical}{tam_text}{market_text}
DATI NON REPERITI
{chr(10).join(f"- {d}" for d in raw.missing_data) or "- nessuno"}

Produci il report.

Nella panoramica della pipeline cita TUTTI gli asset rilevanti elencati sopra,
non solo quello approfondito: chi legge deve capire cosa compone il valore
della società. Se uno studio è marcato IN RITARDO spiegane il significato, e se
è anche a ENDPOINT A EVENTI valuta esplicitamente le due letture possibili
(eventi più lenti del previsto, oppure problemi operativi o di arruolamento)
senza sceglierne una come certa.

Ricorda: probabilità che sommano a 1.0, prezzi obiettivo in dollari coerenti
con il prezzo corrente, nessun calcolo di percentuali o valori attesi."""
