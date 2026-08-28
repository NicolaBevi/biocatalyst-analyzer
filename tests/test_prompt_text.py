"""Test dell'impalcatura bilingue dei prompt.

Il bug all'origine: il system prompt chiedeva un report in inglese mentre
l'intero messaggio utente era in italiano, e il modello seguiva a volte l'uno
a volte l'altro producendo report metà per lingua.
"""

from __future__ import annotations

import re

import pytest

from biocatalyst.agents.prompt_text import PROMPTS, pt
from biocatalyst.models.report import ReportLanguage


def test_ogni_chiave_esiste_in_entrambe_le_lingue() -> None:
    mancanti = [k for k, v in PROMPTS.items() if set(v) != {"en", "it"}]
    assert mancanti == []


def test_i_segnaposto_coincidono_fra_le_lingue() -> None:
    """Un segnaposto presente solo in una lingua farebbe fallire .format()."""
    for chiave, voci in PROMPTS.items():
        campi = {lingua: set(re.findall(r"\{(\w+)", testo)) for lingua, testo in voci.items()}
        assert campi["en"] == campi["it"], f"segnaposto diversi in '{chiave}': {campi}"


@pytest.mark.parametrize("language", ["it", "en"])
def test_nessun_prompt_contiene_l_altra_lingua(language: ReportLanguage) -> None:
    """Verifica grossolana ma efficace: parole tipiche dell'altra lingua.

    Non serve un rilevatore linguistico: bastano parole funzionali che in una
    lingua sono comunissime e nell'altra non compaiono mai.
    """
    spie = {
        "en": ("Scrivi", "Rispondi", "della ", "degli ", "nella ", "questo ", "Redigi"),
        "it": ("Write ", "Answer ", " the ", " with ", " from ", "Produce "),
    }[language]
    for chiave, voci in PROMPTS.items():
        testo = voci[language]
        trovate = [s for s in spie if s in testo]
        assert not trovate, f"'{chiave}' in '{language}' contiene {trovate}: {testo[:80]}"


def test_una_chiave_sconosciuta_non_fa_esplodere_la_pipeline() -> None:
    """Meglio una chiave visibile nel prompt che perdere un'analisi già pagata."""
    assert pt("en", "chiave.inesistente") == "chiave.inesistente"


def test_il_prompt_principale_chiede_esplicitamente_la_lingua() -> None:
    """Il system prompt da solo non bastava: l'istruzione va ripetuta qui."""
    assert "Scrivi ogni sezione in italiano" in PROMPTS["w.main"]["it"]
    assert "Write every section in English" in PROMPTS["w.main"]["en"]
    assert "Rispondi in italiano" in PROMPTS["a.main"]["it"]
    assert "Answer in English" in PROMPTS["a.main"]["en"]
    assert "Rispondi in italiano" in PROMPTS["n.main"]["it"]
    assert "Answer in English" in PROMPTS["n.main"]["en"]
