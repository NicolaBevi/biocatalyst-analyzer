# BioCatalyst Analyzer — stato del progetto

Applicazione Python multi-agente che genera report di due diligence su aziende
biotech/pharma quotate NASDAQ/NYSE, focalizzati su catalizzatori clinici e
regolatori a breve termine. Doppio obiettivo: uso personale reale (report
accurati, non demo) + portfolio piece professionale (codice pulito, tipizzato,
testato, deployabile).

Sviluppo incrementale per fasi, con conferma dell'utente prima di ogni fase.
Questo file va aggiornato ad ogni fase completata: è la fonte di verità su
stato e decisioni, non un artefatto usa-e-getta.

## Metodo di lavoro stabilito in questo progetto

- **Ogni claim va verificato eseguendo il codice**, non assumendo. In questo
  progetto è già emerso più volte che l'output di `ruff`/`mypy`/`pytest` reale
  contraddice quello che "dovrebbe" funzionare (vedi es. sotto sul conflitto
  numpy/mypy, o `temperature` rimosso da `anthropic` 1.x — nessuno dei due
  era prevedibile senza eseguire davvero i tool).
- **Prima di scrivere codice contro un SDK esterno**, introspezionare la
  versione realmente installata (`inspect.signature`, `dir()`) invece di
  affidarsi alla conoscenza pregressa: le librerie in `pyproject.toml` cambiano
  major version nel tempo e le signature cambiano con loro.
- Ambiente senza `git`/`uv` preinstallati (solo `apt-get`/`sudo`/`wget`
  disponibili di base). Entrambi ora installati in `~/.local/bin`. **Le shell
  non interattive non caricano `~/.bashrc`/`~/.profile`**: ogni comando Bash in
  questo progetto deve iniziare con `source ~/.local/bin/env` prima di
  invocare `uv` o `git` se non risultano sul PATH.

## Stato di avanzamento

- [x] **Fase 0** — Scheletro repo e configurazione
- [x] **Fase 1** — Layer LLM multi-provider
- [x] **Fase 2** — Modelli Pydantic condivisi
- [ ] Fase 3 — Data provider (yfinance, SEC EDGAR, ClinicalTrials.gov, openFDA, Finnhub, Frankfurter)
- [ ] Fase 4 — Analysis engine (cash runway, burn rate, squeeze score, EV/ROI)
- [ ] Fase 5 — I 4 agenti (DataCollector, ClinicalFinancialAnalyst, MarketNews, ReportWriter)
- [ ] Fase 6 — Rendering report (Markdown/PDF/JSON)
- [ ] Fase 7 — CLI Typer (analyze/screen/compare)
- [ ] Fase 8 — Modalità screen (universo titoli, filtri, ranking)
- [ ] Fase 9 — UI Streamlit
- [ ] Fase 10 — Test, CI, Docker, README completo

## Architettura

```
src/biocatalyst/
├── config.py       # Settings (pydantic-settings): provider LLM, key, cache TTL — FATTO
├── log.py          # structlog, configure_logging()/get_logger() — FATTO
├── llm/            # BaseLLMProvider + 6 provider + factory — FATTO (Fase 1)
├── models/         # schemi Pydantic condivisi — FATTO (Fase 2)
├── data/           # yfinance, SEC, ClinicalTrials, news, cache — vuoto, Fase 3
├── analysis/       # calcoli deterministici (EV, runway, squeeze score) — vuoto, Fase 4
├── agents/         # i 4 agenti — vuoto, Fase 5
├── report/         # rendering md/pdf/json — vuoto, Fase 6
├── cli.py          # entrypoint Typer — solo stub (comando `version`)
└── app.py          # UI Streamlit — solo stub
```

## Decisioni tecniche prese (con motivazione)

| Decisione | Motivazione |
|---|---|
| **uv** invece di Poetry | Più veloce (Rust), stesso team di ruff, gestisce anche la versione di Python, `pyproject.toml` in stile PEP 621 standard |
| **WeasyPrint** per il PDF (non ReportLab) | Resa migliore da HTML/CSS per un portfolio piece; richiede pacchetti di sistema (Pango/Cairo) già inclusi nel Dockerfile |
| **Finnhub** come fonte news primaria (non NewsAPI) | Il tier gratuito di NewsAPI vieta esplicitamente qualsiasi uso "fuori development environment", anche non commerciale — incompatibile con un'app deployata. Finnhub free tier lo permette (uso personale/non commerciale) |
| **Orphan drug designation: omessa dall'MVP** | openFDA non la copre; l'unica fonte ufficiale (`accessdata.fda.gov/scripts/opdlisting/oopd/`) è un form ColdFusion senza API — solo scraping HTML fragile. Rimandata a estensione futura |
| **SEC: XBRL companyfacts/companyconcept API**, non parsing di 10-Q/10-K grezzi | `data.sec.gov/api/xbrl/companyfacts/CIK{10digit}.json` restituisce già cash/R&D/net loss strutturati e numerici — verificato live. Il Q4 va derivato per sottrazione (FY − 9 mesi YTD), non è mai taggato da solo |
| **Frankfurter** (`api.frankfurter.dev`) per EUR/USD | Gratis, nessuna key, dati ECB, endpoint storico per data — non specificato nei requisiti originali ma necessario per il formato report |
| **mypy `python_version = "3.12"`**, disaccoppiato da `requires-python = ">=3.11"` | I `.pyi` di numpy 2.x (dipendenza transitiva di streamlit/yfinance) usano sintassi PEP 695 che il parser di mypy rifiuta sotto 3.12, anche per stub non importati direttamente. Il codice sorgente resta comunque compatibile 3.11+ |
| **`AnthropicProvider.supports_temperature = False`** | L'SDK `anthropic` 1.x ha rimosso `temperature`/`top_p`/`top_k` da `messages.create()` (TypeError se passati) — unico tra i 6 provider. `BaseLLMProvider.complete()` scarta il parametro con un warning invece di propagarlo |
| **Retry centralizzato in `BaseLLMProvider` (tenacity), retry interno degli SDK disattivato** (`max_retries=0` sui client) | Altrimenti i tentativi si moltiplicano (retry SDK × retry tenacity = costi e latenza imprevisti) |
| **DeepSeek e Groq condividono `OpenAICompatibleProvider`** | Espongono entrambi il protocollo OpenAI chat/completions, cambiano solo `base_url` e nome modello |
| **Sorgenti non attaccate a ogni singolo campo numerico**, ma aggregate in `SourceQuality.sources_consulted` a livello di report | Un campo "fonte" per ogni float avrebbe raddoppiato la dimensione di ogni modello; le sezioni narrative dell'LLM citano comunque la fonte inline nel testo dove rilevante |
| **`ScenarioAnalysis` con campi `bull`/`base`/`bear` nominati**, non `list[Scenario]` | Sono sempre esattamente tre scenari con nomi fissi: un validator (`model_validator`) verifica che le probabilità sommino a 1.0 (tolleranza ±0.01) — un `list` generico avrebbe richiesto validare anche cardinalità e nomi a runtime |
| **`Catalyst` richiede `expected_date` O `expected_date_window`** | Un catalizzatore senza nessuna informazione temporale non è ordinabile per imminenza (requisito esplicito della pipeline) — validato con `model_validator` |

## Rischi noti da tenere presenti nelle fasi successive

- **yfinance / short interest**: dato strutturalmente vecchio di 2–3,5 settimane per *tutte* le fonti (FINRA liquida e pubblica solo 2 volte al mese) — non è un bug, va comunicato nel report con la data di riferimento (`dateShortInterest`). Per i micro-cap i campi `floatShares`/`shortRatio`/`shortPercentOfFloat` sono spesso `None` — serve codice difensivo ovunque, mai `.info["x"]` diretto.
- **yfinance ToS**: dichiara "solo uso personale" — rischio di policy basso ma da menzionare nel README/disclaimer finale.
- **Streamlit Community Cloud**: documentato un timeout non ufficiale ~60s sulle risposte HTTP outbound lunghe (caso reale con `api.anthropic.com`: 60s timeout su Streamlit Cloud vs 23s altrove). Una pipeline sequenziale di 4 agenti con modelli reasoning potrebbe superarlo cumulativamente — da affrontare esplicitamente in Fase 9 (es. generazione report asincrona con polling invece di chiamata sincrona nel path Streamlit). RAM limitata a ~1GB, sleep dopo 12h di inattività.
- **Finviz** (menzionato nei requisiti originali per lo screener universo Fase 8) — non ancora verificato. Non ha un'API ufficiale gratuita stabile: da affrontare quando si arriva alla Fase 8.
- **ClinicalTrials.gov API v2 non distingue "Phase 2b" da "Phase 2"** (valori possibili: `PHASE1`/`PHASE2`/`PHASE3`/`PHASE4`/`EARLY_PHASE1`/`NA`). `ScreenCriteria.min_pipeline_phase` è per ora una stringa semplice; il requisito originale "Phase 2b/3 o NDA/BLA submitted" andrà approssimato in Fase 8 con euristiche aggiuntive (enrollment, disegno dello studio), non con un solo valore di questo campo.
- **Nomi modello di default nei provider LLM** (`gpt-4.1`, `llama-3.3-70b-versatile`, `gemini-2.5-flash` in `llm/openai_compatible.py` e `gemini_provider.py`) sono plausibili ma non verificati con chiamate reali — l'utente inserirà i modelli corretti nel `.env` quando servirà (gli override per-agente in `.env.example` hanno comunque priorità sul default di classe).

## Note per sessioni future

- Il venv è gestito da `uv` (non attivarlo manualmente: usare sempre `uv run <comando>`).
- `uv.lock` è tracciato in git: rigenerarlo con `uv sync` dopo ogni modifica a `pyproject.toml`, mai a mano.
- Nessuna API key reale è mai stata committata: `.env` è in `.gitignore`, `.env.example` contiene solo placeholder.
- Prima di ogni commit, verificare sempre concretamente: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest`.
