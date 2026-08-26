"""Modalità screen: criteri di ricerca e candidate risultanti."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from biocatalyst.models.analysis import Catalyst, TAMEstimate


class ScreenCriteria(BaseModel):
    max_price_usd: float = Field(default=10.0, gt=0)
    # "Fino a $15 se molto interessante, motivando" (Requisito 3): un candidato
    # sopra max_price_usd ma entro questa soglia va comunque incluso, con
    # motivazione esplicita nel rationale — non scartato automaticamente.
    max_price_usd_exceptional: float = Field(default=15.0, gt=0)
    market_cap_max_usd: float = Field(default=500_000_000, gt=0)
    market_cap_max_usd_exceptional: float = Field(default=2_000_000_000, gt=0)
    therapeutic_area: str | None = None
    # Nota: l'API ClinicalTrials.gov v2 non distingue "Phase 2b" da "Phase 2"
    # (i valori possibili sono PHASE1/PHASE2/PHASE3/PHASE4/EARLY_PHASE1/NA).
    # "Phase 2b/3 o NDA/BLA submitted" del requisito originale va quindi
    # approssimato in Fase 8 con euristiche aggiuntive (enrollment, disegno
    # dello studio), non con un singolo valore di questo campo.
    min_pipeline_phase: str = "PHASE2"
    catalyst_types: list[str] = Field(default_factory=list)
    catalyst_window_months: int = Field(default=6, gt=0)


class ScreenCandidate(BaseModel):
    ticker: str
    company_name: str
    sector: str
    price: float = Field(gt=0)
    market_cap_usd: float = Field(gt=0)
    main_drug: str
    indication: str
    #: Prodotto dall'LLM sui soli finalisti: può mancare se la chiamata fallisce.
    tam: TAMEstimate | None = None
    catalyst: Catalyst
    float_shares: float | None = Field(default=None, ge=0)
    short_percent_of_float: float | None = Field(default=None, ge=0)
    days_to_cover: float | None = Field(default=None, ge=0)
    cash_runway_months: float | None = Field(default=None, ge=0)
    #: Punteggio di attrattività 0-100, calcolato in codice deterministico.
    attractiveness_score: float = Field(ge=0, le=100)
    #: Avviso quando la cassa non arriva al catalizzatore. Il titolo resta
    #: fra le candidate — potrebbe essere l'occasione scontata — ma il rischio
    #: di diluizione (e nella coda peggiore di interruzione dello studio) va
    #: dichiarato, non nascosto nel punteggio.
    financing_risk: str | None = None
    #: Vero se il titolo supera le soglie ordinarie ma rientra in quelle
    #: "eccezionali": va incluso dichiarandone il motivo, non scartato.
    exceptional: bool = False
    rationale: str = ""
    key_risks: list[str] = Field(default_factory=list)


class ScreenResult(BaseModel):
    criteria: ScreenCriteria
    candidates: list[ScreenCandidate]
    generated_at: datetime
