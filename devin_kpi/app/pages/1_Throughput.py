"""Throughput page."""

import pandas as pd
import plotly.express as px
import streamlit as st

from devin_kpi.app import data, ui
from devin_kpi.kpis.series import weekly_pr_counts, weekly_session_counts

ctx = data.page_context("Throughput")
s, p, kvs, prev = ctx.sessions, ctx.prs, ctx.kvs, ctx.prev

hidden = ui.kpi_row(
    kvs,
    (
        "sessions_completed",
        "prs_created",
        "prs_merged",
        "prs_closed_unmerged",
        "merge_rate",
        "sessions_shipped_rate",
        "human_takeover_rate",
    ),
    prev,
)
ui.setup_expander(hidden)

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
        entry = ctx.reported.get(name)
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
