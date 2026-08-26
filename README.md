# 🧬 BioCatalyst Analyzer

Applicazione Python multi-agente che genera report di due diligence su aziende
biotech e pharma quotate su NASDAQ e NYSE, centrati sui **catalizzatori clinici
e regolatori a breve termine**: la lettura dei dati di uno studio, una decisione
FDA, la scadenza di un'autonomia di cassa.

Nasce da un'esigenza concreta: le small cap biotech si muovono su eventi datati
e verificabili, ma i dati che servono a valutarli sono sparsi fra sei fonti
diverse, ciascuna con le sue stranezze. Questo strumento li raccoglie, calcola
in Python quello che è calcolabile, e usa un modello linguistico solo dove
serve davvero un giudizio.

> **Non è consulenza finanziaria.** Vedi il [disclaimer](#disclaimer).

---

## Cosa produce

```
📊 Ensysce Biosciences, Inc. ($ENSC)

Analisi generata il: 2026-08-26 · Dati interrogati il: 2026-08-26 10:29 UTC
Prezzo: $0.4030 · Giudizio: HOLD · Target medio analisti: $8.25

⚠️ Avvisi sulla qualità del dato
 · Target medio analisti ($8.25) pari a 20.5 volte il prezzo corrente ($0.40):
   valore probabilmente non aggiornato dopo un raggruppamento di azioni.
 · Lo short interest è riferito a 12 giorni fa: FINRA lo rileva due volte al
   mese, quindi è strutturalmente arretrato per qualunque fonte.

ANALISI FINANZIARIA
  Capitalizzazione              $7,841,088
  Flottante                     19,443,174
  Short sul flottante           5.86% (2026-08-14)
  Consumo di cassa trimestrale  $3,156,097
  Autonomia di cassa            0.6 mesi
  Punteggio rischio diluizione  100/100

VALORE ATTESO
  Investimento   Azioni   Valore atteso   Rendimento
  $1,000         2,481.4  $893.30         -10.7%
```

Il report completo comprende pipeline clinica, analisi del catalizzatore
principale, tre scenari con probabilità, probabilità di acquisizione, strategia
operativa e l'elenco esplicito dei dati **non** reperiti. Esportabile in
Markdown, JSON, HTML e PDF, in **italiano o inglese**.

---

## Architettura

```
                    ┌──────────────────────────────────────────┐
   CLI (Typer) ────▶│              PIPELINE                    │
   UI (Streamlit) ─▶│  4 agenti in sequenza, contesto condiviso│
                    └──────────────────────────────────────────┘
                                      │
   ┌──────────────────────────────────┼──────────────────────────────────┐
   ▼                                  ▼                                  ▼
┌─────────────────┐     ┌──────────────────────┐      ┌─────────────────────┐
│ 1 DataCollector │     │ 2 ClinicalFinancial  │      │ 3 MarketNews        │
│                 │     │   Analyst            │      │                     │
│ nessun LLM:     │────▶│ metriche in Python   │─────▶│ fatti verificati    │
│ raccoglie fatti │     │ LLM solo per il      │      │ separati dalle voci │
│                 │     │ giudizio clinico     │      │ di mercato          │
└─────────────────┘     └──────────────────────┘      └─────────────────────┘
   │                                  │                                  │
   │  ┌───────────────────────────────┴──────────────────────────────────┘
   │  ▼
   │ ┌──────────────────────────────────────────────────────────────────┐
   │ │ 4 ReportWriter — l'unico che vede tutto il contesto              │
   │ │   l'LLM fornisce probabilità e target; l'aritmetica la fa il     │
   │ │   codice (analysis/), non il modello                             │
   │ └──────────────────────────────────────────────────────────────────┘
   │                                   │
   ▼                                   ▼
┌──────────────────────────┐   ┌───────────────────────────────────────┐
│ FONTI DATI (data/)       │   │ RENDERING (report/)                   │
│  · yfinance   prezzo,    │   │  Markdown · JSON · HTML · PDF         │
│    float, short interest │   │  italiano o inglese                   │
│  · SEC EDGAR  XBRL +     │   └───────────────────────────────────────┘
│    ricerca full-text     │
│  · ClinicalTrials.gov v2 │   ┌───────────────────────────────────────┐
│  · openFDA    Drugs@FDA  │   │ CALCOLI DETERMINISTICI (analysis/)    │
│  · Finnhub    notizie    │   │  burn rate · cash runway · squeeze    │
│  · Frankfurter EUR/USD   │   │  diluizione · EV/ROI · catalizzatori  │
│                          │   │  copertura 100% di test               │
│  cache su disco, TTL     │   └───────────────────────────────────────┘
│  differenziati           │
└──────────────────────────┘

LLM (llm/): 6 provider intercambiabili — Anthropic, OpenAI, DeepSeek, Groq,
Gemini, Ollama. Si cambia modello dal solo file .env, anche per singolo agente.
```

---

## Installazione

Serve [uv](https://docs.astral.sh/uv/) (gestisce anche la versione di Python).

```bash
git clone <url-della-repo> && cd biocatalyst-analyzer
uv sync

cp .env.example .env      # poi compila .env, vedi sotto
uv run pytest             # 346 test, deve essere tutto verde
```

### Configurazione minima

Nel file `.env` servono due cose per iniziare:

```bash
# 1. Un provider LLM (uno qualsiasi fra i sei)
DEFAULT_PROVIDER=deepseek
DEEPSEEK_API_KEY=sk-...

# 2. Uno User-Agent per la SEC, che lo richiede con un contatto reale
SEC_EDGAR_USER_AGENT=BioCatalystAnalyzer tua@email.it
```

Opzionale ma consigliato: `FINNHUB_API_KEY` (registrazione gratuita su
[finnhub.io](https://finnhub.io/register)) per le notizie sul titolo. Senza,
tutto il resto funziona e il report dichiara la fonte come non disponibile.

**Modelli diversi per agenti diversi**, per spendere dove conta:

```bash
AGENT_ANALYST_MODEL=deepseek-v4-pro     # giudizio clinico: serve ragionamento
AGENT_NEWS_MODEL=deepseek-v4-flash      # riassumere titoli: basta il veloce
AGENT_WRITER_MODEL=deepseek-v4-pro      # il report finale
```

---

## Uso

### Riga di comando

```bash
# Due diligence completa: salva md, json e pdf in reports/ENSC/
uv run biocatalyst analyze ENSC

uv run biocatalyst analyze ENSC --language en --formats md,pdf
uv run biocatalyst analyze ENSC --output ~/Documenti/report.pdf

# Confronto affiancato, ordinato per rendimento atteso
uv run biocatalyst compare ENSC MRNA VRTX

# Ricerca di nuove opportunità
uv run biocatalyst screen --max-price 10 --catalyst-window 6
uv run biocatalyst screen --risk speculativo   # non penalizza chi dovrà diluire
```

### Interfaccia web

```bash
uv run streamlit run src/biocatalyst/app.py
```

### Docker

```bash
docker build -t biocatalyst-analyzer .
docker run --rm -p 8501:8501 --env-file .env \
    -v "$PWD/reports:/app/reports" biocatalyst-analyzer

# oppure la CLI
docker run --rm --env-file .env --entrypoint biocatalyst \
    biocatalyst-analyzer analyze ENSC
```

---

## Decisioni tecniche

Le scelte non ovvie, con il motivo. Quasi tutte nascono da qualcosa emerso
**eseguendo** il codice contro le API vere, non da una previsione.

| Scelta | Perché |
|---|---|
| **L'aritmetica non la fa il modello** | `ReportDraft` — lo schema che l'LLM compila — non contiene alcun campo calcolato: niente percentuali, valore atteso o ROI. La regola non è affidata a un'istruzione nel prompt, è resa strutturalmente impossibile da violare. Un test lo verifica sullo schema |
| **SEC: API XBRL, non parsing dei filing** | `companyfacts` restituisce già cash, R&D e risultato netto numerici e datati. Ma i fatti vanno filtrati per **durata** (`end - start`), non per il campo `fp`: sotto lo stesso `fp="Q2"` convivono il trimestre e il cumulato semestrale, e usare `fp` raddoppia i valori |
| **Catena di concetti XBRL alternativi** | Ensysce usa `NetIncomeLoss` fino al 2021 e `ProfitLoss` dal 2022. Con un solo concetto il risultato economico mancava su 34 periodi su 34, rendendo il burn rate incalcolabile |
| **Burn rate dal risultato netto, non dal calo di cassa** | Fra Q3 e Q4 2025 la cassa di Ensysce *sale* per un aumento di capitale: misurando il calo di cassa risulterebbe "burn negativo" pur bruciando liquidità |
| **Score di rischio `float \| None`, mai 0** | Uno zero si legge come "rischio nullo" invece che "non calcolabile", e per i micro-cap i dati sullo short interest mancano spesso del tutto |
| **La cassa insufficiente si segnala, non penalizza** | Diluire non è fallire: un titolo scontato che raccoglie capitale e poi pubblica dati positivi può comunque moltiplicarsi. Penalizzarlo nel punteggio scartava proprio le occasioni asimmetriche. Resta però una coda fatale (cassa finita senza accesso al capitale = studio interrotto), dichiarata a parte |
| **Streaming attivo per default** | Streamlit Community Cloud taglia le risposte HTTP in uscita a ~60s e l'agente scrittore ne impiega 146. Un thread non basta: non accorcia la risposta. Lo streaming sì — misurato su un modello di ragionamento, intervallo massimo fra chunk 0,7s |
| **Finnhub, non NewsAPI** | Il tier gratuito di NewsAPI vieta l'uso fuori da un ambiente di sviluppo, anche non commerciale: incompatibile con un'app pubblicata |
| **Universo screen dall'anagrafica SEC** | Finviz non ha un'API gratuita stabile. `browse-edgar` per codice SIC dà 673 società biotech, di cui 175 quotate su NASDAQ/NYSE |
| **Screen a stadi, LLM solo sui finalisti** | Analizzare 175 società per intero costerebbe centinaia di chiamate a pagamento per trovarne cinque. Una sola chiamata produce le motivazioni di tutte le finaliste |
| **Retry centralizzato, retry degli SDK spento** | Lasciandoli entrambi attivi i tentativi si moltiplicano: 3 × 2 = 6 chiamate a pagamento invece di 3 |

---

## Limiti dichiarati

Un report dice sempre cosa **non** è riuscito a sapere. Lo stesso vale per lo
strumento:

- **Lo short interest è vecchio di 2-3 settimane**, per qualunque fonte: FINRA
  lo rileva due volte al mese. Il report mostra sempre la data di riferimento.
- **Il burn rate è un'approssimazione**: include poste non monetarie
  (rivalutazione di warrant, compensi in azioni). Il consumo di cassa operativo
  esatto richiederebbe il rendiconto finanziario, che le API XBRL non espongono.
- **Le orphan drug designation non sono coperte**: openFDA non le espone e
  l'unica fonte ufficiale è un form web senza API.
- **ClinicalTrials.gov non distingue Phase 2b da Phase 2**, quindi il filtro
  per fase è per forza grossolano.
- **Le date dei catalizzatori sono spesso stime dello sponsor** e slittano; il
  report lo dichiara accanto a ogni data.
- **yfinance dichiara "solo uso personale"** nei suoi termini.
- Il rischio di cambio EUR/USD non è modellato: i calcoli sono in dollari.

---

## Sviluppo

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv run pytest
```

346 test. La logica di calcolo (`analysis/`) è coperta al **100%**: sono i
numeri su cui si prendono decisioni, e un errore lì non verrebbe segnalato da
nessuna API. Le chiamate esterne sono simulate con `respx`; nessun test tocca
la rete.

Struttura in `src/biocatalyst/`: `config` · `llm` · `models` · `data` ·
`analysis` · `agents` · `report` · `screening` · `cli` · `app`.

---

## Disclaimer

Questo strumento produce contenuto **puramente informativo**, generato in parte
da modelli linguistici e da dati di fonti pubbliche. **Non costituisce
consulenza finanziaria, raccomandazione di investimento o invito a investire.**

I modelli linguistici possono sbagliare, e i dati delle fonti gratuite possono
essere incompleti o non aggiornati. Verifica sempre ogni numero con le fonti
primarie prima di qualsiasi decisione. Chi usa questo strumento lo fa a proprio
rischio.
