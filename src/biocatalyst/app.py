from __future__ import annotations

import streamlit as st

from biocatalyst import __version__

st.set_page_config(page_title="BioCatalyst Analyzer", page_icon="🧬", layout="wide")

st.title("🧬 BioCatalyst Analyzer")
st.caption(f"v{__version__} — in costruzione")
st.info(
    "Le funzionalità di analisi (analyze / screen) verranno aggiunte nelle fasi "
    "successive. Questa è al momento solo la shell dell'applicazione."
)
