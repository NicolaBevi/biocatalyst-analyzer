"""Separa le cifre misurate da quelle che il modello ha messo di suo.

Il report mescia due cose che si leggono allo stesso modo ma non valgono
uguale: numeri che il sistema ha misurato su una fonte (prezzo, cassa, spesa
Medicare, numerosità di uno studio) e numeri che il modello linguistico ha
tirato fuori dalla propria memoria ("la sopravvivenza mediana storica è di 6-12
mesi", "l'incidenza è di 20.000 casi l'anno"). I secondi possono essere giusti
— spesso lo sono — ma nessuno li ha verificati, e stampati nello stesso
carattere degli altri sembrano avere la stessa solidità.

Questo modulo estrae le cifre dal testo narrativo e le confronta con tutti i
valori noti al sistema. Quelle che non trovano riscontro finiscono in un elenco
in fondo al report: non sono errori — è la lista di ciò che il lettore deve
verificare da sé prima di farci affidamento.

Il confronto è volutamente generoso (tolleranza relativa, ordini di grandezza
riconosciuti): un falso allarme fa perdere fiducia nell'elenco, mentre una
cifra inventata che sfugge è meno grave perché il report dichiara comunque
quali sezioni sono giudizio del modello.

**Il filtro non è esatto e non pretende di esserlo.** Un report porta con sé
oltre un centinaio di valori misurati, quindi una cifra della prosa può
coincidere per caso con un dato che non c'entra nulla — "12 mesi di
sopravvivenza" contro un cash runway di 12 mesi — e passare per verificata. Un
elenco vuoto quindi non dimostra che ogni numero sia fondato: dice che nessuno
è vistosamente estraneo ai dati. Vale come rete, non come garanzia, ed è così
che il report lo presenta.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Tolleranza relativa nel riconoscere una cifra come "già nota": il modello
#: arrotonda ($129.238 diventa "circa $129.000") e un confronto esatto
#: segnalerebbe come non verificata una cifra che invece viene dai nostri dati.
RELATIVE_TOLERANCE = 0.02

#: Numeri troppo piccoli per essere informativi: anni, conteggi di righe,
#: "le due letture possibili". Segnalarli riempirebbe l'elenco di rumore.
MIN_MAGNITUDE = 3.0

_MULTIPLIERS: dict[str, float] = {
    "k": 1e3,
    "thousand": 1e3,
    "mila": 1e3,
    "m": 1e6,
    "mln": 1e6,
    "million": 1e6,
    "milioni": 1e6,
    "milione": 1e6,
    "bn": 1e9,
    "b": 1e9,
    "billion": 1e9,
    "miliardi": 1e9,
    "miliardo": 1e9,
}

#: Un numero, con separatori di migliaia opzionali, seguito eventualmente da
#: un moltiplicatore. Il simbolo di valuta e il segno di percentuale restano
#: fuori dal gruppo catturato: interessa il valore.
_NUMBER = re.compile(
    r"(?<![\w.])(\d{1,3}(?:[,.]\d{3})+|\d+(?:\.\d+)?)\s*"
    r"(k|thousand|mila|m|mln|million|milioni|milione|bn|b|billion|miliardi|miliardo)?\b",
    re.IGNORECASE,
)

#: Anni: "2025" in una data non è una quantità da verificare.
_YEAR = re.compile(r"^(19|20)\d{2}$")


@dataclass(frozen=True)
class UnverifiedFigure:
    """Una cifra citata dal modello senza riscontro nei dati raccolti."""

    value: float
    text: str
    context: str


def _normalise(raw: str, multiplier: str | None) -> float | None:
    pulito = raw.replace(",", "") if raw.count(",") and "." in raw else raw.replace(",", "")
    try:
        valore = float(pulito)
    except ValueError:
        return None
    if multiplier:
        valore *= _MULTIPLIERS[multiplier.lower()]
    return valore


def _matches_known(value: float, known: set[float]) -> bool:
    """Vero se la cifra corrisponde a un valore noto, a meno di arrotondamenti.

    Si confronta anche il valore diviso e moltiplicato per cento: il modello
    scrive indifferentemente "0,25" e "25%" per la stessa quantità.
    """
    for candidato in (value, value / 100.0, value * 100.0):
        for noto in known:
            # Uno zero fra i valori noti si salta: non è divisibile, e non può
            # comunque corrispondere a niente, perché `MIN_MAGNITUDE` ha già
            # scartato le cifre minuscole prima di arrivare qui.
            if noto == 0:
                continue
            if abs(candidato - noto) / abs(noto) <= RELATIVE_TOLERANCE:
                return True
    return False


def unverified_figures(
    narrative: str, known_values: set[float], max_results: int = 12
) -> list[UnverifiedFigure]:
    """Cifre presenti nel testo che non trovano riscontro nei dati raccolti."""
    trovate: list[UnverifiedFigure] = []
    gia_viste: set[float] = set()

    for match in _NUMBER.finditer(narrative):
        grezzo, moltiplicatore = match.group(1), match.group(2)
        if _YEAR.match(grezzo.replace(",", "")) and not moltiplicatore:
            continue
        valore = _normalise(grezzo, moltiplicatore)
        if valore is None or abs(valore) < MIN_MAGNITUDE:
            continue
        if any(abs(valore - v) < 1e-9 for v in gia_viste):
            continue
        if _matches_known(valore, known_values):
            continue

        gia_viste.add(valore)
        inizio = max(0, match.start() - 60)
        fine = min(len(narrative), match.end() + 60)
        trovate.append(
            UnverifiedFigure(
                value=valore,
                text=match.group(0).strip(),
                context="…" + narrative[inizio:fine].strip().replace("\n", " ") + "…",
            )
        )
        if len(trovate) >= max_results:
            break
    return trovate


def collect_known_values(*objects: object) -> set[float]:
    """Tutti i numeri che il sistema ha davvero misurato o calcolato.

    Attraversa i modelli Pydantic e le strutture annidate raccogliendo ogni
    valore numerico, **comprese le proprietà calcolate** (i mesi di
    slittamento, per esempio, esistono solo come proprietà e senza di loro il
    "48 mesi" del testo risulterebbe non verificato pur essendo nostro).

    Le sezioni narrative sono escluse di proposito: sono ciò che stiamo
    verificando, non una fonte.
    """
    noti: set[float] = set()

    def visita(obj: object, profondita: int = 0) -> None:
        if profondita > 8:
            return
        if isinstance(obj, bool) or obj is None:
            return
        if isinstance(obj, int | float):
            noti.add(float(obj))
            return
        if isinstance(obj, str | bytes):
            return
        if isinstance(obj, dict):
            for chiave, valore in obj.items():
                if chiave != "sections":
                    visita(valore, profondita + 1)
            return
        if isinstance(obj, list | tuple | set):
            for elemento in obj:
                visita(elemento, profondita + 1)
            return

        campi = getattr(type(obj), "model_fields", None)
        if campi is None:
            return
        for nome in campi:
            if nome == "sections":
                continue
            visita(getattr(obj, nome, None), profondita + 1)
        # Le proprietà calcolate non sono campi ma sono comunque dati nostri.
        for nome, attributo in vars(type(obj)).items():
            if isinstance(attributo, property):
                try:
                    visita(getattr(obj, nome), profondita + 1)
                except Exception:  # noqa: BLE001 — una proprietà rotta non deve fermare la raccolta
                    continue

    for oggetto in objects:
        visita(oggetto)
    return noti
