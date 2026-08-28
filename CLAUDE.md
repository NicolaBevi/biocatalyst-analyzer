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
- [x] **Fase 5** — I 4 agenti (DataCollector, ClinicalFinancialAnalyst, MarketNews, ReportWriter)
- [x] **Fase 6** — Rendering report (Markdown/PDF/JSON/HTML), bilingue IT/EN
- [x] **Fase 7** — CLI Typer (analyze/compare completi, screen rimandato alla Fase 8)
- [x] **Fase 8** — Modalità screen (universo titoli, filtri, ranking)
- [x] **Fase 9** — UI Streamlit
- [x] **Fase 10** — Test, CI, Docker, README completo

## Architettura

```
src/biocatalyst/
├── config.py       # Settings (pydantic-settings): provider LLM, key, cache TTL — FATTO
├── log.py          # structlog, configure_logging()/get_logger() — FATTO
├── i18n.py         # catalogo dei messaggi generati dal codice, EN/IT
├── llm/            # BaseLLMProvider + 6 provider + factory — FATTO (Fase 1)
│   └── structured.py # output JSON validato con Pydantic — Fase 5
├── models/         # schemi Pydantic condivisi — FATTO (Fase 2)
├── data/           # 6 fonti + cache + factory — FATTO (Fase 3)
│   ├── base.py     #   errori, RateLimiter, HTTPDataProvider, collect_safely
│   ├── cache.py    #   diskcache con TTL per chiave
│   ├── sec.py      #   ticker->CIK, XBRL companyfacts, full-text search
│   ├── market.py   #   yfinance: quotazione/float/short + sentiment XBI-IBB
│   ├── clinical_trials.py, fda.py, news.py, forex.py
│   ├── drug_pricing.py # spesa Medicare per farmaco (CMS), ancora il TAM
│   ├── universe.py #   universo biotech da codici SIC SEC
│   └── factory.py  #   build_data_providers(settings) -> DataProviders
├── analysis/       # calcoli deterministici — FATTO (Fase 4), copertura 100%
│   ├── financials.py     # burn rate, cash runway
│   ├── risk.py           # squeeze score, dilution risk
│   ├── expected_value.py # EV, ROI, variazioni target
│   ├── catalysts.py      # estrazione e ordinamento per imminenza
│   ├── metrics.py        # compute_financial_metrics() -> (metriche, note)
│   ├── validation.py     # controlli di plausibilità (target price)
│   ├── base_rates.py     # tassi storici di successo per fase (letteratura)
│   ├── claims.py         # cifre della prosa senza riscontro nei dati
│   └── screening.py      # filtri e punteggio di attrattività
├── agents/         # i 4 agenti + pipeline — FATTO (Fase 5)
│   ├── prompt_text.py # impalcatura bilingue dei prompt (EN/IT)
│   ├── base.py     #   BaseAgent: run(context)->context, chiavi richieste
│   ├── data_collector.py, analyst.py, market_news.py, report_writer.py
│   └── pipeline.py #   analyze(ticker) con callback di avanzamento
├── report/         # rendering md/json/html/pdf — FATTO (Fase 6)
│   ├── labels.py   #   etichette e spiegazioni IT/EN
│   ├── markdown.py, html.py, pdf.py (WeasyPrint)
│   └── __init__.py #   render_json(), save_report(path) per estensione
├── screening.py    # modalità screen a stadi — FATTO (Fase 8)
├── cli.py          # Typer: analyze, compare, screen, version — FATTO (Fasi 7-8)
└── app.py          # UI Streamlit — FATTO (Fase 9), testata con AppTest
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
| **`ReportDraft` privo di qualunque campo aritmetico** | Stessa logica applicata all'agente scrittore: niente variazioni percentuali, EV o ROI nello schema che il modello compila. La regola non è affidata a un'istruzione nel prompt ma resa impossibile da violare. C'è un test che lo verifica sullo schema |
| **`complete_structured()` ritenta rimandando al modello l'errore di validazione** | Ripetere la richiesta identica produrrebbe con ogni probabilità lo stesso JSON malformato. I tentativi di *parsing* sono contati separatamente dai retry di rete, perché un JSON non conforme non è un problema transitorio |
| **Il sentiment di settore viene sovrascritto coi valori misurati** dopo la chiamata all'LLM | È un dato misurato da yfinance, non una deduzione: il modello non deve poterlo alterare. Verificato da un test in cui il modello dichiara un sentiment inventato |
| **DataCollectorAgent non usa l'LLM** | Il suo compito è raccogliere fatti verificabili; un modello linguistico introdurrebbe solo il rischio di inventarli |
| **`_sponsor_query()` toglie la forma societaria dalla ragione sociale** | ClinicalTrials.gov registra "Ensysce Biosciences", la SEC "Ensysce Biosciences, Inc.": senza la normalizzazione la ricerca per sponsor non troverebbe nulla |
| **Expected value in dollari su $1.000**, non in euro | Il titolo quota in dollari: calcolare in quella valuta evita di far entrare un'assunzione sul cambio nel risultato. Il tasso EUR/USD resta allegato come riferimento informativo, e la sua assenza non blocca più il report |
| **Inglese come lingua predefinita**, di report *e* interfaccia | CLI e UI Streamlit sono in inglese; il report resta generabile anche in italiano |
| **`i18n.py`: catalogo centrale dei messaggi generati dal codice** | I testi prodotti dal codice (etichette delle fonti, note sulle metriche, avvisi, note sui catalizzatori) comparivano nella lingua in cui erano stati scritti a prescindere da quella scelta: un report in inglese conteneva "cassa non disponibile nei filing XBRL". Erano sparsi in sei moduli e a mano sarebbero divergiti di nuovo. Due test verificano che ogni chiave esista in entrambe le lingue e che i segnaposto di `.format()` coincidano |
| **Screening esposto anche nella UI**, non solo da CLI | La pagina ha due schede: analisi di un ticker e ricerca di opportunità, con gli stessi criteri e profili di rischio della riga di comando |
| **Report bilingue IT/EN**, scelto per singola analisi | Prompt di sistema, etichette e spiegazioni sono in `agents/prompts.py` e `report/labels.py`. Un test verifica che le due lingue abbiano esattamente le stesse chiavi, altrimenti resterebbe testo non tradotto |
| **`deepseek-v4-pro` per il solo agente scrittore**, flash per gli altri | Il report finale è il punto in cui la qualità del ragionamento conta di più. Costa: ~142s contro i ~40s del flash. Gli altri agenti restano su flash |
| **Analista: una sola chiamata LLM per valutazione clinica e TAM** (`TrialAndMarketAssessment`) | Il contesto del prompt è identico nei due casi: sdoppiarlo raddoppiava i token senza migliorare le risposte. Da 4 chiamate LLM per report a 3 |
| **Spiegazioni fisse nel report, non generate dall'LLM** | Descrivono il metodo di calcolo del sistema e devono restare identiche fra un report e l'altro; farle generare significherebbe pagarle ogni volta e rischiare che cambino |
| **`generated_at` distinto da `report_date`** | Un report rigenerato da cache può avere dati più vecchi della data di redazione: il lettore deve poter vedere entrambe |
| **Avvisi sulla qualità del dato in cima al report**, non in fondo | Se un dato è inaffidabile va saputo prima di leggerlo. Il controllo sul target analisti nasce da un caso reale: yfinance riporta $8,25 per ENSC contro un prezzo di $0,403 (20,5 volte), quasi certamente una copertura non aggiornata |
| **`market_snapshot` dentro `Report`** | Capitalizzazione, flottante e short interest sono richiesti esplicitamente dal formato: lasciarli nei soli dati grezzi li rendeva irraggiungibili al rendering (bug trovato guardando il primo report generato) |
| **`deepseek-v4-pro` anche per l'analista** (misurato, non ipotizzato) | Su uno stesso prompt pro consuma ~il doppio dei token di flash (1.960 contro 1.015) ma non estrapola oltre i dati: su uno studio in volontari sani flash deduceva un'indicazione terapeutica, pro rispondeva "non è possibile determinarla dai dati forniti". Per un progetto la cui regola è "mai stimare in silenzio", la differenza vale il costo. MarketNews resta su flash: riassumere titoli è estrazione, non ragionamento |
| **Report salvati in `reports/<TICKER>/`** con nome `TICKER_DATA_lingua.est` | Il nome ripete ticker e data che la cartella già contiene, così il file resta identificabile se spostato o allegato; la data evita che due analisi dello stesso titolo in giorni diversi si sovrascrivano. `reports/` è in `.gitignore` |
| **Tutti i parametri della CLI validati prima di costruire i provider** | Bug trovato provando la CLI: `--formats docx` avviava l'analisi completa e falliva solo al salvataggio, dopo aver speso in chiamate LLM. Ora fallisce in 3 secondi |
| **Log a WARNING per default nella CLI, `--verbose` per alzarli** | La CLI mostra già il proprio avanzamento: i log strutturati si mescolavano all'output rendendolo illeggibile |
| **`compare` non si ferma al primo ticker fallito** | Confrontare cinque titoli e perdere tutto perché il terzo non risponde sarebbe inaccettabile: i falliti sono elencati a parte |
| **Universo screen dall'anagrafica SEC per codice SIC**, non da Finviz | Finviz non pubblica un'API gratuita stabile e lo scraping sarebbe fragile. `browse-edgar?SIC=...&output=atom` elenca le società per settore; `company_tickers_exchange.json` dice quali hanno un ticker NASDAQ/NYSE. Verificato: SIC 2836+8731 danno 673 società, di cui **175 quotate** |
| **SIC 2834 escluso dal default**, disponibile con `--include-pharma` | Da solo aggiunge oltre 1.500 società, in larga parte big pharma fuori dal profilo micro-cap cercato, moltiplicando per otto i tempi di scansione |
| **Solo il CIK viene letto dal feed atom SEC** | Il feed ha un difetto noto: il nome finisce in un tag `<last-date>` mal etichettato e il titolo contiene un artefatto Perl (`ARRAY(0x...)`). Il CIK è affidabile, il nome arriva dalla mappatura dei ticker |
| **Screen a stadi con l'LLM solo sulle finaliste** | Eseguire la pipeline completa su 175 società costerebbe centinaia di chiamate a pagamento per trovarne cinque. Universo, prezzo, catalizzatori e cassa filtrano con dati gratuiti; una sola chiamata LLM produce le motivazioni di **tutte** le finaliste insieme |
| **La cassa insufficiente si segnala, non si penalizza** (peso sceso dal 35% al 15%) | Correzione a una scelta iniziale sbagliata: **diluire non è fallire**. Un titolo a $0,40 che raccoglie capitale al 50% di sconto e poi pubblica dati positivi può comunque moltiplicarsi, e questi titoli sono scontati *perché* il mercato prezza già la diluizione — è lì che vivono le scommesse asimmetriche. Penalizzandoli si scartavano proprio le occasioni. Resta però una coda davvero fatale (cassa finita senza accesso al capitale = studio interrotto): per questo ogni candidata a rischio porta `financing_risk`, un avviso che distingue esplicitamente i due scenari |
| **Tre profili di rischio** (`--risk speculativo\|bilanciato\|prudente`) | Lo screen deve mostrare l'opportunità col suo rischio, non decidere al posto di chi legge. Il profilo speculativo azzera del tutto il peso della cassa nell'ordinamento, il prudente lo porta al 40% |
| **La banda "eccezionale" include invece di scartare** | I requisiti chiedono di ammettere un titolo appena sopra soglia motivandolo: `ScreenCandidate.exceptional` lo marca e la CLI lo dichiara |
| **Streaming attivo per default** (`LLM_USE_STREAMING`) | Risolve il timeout di ~60s di Streamlit Cloud sulle risposte HTTP in uscita. **La nota precedente in questo file era sbagliata**: spostare la chiamata in un thread non accorcia la risposta HTTP, quindi il proxy la taglierebbe comunque. Lo streaming invece tiene i byte in movimento. Misurato su `deepseek-v4-pro`: primo chunk dopo 0,7s, intervallo massimo fra chunk 0,7s su 67s totali — nessuna attesa singola vicina ai 60s |
| **La pipeline gira in un thread, la pagina legge uno stato condiviso** | Serve comunque, ma per un motivo diverso dal timeout: eseguire 200s di pipeline dentro il ciclo di rendering bloccherebbe l'interfaccia. Un `st.fragment(run_every=2)` ridisegna la sola barra di avanzamento, e un `st.rerun(scope="app")` a fine lavoro sostituisce la barra col report |
| **UI testata con `streamlit.testing.v1.AppTest`** | È il framework ufficiale: permette di verificare metriche, avvisi ed errori mostrati in pagina senza un browser |
| **L'utente non-root va creato PRIMA di installare le dipendenze** | `chown -R /app` dopo `uv sync` duplica l'intero ambiente virtuale in un nuovo layer: erano 547 MB sprecati su 1,71 GB. Creando l'utente prima e usando `COPY --chown`, l'immagine è scesa a 995 MB (-42%). Verificato costruendola davvero |
| **Dockerfile: dipendenze di sistema ricavate, non copiate** | Ho verificato quali librerie WeasyPrint risolve davvero via `ctypes.util.find_library` (gobject, pango, pangoft2, harfbuzz, fontconfig, gio, cairo) e a quali pacchetti Debian corrispondono. Le versioni recenti hanno smesso di usare gdk-pixbuf, che era nella bozza iniziale ed era peso inutile. glib non è nominato di proposito: arriva come dipendenza di pango e il suo nome cambia fra Debian e Ubuntu recenti (`libglib2.0-0t64`) |
| **CI con matrice 3.11/3.12/3.13** | `requires-python = ">=3.11"` va verificato, non solo dichiarato. Controllato in locale con `uv run --python 3.11 --isolated pytest`: 345 test verdi anche lì |
| **Il job Docker della CI costruisce ma non pubblica** | Serve solo a garantire che il Dockerfile sia costruibile; l'immagine viene poi avviata per verificare che la CLI risponda |
| **Uno studio in ritardo non è uno studio concluso** | Trovato provando SLS (SELLAS): lo studio REGAL di Fase 3 su galinpepimut-S ha data stimata 2025-12-01, superata da 268 giorni, ma stato `ACTIVE_NOT_RECRUITING`. Il filtro `completion < oggi` lo scartava, e l'analisi finiva sull'asset secondario SLS009 (Fase 1/2) ignorando quello che spiega la valutazione. Ora: data **stimata** passata + stato attivo = catalizzatore **in ritardo**, quindi il più imminente di tutti; data **effettiva** passata = completamento davvero avvenuto, escluso |
| **Endpoint a eventi riconosciuti dal testo dell'outcome primario** | Uno studio con endpoint di sopravvivenza si chiude al raggiungimento di un numero di eventi, non a una data. Se gli eventi arrivano più lentamente il ritardo può significare che i pazienti vivono più a lungo — lettura possibile, non certa, e il prompt chiede al modello di esporre entrambe. Le sigle (`OS`, `PFS`) si confrontano come parole intere: come sottostringa "os" comparirebbe in "dose" e "response" |
| **L'asset di riferimento si sceglie per materialità, non per data** | Una Fase 3 muove il titolo più di una Fase 1 che legge prima. `_lead_trial` ordina per fase e, a parità, per imminenza |
| **Il prompt del writer riceve l'intera pipeline registrata** | Prima vedeva solo i catalizzatori attesi, e il report sembrava riguardare una società con un farmaco solo. Ora elenca tutti gli studi noti e chiede esplicitamente di citarli |
| **Il ritardo di uno studio si dimensiona sulla durata pianificata** | Richiede `start_date`, che il modello non catturava. REGAL: 58 mesi pianificati, 8,8 di ritardo = 15% oltre il piano. Senza questo riferimento "in ritardo di 268 giorni" è un numero che il modello non sa pesare |
| **Il prompt chiede di confrontare il ritardo con la sopravvivenza storica del controllo** | Su uno studio a eventi con comparatore a prognosi nota, un ritardo superiore alla mediana storica del controllo è un'informazione quantitativa. Non si codifica "ritardo = rialzista" — sarebbe la stima silenziosa che il progetto vieta — ma si dà al modello il riferimento per ragionarci |
| **La chiave di cache include l'impronta dei campi richiesti** | Bug trovato aggiungendo `StartDate`: la chiave non cambiava, la risposta vecchia restava valida e il campo nuovo risultava assente **senza alcun errore**. È il tipo di guasto peggiore, quello silenzioso |
| **Il prezzo del comparatore è verificato sui dati CMS, non lasciato al modello** | La stima del TAM era l'unica parte del report che poggiava interamente sulla memoria del modello. CMS pubblica la spesa Medicare effettiva per farmaco, compresa la media annua per beneficiario. Ora il modello sceglie *quale* farmaco sia il comparatore (giudizio di dominio) e il sistema ne verifica il prezzo. Su SLS il modello dichiarava $240-300k di listino per Onureg, il dato CMS dice **$129.238**: circa la metà. Se il farmaco non è nei dati Medicare, `verified_pricing` resta nullo e il report lo dichiara |
| **Il modello non deve commentare `verified_pricing`** | La verifica avviene *dopo* la sua risposta, quindi scriveva "no Medicare data were supplied, verified_pricing is null" mentre il report poi lo mostrava compilato. Il prompt ora glielo dice esplicitamente |
| **Rimosse `responses` e `vcrpy` dalle dipendenze di sviluppo** | Sostituite da `respx` in Fase 3 ma mai tolte: nessun import in tutto il progetto |
| **Storico dei rinvii di uno studio da CT.gov** (`/api/int/studies/{nct}/history`) | "In ritardo di 268 giorni" non dice se è la prima volta o la quarta: sono due storie diverse e il modello non aveva modo di distinguerle. Il registro conserva ogni revisione. Verificato su REGAL: la data è passata da 2021-12 a 2025-12 in **tre rinvii, 48 mesi**. L'endpoint è interno (non l'API v2 documentata), quindi può cambiare senza preavviso: ogni errore vale "storia non disponibile" e non blocca mai l'analisi |
| **Solo le versioni etichettate `Study Status` vengono scaricate** | Le date stanno nello `statusModule`, quindi ogni loro cambio risulta segnalato da quell'etichetta — verificato su tutte e 10 le versioni di REGAL, nessun cambio sfuggiva. Le richieste scendono da 10 a 3 |
| **Le versioni passate hanno TTL di 30 giorni, l'indice quello normale** | Una versione già pubblicata non cambia più: rileggerla è spreco. Solo l'indice va riletto per scoprire quelle nuove |
| **`TAMDraft` separato da `TAMEstimate`** | Il modello continuava a scrivere "the verified Medicare spending field is left null as instructed" in un report che due righe sotto lo mostrava compilato: obbediva all'istruzione e la raccontava. Un prompt migliore non bastava — il campo è stato tolto dallo schema che il modello compila, come già fatto con l'aritmetica in `ReportDraft`. La contraddizione è ora strutturalmente impossibile |
| **Il prezzo verificato viene passato anche allo scrittore** | Difetto trovato leggendo il report: la verifica CMS avviene dopo l'analista, ma lo scrittore riceveva solo la stima non verificata. Il testo diceva $240-300k mentre la tabella accanto diceva $129.238. Ora riceve entrambe e gli si chiede di spiegare la differenza (listino contro spesa netta) |
| **Tassi storici di successo come ancoraggio delle probabilità** | Le probabilità degli scenari sono il numero meno fondato del report e quello su cui si calcola l'expected value: il modello le sceglieva senza alcun riferimento. Ora accanto compare il tasso storico di transizione di fase. **Non è una fonte interrogabile** — unica eccezione nel progetto: sono valori di letteratura (BIO/Informa/QLS, dati fino al 2020) trascritti a mano, e il report cita sempre fonte e anno |
| **Ematologia valutata prima dell'oncologia** nel riconoscimento dell'area | Una leucemia contiene spesso "cancer" nelle condizioni, ma i tumori del sangue hanno una probabilità di approvazione del 23,9% contro il 5,3% dei solidi: confonderli darebbe il riferimento sbagliato per un fattore quattro |
| **La sigla "ALL" esclusa dalle parole chiave** | Come parola intera coincide con l'inglese "all": classificava "all solid tumors" fra i tumori del sangue. Stessa famiglia di errore già vista con "OS" dentro "dose" |
| **Elenco delle cifre non verificate in fondo al report** | La prosa mescola numeri misurati e numeri che il modello ricorda ("la sopravvivenza mediana storica è 6-12 mesi"), stampati uguali e quindi apparentemente ugualmente solidi. Ora le cifre senza riscontro nei dati raccolti sono elencate a parte. Misurato su SLS: **una sola segnalazione**, genuina. È una rete, non una garanzia — con 150+ valori noti una cifra può coincidere per caso — e il report lo dichiara |
| **La raccolta dei valori noti include le proprietà calcolate** | I mesi di slittamento esistono solo come proprietà, non come campo: senza guardarle il "48 mesi" del testo risultava non verificato pur essendo un nostro calcolo |
| **Le risposte dell'LLM vanno in cache: è così che un report diventa ripetibile** | L'utente ha segnalato che rigenerare lo stesso report dava numeri diversi. Verificato: due analisi di SLS a poche ore di distanza, stessi dati, expected value +19,1% e -27,8%. La chiave di cache è l'impronta del prompt intero, e il prompt contiene i dati raccolti: se i dati cambiano il report si rifà da solo, se non cambiano la risposta è la stessa. Non costa, anzi risparmia |
| **`temperature=0` e `seed` NON bastano** (misurato, non ipotizzato) | Sembrava la soluzione ovvia. L'API DeepSeek accetta entrambi i parametri, ma sui modelli di ragionamento non li onora: su tre chiamate identiche a `deepseek-v4-flash` con `temperature=0, seed=7` la probabilità bull è uscita 0,70 / 0,15 / 0,55 — dispersione pari a quella del default. La conduttura è comunque implementata (`supports_seed`, `LLM_TEMPERATURE`) perché è corretta e altri provider la onorano, ma il rimedio vero è la cache |
| **`generated_at` riporta l'età reale del dato, non l'ora di esecuzione** | Il file dichiarava da sempre `datetime.now()`, quindi un report costruito su filing di ieri si presentava come appena raccolto. Con la cache delle risposte il caso è diventato la norma, non l'eccezione. `DataCache` ora ricorda quando è stato scritto il più vecchio dei dati serviti (ricavato da `expire_time - ttl`, senza cambiare il formato già in cache) e il collector usa quello |
| **I prompt sono nella lingua del report, non sempre in italiano** | Segnalato dall'utente: il PDF di SLS usciva metà in inglese e metà in italiano. Causa: il system prompt diceva "write in English" ma **l'intero messaggio utente era in italiano** (intestazioni, etichette dei dati, istruzioni finali), e il modello seguiva a volte la lingua del messaggio invece di quella dell'istruzione. Con la cache delle risposte la scelta sbagliata restava poi congelata. Ora `agents/prompt_text.py` contiene l'impalcatura nelle due lingue, con gli stessi test di parità già usati per `i18n.py`, più un test che cerca parole dell'altra lingua dentro ogni voce |
| **La lingua è chiesta anche nel messaggio utente, non solo nel system prompt** | Cintura e bretelle: ogni prompt principale finisce con "Scrivi ogni sezione in italiano" / "Write every section in English". Il system prompt da solo non era bastato |
| **I profili di rischio hanno nomi interni inglesi** (`speculative`/`balanced`/`prudent`) | Comparivano in italiano nel menù di screening anche a interfaccia inglese. Il nome interno è ora inglese e stabile — è il valore accettato da `--risk` — mentre `risk_appetite_label()` fornisce l'etichetta tradotta dove serve |
| **Token esauriti = errore NON ritentabile** | `deepseek-v4-flash` e `deepseek-v4-pro` sono modelli di ragionamento e possono consumare tutto `max_tokens` nel reasoning, restituendo contenuto vuoto con `finish_reason="length"`. Ritentare fallirebbe identicamente, a pagamento |

## Rischi noti da tenere presenti nelle fasi successive

- **yfinance / short interest**: dato strutturalmente vecchio di 2–3,5 settimane per *tutte* le fonti (FINRA liquida e pubblica solo 2 volte al mese) — non è un bug, va comunicato nel report con la data di riferimento (`dateShortInterest`). Per i micro-cap i campi `floatShares`/`shortRatio`/`shortPercentOfFloat` sono spesso `None` — serve codice difensivo ovunque, mai `.info["x"]` diretto.
- **yfinance ToS**: dichiara "solo uso personale" — rischio di policy basso ma da menzionare nel README/disclaimer finale.
- **Tempi della pipeline con `pro`**: DataCollector ~1s (cache), analista ~45s, notizie ~14s, scrittore ~146s. Totale ~205s per report.
- **Streamlit Community Cloud**: documentato un timeout non ufficiale ~60s sulle risposte HTTP outbound lunghe (caso reale con `api.anthropic.com`: 60s timeout su Streamlit Cloud vs 23s altrove). Una pipeline sequenziale di 4 agenti con modelli reasoning potrebbe superarlo cumulativamente — da affrontare esplicitamente in Fase 9 (es. generazione report asincrona con polling invece di chiamata sincrona nel path Streamlit). RAM limitata a ~1GB, sleep dopo 12h di inattività.
- **Finviz**: confermato che non ha un'API ufficiale gratuita stabile. Risolto usando l'anagrafica SEC (vedi sotto), senza scraping.
- **ClinicalTrials.gov API v2 non distingue "Phase 2b" da "Phase 2"** (valori possibili: `PHASE1`/`PHASE2`/`PHASE3`/`PHASE4`/`EARLY_PHASE1`/`NA`). `ScreenCriteria.min_pipeline_phase` è per ora una stringa semplice; il requisito originale "Phase 2b/3 o NDA/BLA submitted" andrà approssimato in Fase 8 con euristiche aggiuntive (enrollment, disegno dello studio), non con un solo valore di questo campo.
- **Nomi modello di default nei provider LLM** (`gpt-4.1`, `llama-3.3-70b-versatile`, `gemini-2.5-flash` in `llm/openai_compatible.py` e `gemini_provider.py`) sono plausibili ma non verificati con chiamate reali — l'utente inserirà i modelli corretti nel `.env` quando servirà (gli override per-agente in `.env.example` hanno comunque priorità sul default di classe).

## Particolarità delle fonti dati (verificate sulle API reali, Fase 3)

- **SEC full-text search** (`efts.sec.gov/LATEST/search-index`): con il solo parametro `q` risponde **500**. Richiede `ciks` oppure un intervallo di date. Noi passiamo sempre `ciks`.
- **CIK zero-paddato a 10 cifre**: `company_tickers.json` espone il CIK come intero senza padding; gli URL di `data.sec.gov` con CIK non paddato rispondono 404.
- **Q4 non esiste in XBRL**: derivato come FY meno i primi tre trimestri, solo se tutti e quattro i valori sono presenti (altrimenti resta assente, invece di produrre un numero sbagliato in silenzio). Verificato su ENSC: −10.176.187 − (−7.408.218) = −2.767.969.
- **Filing rettificati** (`10-K/A`, `10-Q/A`) riemettono lo stesso periodo con valori diversi: vince il deposito più recente. Una rettifica mantiene il tipo di origine (`10-Q/A` resta un 10-Q).
- **Cassa = fatto "instant"**: ha solo `end`, mai `start`. Codice che assume `start` su ogni fatto si rompe.
- **Le date di completamento primario sono spesso già scadute** su studi ancora attivi: il campo `type` (`ESTIMATED` contro `ACTUAL`) è l'unico modo per distinguere un ritardo da un completamento avvenuto.
- **ClinicalTrials.gov `query.spons`** trova anche gli studi dove la società è solo *collaboratore*: il filtro sul lead sponsor va rifatto lato client.
- **Date parziali CT.gov**: le date stimate possono essere `"2027-04"` (solo anno-mese) — `date.fromisoformat` da solo fallisce. Normalizzate al primo del mese da `parse_flexible_date`.
- **openFDA usa date compatte** (`"20160523"`) e risponde **404 quando non ci sono risultati**: per una biotech clinical-stage senza farmaci approvati è l'esito normale, tradotto in lista vuota e non in errore.
- **yfinance `shortPercentOfFloat` è una frazione** (0,0125 = 1,25%): normalizzato a percentuale nel provider. Trattarlo come percentuale sbaglierebbe di 100× lo squeeze score.
- **yfinance `dateShortInterest` è un timestamp Unix**, non una data ISO.
- **CMS Medicare spending by drug** (`data.cms.gov/data-api/v1/dataset/...`): gratis, nessuna key. Part D (farmacia) e Part B (ambulatoriale, dove sta l'oncologia infusa) usano nomi di campo diversi per la stessa misura (`Avg_Spnd_Per_Bene_YYYY` contro `Avg_Spndng_Per_Bene_YYYY`). Copre la sola popolazione Medicare: è un ordine di grandezza al netto di parte degli sconti, non un prezzo di listino.
- **Frankfurter nei weekend/festivi** restituisce silenziosamente l'ultimo giorno lavorativo: si cita sempre la data *della risposta*, non quella richiesta.

## Ripetibilità (misurata su SLS, ALT, GALT, CAPR)

Rigenerando lo stesso report due volte di fila, con la cache attiva:

| Ticker | Esito | Tempi |
|---|---|---|
| SLS | identico | 4s → 4s |
| ALT | identico | 198s → 4s |
| GALT | identico | 284s → 4s |
| CAPR | identico | 158s → 4s |

Il confronto è sul JSON intero, campo per campo. Il crollo dei tempi è la
cache delle risposte LLM: la seconda esecuzione non chiama i modelli.

**Il limite che resta, misurato.** La cache garantisce che due esecuzioni *con
gli stessi dati* diano lo stesso report, non che il giudizio del modello sia
stabile in sé. Tre esecuzioni di SLS con `--no-cache`, a prezzo praticamente
fermo (13,755 / 13,800 / 13,795):

| | rating | prob. bull | target bull | EV |
|---|---|---|---|---|
| 1 | SELL | 0,15 | $30,00 | −32,8% |
| 2 | HOLD | 0,18 | $28,00 | −17,1% |
| 3 | HOLD | 0,15 | $35,00 | −5,0% |

Il rating oscilla fra SELL e HOLD e l'EV copre 28 punti. **La dispersione però
non viene dalle probabilità** — quelle stanno in 0,15-0,18 — **ma dal target
price dello scenario rialzista**, che va da $28 a $35. È l'informazione utile:
un eventuale campionamento ripetuto va applicato ai target, non alle
probabilità. Non implementato: costerebbe 2-3 chiamate in più per report.

## Non verificato (dichiarato, non nascosto)

- **I tassi storici di successo non sono verificabili eseguendo il codice.**
  Sono l'unica eccezione al metodo di questo progetto: non esiste una fonte
  gratuita e interrogabile per i tassi di transizione di fase, quindi
  `analysis/base_rates.py` contiene valori di letteratura trascritti a mano
  (BIO/Informa/QLS, dati fino al 2020). Vanno confrontati con la pubblicazione
  originale e aggiornati quando ne esce una nuova. Il report cita sempre fonte
  e anno accanto alla cifra proprio perché il lettore possa farlo.
- **L'endpoint dello storico revisioni CT.gov è interno** (`/api/int/`), non
  documentato nell'API v2 pubblica. Funziona oggi (verificato su più studi) ma
  può cambiare senza preavviso: il codice tratta ogni errore come "storia non
  disponibile".

- **La CI non è mai stata eseguita su GitHub**: il file è YAML valido e tutti i
  suoi comandi passano in locale, ma il comportamento su runner GitHub (cache
  di uv, `setup-uv@v4`) resta da confermare.
- **Nulla è mai stato pubblicato su GitHub**: nessun remote configurato, per
  scelta esplicita dell'utente.

## Note per sessioni future

- Il venv è gestito da `uv` (non attivarlo manualmente: usare sempre `uv run <comando>`).
- `uv.lock` è tracciato in git: rigenerarlo con `uv sync` dopo ogni modifica a `pyproject.toml`, mai a mano.
- Nessuna API key reale è mai stata committata: `.env` è in `.gitignore`, `.env.example` contiene solo placeholder.
- Prima di ogni commit, verificare sempre concretamente: `uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest`.
