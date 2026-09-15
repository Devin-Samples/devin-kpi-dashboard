"""KPI definitions page."""

import streamlit as st

from devin_kpi.app import data
from devin_kpi.kpis.definitions import DEFINITIONS
from devin_kpi.kpis.formulas import TERMINAL_STATUSES

st.set_page_config(page_title="Definitions", layout="wide")
st.title("KPI definitions")
data.demo_banner()

st.info(
    "Session statuses treated as terminal: "
    + ", ".join(f"`{s}`" for s in TERMINAL_STATUSES)
    + ". Daily consumption is bucketed on midnight Pacific "
    "(America/Los_Angeles; 08:00 UTC in winter, 07:00 UTC in summer), "
    "matching the Devin web app."
)

groups: dict[str, list] = {}
for key, d in DEFINITIONS.items():
    groups.setdefault(d["group"], []).append((key, d))

for group, items in groups.items():
    st.header(group)
    for key, dd in items:
        dep = ", ".join(dd["depends_on"]) or "none"
        st.markdown(
            f"**{dd['label']}** (`{key}`)  \n"
            f"Formula: {dd['formula']}  \n"
            f"Source: {dd['source']} · Depends on: {dep}"
        )
