"""Quality & efficiency page."""

import plotly.express as px
import streamlit as st

from devin_kpi.app import data, ui
from devin_kpi.kpis.formulas import analysis_issue_counts, status_detail_breakdown
from devin_kpi.kpis.series import weekly_user_messages

ctx = data.page_context("Quality & efficiency")
s, ins, kvs, prev = ctx.sessions, ctx.insights, ctx.kvs, ctx.prev

hidden = ui.kpi_row(
    kvs,
    (
        "closed_without_merge_rate",
        "usage_limit_hit_rate",
        "session_error_rate",
        "large_session_share",
        "user_messages_per_session",
    ),
    prev,
)
hidden += ui.kpi_row(kvs, ("review_comments_per_merged_pr", "review_rounds_per_merged_pr"), prev)
ui.setup_expander(hidden)

st.subheader("How sessions ended")
st.caption(
    "status_detail of every session in the period. `inactivity` and `user_request` are "
    "normal endings; `usage_limit_exceeded` / `error` indicate blocked work."
)
outcome = status_detail_breakdown(s)
fig = px.bar(outcome, x="status_detail", y="sessions", hover_data=["share"])
ui.chart(outcome, fig, "session_outcomes")

st.subheader("Session size distribution")
sizes = ins.session_size.str.lower().value_counts().reindex(["xs", "s", "m", "l", "xl"]).fillna(0)
size_df = sizes.rename_axis("size").reset_index(name="sessions")
fig = px.bar(size_df, x="size", y="sessions")
ui.chart(size_df, fig, "size_distribution")

st.subheader("User messages per session (weekly trend)")
um = weekly_user_messages(s, ins)
fig = px.line(um, x="week", y="avg_user_messages")
ui.chart(um, fig, "user_messages_weekly")

st.subheader("Recurring issues (analysis labels)")
ic = analysis_issue_counts(ins)
ic_df = ic.rename("count").rename_axis("label").reset_index()
if ic_df.empty:
    st.caption("No analysis data collected yet.")
else:
    fig = px.bar(ic_df, x="label", y="count")
    ui.chart(ic_df, fig, "recurring_issues")
