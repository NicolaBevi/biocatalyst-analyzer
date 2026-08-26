"""Rendering del report in Markdown.

Segue il formato richiesto nei requisiti, con due aggiunte: la data di
generazione accanto a quella di interrogazione dei dati, e una riga di
spiegazione sotto ogni metrica, perché il documento deve poter essere letto da
chi non conosce il gergo del settore.
"""

from __future__ import annotations

from biocatalyst.models.report import Report, Scenario
from biocatalyst.report.labels import DISCLAIMER, explanation, label


def _fmt(value: float | None, prefix: str = "", suffix: str = "", decimals: int = 2) -> str:
    if value is None:
        return "—"
    return f"{prefix}{value:,.{decimals}f}{suffix}"


def _nota(testo: str) -> str:
    """Riga di spiegazione, resa visivamente distinta dal dato."""
    return f"> _{testo}_\n" if testo else ""


def render_markdown(report: Report) -> str:
    lang = report.language

    def lb(key: str) -> str:
        return label(lang, key)

    def ex(key: str) -> str:
        return explanation(lang, key)

    md = report.financial_metrics
    parts: list[str] = []

    # --- Intestazione ---------------------------------------------------------
    nome = f"{report.company_name} " if report.company_name else ""
    parts.append(f"# 📊 {nome}(${report.ticker})\n")
    parts.append(f"**{lb('report_title')}**\n")
    parts.append(
        f"- **{lb('generated_on')}**: {report.report_date.isoformat()}\n"
        f"- **{lb('data_retrieved')}**: {report.generated_at:%Y-%m-%d %H:%M UTC}\n"
        f"- **{lb('price')}**: ${report.current_price:,.4f}\n"
        f"- **{lb('rating')}**: **{report.rating}**\n"
        f"- **{lb('analyst_target')}**: {_fmt(report.average_analyst_target, '$')}\n"
        f"- **{lb('main_catalyst')}**: {report.main_catalyst}\n"
    )

    # Gli avvisi vanno in cima: se un dato è inaffidabile il lettore deve
    # saperlo prima di leggerlo, non in fondo al documento.
    if report.source_quality.warnings:
        parts.append(f"\n> ⚠️ **{lb('warnings')}**\n>")
        for w in report.source_quality.warnings:
            parts.append(f"> - {w}")
        parts.append("")

    # --- Pipeline -------------------------------------------------------------
    parts.append(f"\n## {lb('sec_pipeline')}\n")
    parts.append(report.sections.pipeline_and_clinical_results + "\n")

    # --- Analisi finanziaria --------------------------------------------------
    parts.append(f"\n## {lb('sec_financial')}\n")
    parts.append("| | |\n|---|---|")
    snap = report.market_snapshot
    parts.append(
        f"| {lb('market_cap')} | {_fmt(snap.market_cap_usd if snap else None, '$', decimals=0)} |"
    )
    parts.append(
        f"| {lb('float_shares')} | {_fmt(snap.float_shares if snap else None, decimals=0)} |"
    )
    short_pct = _fmt(snap.short_percent_of_float if snap else None, suffix="%")
    riferimento = f" ({snap.short_interest_date})" if snap and snap.short_interest_date else ""
    parts.append(f"| {lb('short_float')} | {short_pct}{riferimento} |")
    parts.append(f"| {lb('days_to_cover')} | {_fmt(snap.short_ratio_days if snap else None)} |")
    parts.append(f"| {lb('burn_rate')} | {_fmt(md.quarterly_burn_rate_usd, '$', decimals=0)} |")
    runway = (
        f"{md.cash_runway_months:,.1f} {lb('months')}" if md.cash_runway_months is not None else "—"
    )
    parts.append(f"| {lb('runway')} | **{runway}** |")
    parts.append(
        f"| {lb('squeeze_score')} | {_fmt(md.short_squeeze_score, suffix='/100', decimals=0)} |"
    )
    parts.append(
        f"| {lb('dilution_score')} | {_fmt(md.dilution_risk_score, suffix='/100', decimals=0)} |"
    )
    parts.append(f"\n_{lb('data_retrieved')}: {md.as_of.isoformat()}_\n")
    parts.append(_nota(ex("runway")))
    parts.append(_nota(ex("burn_rate")))
    parts.append(_nota(ex("squeeze_score")))
    parts.append(_nota(ex("days_to_cover")))
    parts.append(_nota(ex("dilution_score")))

    if report.tam.indication != "non determinata":
        parts.append(f"\n### {lb('tam')}\n")
        parts.append(f"- **{report.tam.indication}**")
        parts.append(f"- {report.tam.prevalence_estimate}")
        parts.append(f"- {report.tam.pricing_comparable}")
        if report.tam.tam_low_usd is not None and report.tam.tam_high_usd is not None:
            parts.append(
                f"- {_fmt(report.tam.tam_low_usd, '$', decimals=0)} – "
                f"{_fmt(report.tam.tam_high_usd, '$', decimals=0)}"
            )
        parts.append(f"\n{report.tam.methodology_notes}\n")
        parts.append(_nota(ex("tam")))

    # --- Catalizzatori --------------------------------------------------------
    parts.append(f"\n## {lb('sec_catalyst')}\n")
    parts.append(report.sections.catalyst_analysis + "\n")
    if report.catalysts:
        parts.append(f"\n### {lb('catalysts_list')}\n")
        for c in report.catalysts:
            data = c.expected_date.isoformat() if c.expected_date else c.expected_date_window
            marcatori = []
            if c.is_overdue:
                marcatori.append(f"⚠️ **{lb('overdue')}**")
            if c.is_event_driven:
                marcatori.append(lb("event_driven"))
            marca = f" — {' · '.join(marcatori)}" if marcatori else ""
            parts.append(f"{c.imminence_rank}. **{data}**{marca} — {c.name}")
            # La nota temporale spiega il ritardo e cosa può significare: va
            # riportata per intero, non sostituita da un'etichetta generica.
            if c.expected_date_window:
                parts.append(f"   _{c.expected_date_window}_")
            parts.append(f"   _{c.source}_")
        parts.append("")
        parts.append(_nota(ex("catalysts")))

    # --- Scenari --------------------------------------------------------------
    parts.append(f"\n## {lb('sec_scenarios')}\n")
    for chiave, scenario in (
        ("scenario_bull", report.scenarios.bull),
        ("scenario_base", report.scenarios.base),
        ("scenario_bear", report.scenarios.bear),
    ):
        parts.append(_scenario_riga(lb(chiave), scenario))
    parts.append("")
    parts.append(_nota(ex("scenarios")))

    # --- Valore atteso --------------------------------------------------------
    ev = report.expected_value
    parts.append(f"\n## {lb('sec_ev')}\n")
    parts.append(
        f"| {lb('investment')} | {lb('shares')} | {lb('expected_value')} | {lb('expected_roi')} |"
    )
    parts.append("|---|---|---|---|")
    for r in ev.rows:
        parts.append(
            f"| ${r.investment_usd:,.0f} | {r.shares_purchasable:,.1f} | "
            f"${r.expected_value_usd:,.2f} | {r.expected_roi_pct:+.1f}% |"
        )
    if ev.eur_usd_rate is not None and ev.rate_date is not None:
        equivalente = ev.rows[0].investment_usd / ev.eur_usd_rate if ev.rows else 0
        parts.append(
            f"\n_{lb('reference_rate')}: 1 EUR = {ev.eur_usd_rate} USD "
            f"({ev.rate_date.isoformat()}) — ${ev.rows[0].investment_usd:,.0f} ≈ "
            f"€{equivalente:,.0f}_\n"
        )
    parts.append(_nota(ex("expected_value")))

    # --- Acquisizione ---------------------------------------------------------
    parts.append(f"\n## {lb('sec_acquisition')}\n")
    parts.append(f"**{report.acquisition.probability_pct:.0f}%**\n")
    if report.acquisition.potential_acquirers:
        parts.append(f"\n**{lb('potential_acquirers')}**\n")
        parts.extend(f"- {a}" for a in report.acquisition.potential_acquirers)
    if report.acquisition.comparable_deals:
        parts.append(f"\n**{lb('comparable_deals')}**\n")
        parts.extend(f"- {d}" for d in report.acquisition.comparable_deals)

    # --- Strategia ------------------------------------------------------------
    parts.append(f"\n## {lb('sec_strategy')}\n")
    parts.append(report.sections.operational_strategy + "\n")

    # --- Fonti ----------------------------------------------------------------
    parts.append(f"\n## {lb('sec_sources')}\n")
    parts.append(f"**{lb('sources_consulted')}**\n")
    for s in report.source_quality.sources_consulted:
        parts.append(f"- {s.name} — {s.retrieved_at:%Y-%m-%d %H:%M UTC}")
    parts.append(f"\n**{lb('missing_data')}**\n")
    if report.source_quality.missing_data:
        parts.extend(f"- {d}" for d in report.source_quality.missing_data)
    else:
        parts.append(f"- {lb('none')}")
    parts.append(_nota(ex("short_interest")))

    # --- Avvertenza -----------------------------------------------------------
    parts.append(f"\n---\n\n**{lb('disclaimer_title')}** — {DISCLAIMER[lang]}\n")

    return "\n".join(parts)


def _scenario_riga(nome: str, scenario: Scenario) -> str:
    return (
        f"**{nome}** ({scenario.probability:.0%}) — ${scenario.target_price:,.4f} "
        f"({scenario.target_price_change_pct:+.1f}%)  \n"
        f"{scenario.conditions}\n"
    )
