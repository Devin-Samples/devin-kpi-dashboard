"""Throughput page."""

import pandas as pd
import plotly.express as px
import streamlit as st

from devin_kpi.app import data, ui
from devin_kpi.kpis.filters import apply_filters, previous_period
from devin_kpi.kpis.formulas import compute_all
from devin_kpi.kpis.metrics_reported import reported_metrics
from devin_kpi.kpis.series import weekly_pr_counts, weekly_session_counts
from devin_kpi.store import Store

st.set_page_config(page_title="Throughput", layout="wide")
st.title("Throughput")
data.demo_banner()
d = data.load_all()
settings = data.get_settings()
f, compare = ui.sidebar_filters(d)
s, p = apply_filters(d["sessions"], d["prs"], f)

store = Store(data.db_path())
reported = reported_metrics(store, f.start, f.end)
store.close()

kvs = {
    k.key: k
    for k in compute_all(
        s, p, d["insights"], d["issues"], d["consumption"], f, settings, reported=reported
    )
}
prev_map = {}
if compare:
    pf = previous_period(f)
    ps, pp = apply_filters(d["sessions"], d["prs"], pf)
    pins = (
        d["insights"][d["insights"].session_id.isin(ps.session_id)]
        if not d["insights"].empty
        else d["insights"]
    )
    piss = (
        d["issues"][d["issues"].session_id.isin(ps.session_id)]
        if not d["issues"].empty
        else d["issues"]
    )
    prev_map = {
        k.key: k
        for k in compute_all(ps, pp, pins, piss, d["consumption"], pf, settings, reported=reported)
    }

keys = [
    "sessions_completed",
    "prs_created",
    "prs_merged",
    "prs_closed_unmerged",
    "merge_rate",
    "sessions_shipped_rate",
    "human_takeover_rate",
]
cols = st.columns(len(keys))
for c, k in zip(cols, keys):
    ui.kpi_card(kvs[k], prev_map.get(k) and prev_map[k].value, col=c)

st.subheader("Weekly sessions")
ws = weekly_session_counts(s)
fig = px.bar(ws, x="week", y="sessions")
ui.chart(ws, fig, "weekly_sessions")

st.subheader("Weekly PRs by state")
wp = weekly_pr_counts(p, s)
fig = px.bar(wp, x="week", y="prs", color="pr_state")
ui.chart(wp, fig, "weekly_prs")

with st.expander("API-reported counterparts (metrics snapshots)"):
    for name in ("metrics_usage", "metrics_sessions", "metrics_prs"):
        entry = reported.get(name)
        if not entry:
            continue
        st.markdown(f"**{name}**")
        st.json(entry.get("totals", {}))
        for k in ("by_size", "by_size_merged", "by_origin"):
            if entry.get(k):
                st.dataframe(
                    pd.DataFrame([{"key": a, "count": b} for a, b in entry[k].items()]),
                    hide_index=True,
                )
