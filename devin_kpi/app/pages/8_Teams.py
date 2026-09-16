"""Teams page: per-organization and per-user rollups (IDs only — no
names or emails are collected)."""

import plotly.express as px
import streamlit as st

from devin_kpi.app import data, ui
from devin_kpi.kpis.formulas import human_sessions, leaderboard

ctx = data.page_context("Teams")
s, p, settings = ctx.sessions, ctx.prs, ctx.settings
price = settings.effective_acu_unit_price

st.caption(
    "Rollups of the filtered sessions by organization and by user. Identifiers are the "
    "API's opaque IDs; map them to names in your own directory if needed."
)
humans_only = st.toggle(
    "Exclude service users and code-scan / automation sessions", value=True, key="teams_humans"
)
if humans_only:
    s = human_sessions(s)
    p = p[p.session_id.isin(s.session_id)] if not p.empty else p

COLUMN_CONFIG = {
    "merge_rate": st.column_config.NumberColumn("merge rate", format="%.0f%%"),
    "acus": st.column_config.NumberColumn("ACUs", format="%.1f"),
    "acus_per_merged_pr": st.column_config.NumberColumn("ACUs / merged PR", format="%.1f"),
    "cost": st.column_config.NumberColumn("cost (USD)", format="$%.0f"),
}


def _show(df, name: str) -> None:
    view = df.assign(merge_rate=df.merge_rate * 100)
    st.dataframe(view, hide_index=True, use_container_width=True, column_config=COLUMN_CONFIG)
    st.download_button(
        f"Download {name} (CSV)", ui.csv_bytes(df), file_name=f"{name}.csv", mime="text/csv"
    )


st.subheader("By organization")
orgs = leaderboard(s, p, "org_id", price)
if orgs.empty:
    st.caption("No sessions in the selected period.")
else:
    top_orgs = orgs.head(15)
    fig = px.bar(
        top_orgs,
        x="org_id",
        y="acus",
        hover_data=["sessions", "prs_merged", "merge_rate"],
        title="ACUs by organization (top 15)",
    )
    ui.chart(top_orgs, fig, "acus_by_org")
    _show(orgs, "leaderboard_orgs")

st.subheader("By user")
users = leaderboard(s, p, "user_id", price)
if users.empty:
    st.caption("No sessions in the selected period.")
else:
    n = len(users)
    if n > 5:
        n = st.slider("Show top N users by ACUs", 5, min(100, n), min(20, n))
    top_users = users.head(n)
    fig = px.scatter(
        top_users,
        x="sessions",
        y="prs_merged",
        size="acus",
        hover_name="user_id",
        hover_data=["merge_rate", "acus_per_merged_pr"],
        title="Sessions vs merged PRs (bubble = ACUs)",
    )
    ui.chart(top_users, fig, "user_sessions_vs_merged")
    _show(top_users, "leaderboard_users")
