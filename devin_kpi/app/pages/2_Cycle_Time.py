"""Cycle time page."""

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from devin_kpi.app import data, ui
from devin_kpi.kpis.filters import apply_filters
from devin_kpi.kpis.formulas import _is_terminal, compute_all
from devin_kpi.kpis.metrics_reported import code_scan_metrics, reported_metrics
from devin_kpi.kpis.series import request_to_merge_hours, session_duration_hours
from devin_kpi.store import Store

st.set_page_config(page_title="Cycle time", layout="wide")
st.title("Cycle time")
data.demo_banner()
d = data.load_all()
settings = data.get_settings()
f, compare = ui.sidebar_filters(d)
s, p = apply_filters(d["sessions"], d["prs"], f)

store = Store(data.db_path())
reported = reported_metrics(store, f.start, f.end)
cscan = code_scan_metrics(store)
store.close()

kvs = {
    k.key: k
    for k in compute_all(
        s, p, d["insights"], d["issues"], d["consumption"], f, settings, reported=reported
    )
}

for c, k in zip(
    st.columns(6),
    (
        "request_to_merge_median",
        "request_to_merge_p90",
        "session_duration_median",
        "session_duration_p90",
        "pr_open_to_merge_median",
        "pr_open_to_merge_p90",
    ),
):
    ui.kpi_card(kvs[k], col=c)

git_ok = not p.empty and p.enriched_at.notna().any()
if git_ok:
    hist = request_to_merge_hours(s, p)
    label = "Request → merged change (hours)"
    fig = px.histogram(hist, x="hours", nbins=40, title=label)
else:
    hist = session_duration_hours(s, _is_terminal(s.status))
    label = "Session duration (hours) — no git enrichment; falling back to session duration"
    fig = px.histogram(hist, x="hours", nbins=40, title=label)
    st.caption(label)
ui.chart(hist, fig, "cycle_time_hist")

merged = p[p.pr_state.str.lower() == "merged"] if not p.empty else p
otm = (merged.merged_at - merged.pr_created_at).dropna() / 3600.0
fig = go.Figure()
if len(otm):
    fig.add_histogram(x=otm, name="PR open → merge (h)")
if cscan and cscan.get("avg_pr_time_to_merge_seconds"):
    avg_h = cscan["avg_pr_time_to_merge_seconds"] / 3600.0
    fig.add_vline(x=avg_h, line_dash="dash", annotation_text="code-scan avg")
import pandas as pd

otm_df = pd.DataFrame({"hours": otm})
ui.chart(otm_df, fig, "pr_open_to_merge")
