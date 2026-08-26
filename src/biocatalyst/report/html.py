"""Rendering HTML, usato come sorgente per il PDF e per l'anteprima web.

Il markup è generato con Jinja2 e ogni valore passa dall'escaping automatico:
i testi provengono da un modello linguistico e da titoli di stampa, che
possono contenere caratteri speciali.
"""

from __future__ import annotations

from jinja2 import Environment, select_autoescape

from biocatalyst.models.report import Report
from biocatalyst.report.labels import DISCLAIMER, explanation, label

TEMPLATE = """
<div class="intestazione">
  <h1>📊 {% if r.company_name %}{{ r.company_name }} {% endif %}(${{ r.ticker }})</h1>
  <p><strong>{{ lb('report_title') }}</strong></p>
  <p>{{ lb('generated_on') }}: <strong>{{ r.report_date }}</strong>
     &nbsp;·&nbsp; {{ lb('data_retrieved') }}:
     {{ r.generated_at.strftime('%Y-%m-%d %H:%M UTC') }}</p>
  <p>{{ lb('price') }}: <strong>${{ '%.4f'|format(r.current_price) }}</strong>
     &nbsp;·&nbsp; {{ lb('rating') }}: <span class="rating">{{ r.rating }}</span>
     &nbsp;·&nbsp; {{ lb('analyst_target') }}:
     {% if r.average_analyst_target %}${{ '%.2f'|format(r.average_analyst_target) }}
     {% else %}—{% endif %}</p>
  <p>{{ lb('main_catalyst') }}: {{ r.main_catalyst }}</p>
</div>

{% if r.source_quality.warnings %}
<div class="avviso">
  <strong>⚠️ {{ lb('warnings') }}</strong>
  <ul>{% for w in r.source_quality.warnings %}<li>{{ w }}</li>{% endfor %}</ul>
</div>
{% endif %}

<h2>{{ lb('sec_pipeline') }}</h2>
<p>{{ r.sections.pipeline_and_clinical_results }}</p>

<h2>{{ lb('sec_financial') }}</h2>
<table>
  <tr><th>{{ lb('market_cap') }}</th>
      <td>{{ money(snap.market_cap_usd if snap else None, 0) }}</td></tr>
  <tr><th>{{ lb('float_shares') }}</th>
      <td>{{ plain(snap.float_shares if snap else None) }}</td></tr>
  <tr><th>{{ lb('short_float') }}</th><td>{{ pct(snap.short_percent_of_float if snap else None) }}
      {% if snap and snap.short_interest_date %}<small>({{ snap.short_interest_date }})</small>
      {% endif %}</td></tr>
  <tr><th>{{ lb('days_to_cover') }}</th>
      <td>{{ plain2(snap.short_ratio_days if snap else None) }}</td></tr>
  <tr><th>{{ lb('burn_rate') }}</th><td>{{ money(m.quarterly_burn_rate_usd, 0) }}</td></tr>
  <tr><th>{{ lb('runway') }}</th><td><strong>
    {% if m.cash_runway_months is not none %}{{ '%.1f'|format(m.cash_runway_months) }}
    {{ lb('months') }}{% else %}—{% endif %}
  </strong></td></tr>
  <tr><th>{{ lb('squeeze_score') }}</th><td>{{ score(m.short_squeeze_score) }}</td></tr>
  <tr><th>{{ lb('dilution_score') }}</th><td>{{ score(m.dilution_risk_score) }}</td></tr>
</table>
<div class="nota">{{ ex('runway') }}</div>
<div class="nota">{{ ex('burn_rate') }}</div>
<div class="nota">{{ ex('squeeze_score') }}</div>
<div class="nota">{{ ex('days_to_cover') }}</div>
<div class="nota">{{ ex('dilution_score') }}</div>

{% if r.tam.indication != 'non determinata' %}
<h3>{{ lb('tam') }}</h3>
<ul>
  <li><strong>{{ r.tam.indication }}</strong></li>
  <li>{{ r.tam.prevalence_estimate }}</li>
  <li>{{ r.tam.pricing_comparable }}</li>
  {% if r.tam.tam_low_usd and r.tam.tam_high_usd %}
  <li>{{ money(r.tam.tam_low_usd, 0) }} – {{ money(r.tam.tam_high_usd, 0) }}</li>
  {% endif %}
</ul>
<p>{{ r.tam.methodology_notes }}</p>
<div class="nota">{{ ex('tam') }}</div>
{% endif %}

<h2>{{ lb('sec_catalyst') }}</h2>
<p>{{ r.sections.catalyst_analysis }}</p>
{% if r.catalysts %}
<h3>{{ lb('catalysts_list') }}</h3>
<ul>
{% for c in r.catalysts %}
  <li><strong>{{ c.expected_date or c.expected_date_window }}</strong>
      {% if c.is_overdue %}<strong style="color:#c0392b">⚠️ {{ lb('overdue') }}</strong>{% endif %}
      {% if c.is_event_driven %}<em>({{ lb('event_driven') }})</em>{% endif %}
      — {{ c.name }}
      {% if c.expected_date_window %}<br><small><em>{{ c.expected_date_window }}</em></small>
      {% endif %}<br><small>{{ c.source }}</small></li>
{% endfor %}
</ul>
<div class="nota">{{ ex('catalysts') }}</div>
{% endif %}

<h2>{{ lb('sec_scenarios') }}</h2>
{% for nome, s in scenari %}
<div class="scenario">
  <strong>{{ lb(nome) }}</strong> ({{ '%.0f'|format(s.probability * 100) }}%)
  — ${{ '%.4f'|format(s.target_price) }}
  ({{ '%+.1f'|format(s.target_price_change_pct) }}%)<br>{{ s.conditions }}
</div>
{% endfor %}
<div class="nota">{{ ex('scenarios') }}</div>

<h2>{{ lb('sec_ev') }}</h2>
<table>
  <tr><th>{{ lb('investment') }}</th><th>{{ lb('shares') }}</th>
      <th>{{ lb('expected_value') }}</th><th>{{ lb('expected_roi') }}</th></tr>
  {% for row in r.expected_value.rows %}
  <tr><td>${{ '%.0f'|format(row.investment_usd) }}</td>
      <td>{{ '%.1f'|format(row.shares_purchasable) }}</td>
      <td>{{ money(row.expected_value_usd, 2) }}</td>
      <td>{{ '%+.1f'|format(row.expected_roi_pct) }}%</td></tr>
  {% endfor %}
</table>
{% if r.expected_value.eur_usd_rate %}
<p><small>{{ lb('reference_rate') }}: 1 EUR = {{ r.expected_value.eur_usd_rate }} USD
   ({{ r.expected_value.rate_date }})</small></p>
{% endif %}
<div class="nota">{{ ex('expected_value') }}</div>

<h2>{{ lb('sec_acquisition') }}</h2>
<p><strong>{{ '%.0f'|format(r.acquisition.probability_pct) }}%</strong></p>
{% if r.acquisition.potential_acquirers %}
<p><strong>{{ lb('potential_acquirers') }}</strong></p>
<ul>{% for a in r.acquisition.potential_acquirers %}<li>{{ a }}</li>{% endfor %}</ul>
{% endif %}
{% if r.acquisition.comparable_deals %}
<p><strong>{{ lb('comparable_deals') }}</strong></p>
<ul>{% for d in r.acquisition.comparable_deals %}<li>{{ d }}</li>{% endfor %}</ul>
{% endif %}

<h2>{{ lb('sec_strategy') }}</h2>
<p>{{ r.sections.operational_strategy }}</p>

<h2>{{ lb('sec_sources') }}</h2>
<p><strong>{{ lb('sources_consulted') }}</strong></p>
<ul>
{% for s in r.source_quality.sources_consulted %}
  <li>{{ s.name }} — {{ s.retrieved_at.strftime('%Y-%m-%d %H:%M UTC') }}</li>
{% endfor %}
</ul>
<p><strong>{{ lb('missing_data') }}</strong></p>
<ul>
{% for d in r.source_quality.missing_data %}<li>{{ d }}</li>
{% else %}<li>{{ lb('none') }}</li>{% endfor %}
</ul>
<div class="nota">{{ ex('short_interest') }}</div>

<div class="disclaimer"><strong>{{ lb('disclaimer_title') }}</strong> — {{ disclaimer }}</div>
"""


def render_html(report: Report) -> str:
    env = Environment(autoescape=select_autoescape(default=True))
    template = env.from_string(TEMPLATE)

    def money(value: float | None, decimals: int) -> str:
        return "—" if value is None else f"${value:,.{decimals}f}"

    def score(value: float | None) -> str:
        return "—" if value is None else f"{value:,.0f}/100"

    def plain(value: float | None) -> str:
        return "—" if value is None else f"{value:,.0f}"

    def plain2(value: float | None) -> str:
        return "—" if value is None else f"{value:,.2f}"

    def pct(value: float | None) -> str:
        return "—" if value is None else f"{value:,.2f}%"

    return template.render(
        r=report,
        m=report.financial_metrics,
        snap=report.market_snapshot,
        plain=plain,
        plain2=plain2,
        pct=pct,
        lb=lambda key: label(report.language, key),
        ex=lambda key: explanation(report.language, key),
        money=money,
        score=score,
        disclaimer=DISCLAIMER[report.language],
        scenari=[
            ("scenario_bull", report.scenarios.bull),
            ("scenario_base", report.scenarios.base),
            ("scenario_bear", report.scenarios.bear),
        ],
    )
