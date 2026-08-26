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
- [x] **Fase 3** — Data provider (yfinance, SEC EDGAR, ClinicalTrials.gov, openFDA, Finnhub, Frankfurter)
- [x] **Fase 4** — Analysis engine (cash runway, burn rate, squeeze score, EV/ROI) — **copertura 100%**
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
├── data/           # 6 fonti + cache + factory — FATTO (Fase 3)
│   ├── base.py     #   errori, RateLimiter, HTTPDataProvider, collect_safely
│   ├── cache.py    #   diskcache con TTL per chiave
│   ├── sec.py      #   ticker->CIK, XBRL companyfacts, full-text search
│   ├── market.py   #   yfinance: quotazione/float/short + sentiment XBI-IBB
│   ├── clinical_trials.py, fda.py, news.py, forex.py
│   └── factory.py  #   build_data_providers(settings) -> DataProviders
├── analysis/       # calcoli deterministici — FATTO (Fase 4), copertura 100%
│   ├── financials.py     # burn rate, cash runway
│   ├── risk.py           # squeeze score, dilution risk
│   ├── expected_value.py # EV, ROI, variazioni target
│   ├── catalysts.py      # estrazione e ordinamento per imminenza
│   └── metrics.py        # compute_financial_metrics() -> (metriche, note)
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
| **Catena di concetti XBRL alternativi** (`NetIncomeLoss` → `ProfitLoss` → `NetIncomeLossAvailableToCommonStockholdersBasic`), fusi per periodo | **Verificato su ENSC**: usa `NetIncomeLoss` fino al 2021 e `ProfitLoss` dal 2022. Con un solo concetto il risultato economico risultava assente su 34 periodi su 34, rendendo incalcolabile il burn rate. La fusione è per singolo periodo, non "primo concetto non vuoto", per coprire l'intera serie storica |
| **Fatti XBRL filtrati per durata (`end - start`), non per campo `fp`** | Per uno stesso `fp` coesistono il fatto trimestrale e il cumulato year-to-date (verificato: Q2 2026 di ENSC ha sia 2.471.752 su 3 mesi sia 5.818.633 su 6 mesi). Filtrare per `fp` raddoppierebbe i valori. Finestra 80-100gg per il trimestre, 350-380 per l'esercizio |
| **`RateLimiter` condiviso a livello di classe per la SEC** (0,12s ≈ 8 req/s) | La SEC conta le 10 req/s **sommando** `www`, `data` ed `efts`: un limitatore per-provider non basterebbe |
| **`respx` per i test HTTP, non `responses`** | `responses` intercetta solo la libreria `requests`; i nostri provider usano `httpx` |
| **`collect_safely(label, fetch, missing_data)`** come unico punto di degradazione | Realizza il requisito "se un data provider fallisce il report si genera comunque": traduce l'errore in una riga di `missing_data`. Non cattura le eccezioni non-`DataProviderError`, così un bug di programmazione resta visibile |
| **Burn rate dalla media del risultato netto**, non dal calo di cassa | Verificato su ENSC: fra Q3 e Q4 2025 la cassa *sale* da 1,67M a 4,31M per un aumento di capitale — misurando il calo di cassa l'azienda avrebbe "burn negativo" pur bruciando liquidità. Il risultato netto è a sua volta distorto dalle poste non monetarie (ENSC ha un Q3 2024 in utile con cassa in calo), ma la media su 4 trimestri assorbe gli anomali. Resta un'approssimazione: il rendiconto finanziario non è esposto dalle API XBRL usate |
| **Score di rischio `float \| None`, mai 0 come segnaposto** | Uno zero si leggerebbe come "rischio nullo" invece che "non calcolabile". Per i micro-cap i dati sullo short interest mancano spesso del tutto. Ha richiesto di rendere opzionali `short_squeeze_score` e `dilution_risk_score` in `FinancialMetrics` (modifica alla Fase 2) |
| **Pesi ridistribuiti sui componenti disponibili** negli score compositi | Con un ingrediente assente il punteggio usa solo gli altri, invece di penalizzare implicitamente il titolo per un dato mancante |
| **`dilution_risk_score` distingue `None` da `False`** sui segnali dai filing | `None` = ricerca non eseguita (peso ridistribuito), `False` = cercato e non trovato (contribuisce zero). Confonderli falserebbe il punteggio |
| **Il cambio EUR/USD si semplifica nell'Expected Value** | Convertendo ingresso e uscita allo stesso tasso, il valore atteso in euro dipende solo dal rapporto prezzo atteso/prezzo corrente. Il tasso serve comunque per le azioni acquistabili e va citato — ma **il rischio di cambio fra ingresso e uscita non è modellato**, ed è dichiarato nel docstring |
| **`ScenarioInput`** (probabilità, target, condizioni) come unico input dell'LLM agli scenari | Il dataclass è volutamente privo della variazione percentuale: rende strutturalmente impossibile che l'LLM fornisca un numero aritmetico, come da requisito |

## Rischi noti da tenere presenti nelle fasi successive

- **yfinance / short interest**: dato strutturalmente vecchio di 2–3,5 settimane per *tutte* le fonti (FINRA liquida e pubblica solo 2 volte al mese) — non è un bug, va comunicato nel report con la data di riferimento (`dateShortInterest`). Per i micro-cap i campi `floatShares`/`shortRatio`/`shortPercentOfFloat` sono spesso `None` — serve codice difensivo ovunque, mai `.info["x"]` diretto.
- **yfinance ToS**: dichiara "solo uso personale" — rischio di policy basso ma da menzionare nel README/disclaimer finale.
- **Streamlit Community Cloud**: documentato un timeout non ufficiale ~60s sulle risposte HTTP outbound lunghe (caso reale con `api.anthropic.com`: 60s timeout su Streamlit Cloud vs 23s altrove). Una pipeline sequenziale di 4 agenti con modelli reasoning potrebbe superarlo cumulativamente — da affrontare esplicitamente in Fase 9 (es. generazione report asincrona con polling invece di chiamata sincrona nel path Streamlit). RAM limitata a ~1GB, sleep dopo 12h di inattività.
- **Finviz** (menzionato nei requisiti originali per lo screener universo Fase 8) — non ancora verificato. Non ha un'API ufficiale gratuita stabile: da affrontare quando si arriva alla Fase 8.
- **ClinicalTrials.gov API v2 non distingue "Phase 2b" da "Phase 2"** (valori possibili: `PHASE1`/`PHASE2`/`PHASE3`/`PHASE4`/`EARLY_PHASE1`/`NA`). `ScreenCriteria.min_pipeline_phase` è per ora una stringa semplice; il requisito originale "Phase 2b/3 o NDA/BLA submitted" andrà approssimato in Fase 8 con euristiche aggiuntive (enrollment, disegno dello studio), non con un solo valore di questo campo.
- **Nomi modello di default nei provider LLM** (`gpt-4.1`, `llama-3.3-70b-versatile`, `gemini-2.5-flash` in `llm/openai_compatible.py` e `gemini_provider.py`) sono plausibili ma non verificati con chiamate reali — l'utente inserirà i modelli corretti nel `.env` quando servirà (gli override per-agente in `.env.example` hanno comunque priorità sul default di classe).

## Particolarità delle fonti dati (verificate sulle API reali, Fase 3)

- **SEC full-text search** (`efts.sec.gov/LATEST/search-index`): con il solo parametro `q` risponde **500**. Richiede `ciks` oppure un intervallo di date. Noi passiamo sempre `ciks`.
- **CIK zero-paddato a 10 cifre**: `company_tickers.json` espone il CIK come intero senza padding; gli URL di `data.sec.gov` con CIK non paddato rispondono 404.
- **Q4 non esiste in XBRL**: derivato come FY meno i primi tre trimestri, solo se tutti e quattro i valori sono presenti (altrimenti resta assente, invece di produrre un numero sbagliato in silenzio). Verificato su ENSC: −10.176.187 − (−7.408.218) = −2.767.969.
- **Filing rettificati** (`10-K/A`, `10-Q/A`) riemettono lo stesso periodo con valori diversi: vince il deposito più recente. Una rettifica mantiene il tipo di origine (`10-Q/A` resta un 10-Q).
- **Cassa = fatto "instant"**: ha solo `end`, mai `start`. Codice che assume `start` su ogni fatto si rompe.
- **ClinicalTrials.gov `query.spons`** trova anche gli studi dove la società è solo *collaboratore*: il filtro sul lead sponsor va rifatto lato client.
- **Date parziali CT.gov**: le date stimate possono essere `"2027-04"` (solo anno-mese) — `date.fromisoformat` da solo fallisce. Normalizzate al primo del mese da `parse_flexible_date`.
- **openFDA usa date compatte** (`"20160523"`) e risponde **404 quando non ci sono risultati**: per una biotech clinical-stage senza farmaci approvati è l'esito normale, tradotto in lista vuota e non in errore.
- **yfinance `shortPercentOfFloat` è una frazione** (0,0125 = 1,25%): normalizzato a percentuale nel provider. Trattarlo come percentuale sbaglierebbe di 100× lo squeeze score.
- **yfinance `dateShortInterest` è un timestamp Unix**, non una data ISO.
- **Frankfurter nei weekend/festivi** restituisce silenziosamente l'ultimo giorno lavorativo: si cita sempre la data *della risposta*, non quella richiesta.

## Note per sessioni future

- Il venv è gestito da `uv` (non attivarlo manualmente: usare sempre `uv run <comando>`).
- `uv.lock` è tracciato in git: rigenerarlo con `uv sync` dopo ogni modifica a `pyproject.toml`, mai a mano.
- Nessuna API key reale è mai stata committata: `.env` è in `.gitignore`, `.env.example` contiene solo placeholder.
- Prima di ogni commit, verificare sempre concretamente: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest`.
