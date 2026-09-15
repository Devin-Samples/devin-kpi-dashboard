"""Cycle time page."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from devin_kpi.app import data, ui
from devin_kpi.kpis.formulas import _is_terminal
from devin_kpi.kpis.series import request_to_merge_hours, session_duration_hours

ctx = data.page_context("Cycle time")
s, p, kvs, prev = ctx.sessions, ctx.prs, ctx.kvs, ctx.prev

hidden = ui.kpi_row(
    kvs,
    (
        "session_duration_median",
        "session_duration_p90",
        "request_to_merge_median",
        "request_to_merge_p90",
        "pr_open_to_merge_median",
        "pr_open_to_merge_p90",
    ),
    prev,
)
ui.setup_expander(hidden)

st.subheader("Session duration")
st.caption("Hours from session creation to last activity, terminal sessions only.")
dur = session_duration_hours(s, _is_terminal(s.status))
fig = px.histogram(dur, x="hours", nbins=40)
ui.chart(dur, fig, "session_duration_hist")

git_ok = not p.empty and p.enriched_at.notna().any()
if git_ok:
    st.subheader("Request → merged change")
    st.caption("Hours from session creation to PR merge (git-enriched merged PRs).")
    hist = request_to_merge_hours(s, p)
    fig = px.histogram(hist, x="hours", nbins=40)
    ui.chart(hist, fig, "request_to_merge_hist")

    st.subheader("PR open → merge")
    merged = p[p.pr_state.str.lower() == "merged"]
    otm = (merged.merged_at - merged.pr_created_at).dropna() / 3600.0
    fig = go.Figure(go.Histogram(x=otm, name="PR open → merge (h)"))
    ui.chart(pd.DataFrame({"hours": otm}), fig, "pr_open_to_merge")
