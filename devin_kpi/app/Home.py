"""Executive overview: plain-English summary, outcome cards, trends and a
one-click export of every KPI."""

from datetime import UTC, datetime

import plotly.express as px
import streamlit as st

from devin_kpi.app import data, ui
from devin_kpi.kpis.formulas import kpi_table
from devin_kpi.kpis.series import weekly_acus, weekly_merged_prs
from devin_kpi.kpis.summary import executive_summary

ctx = data.page_context("Devin Enterprise KPI Dashboard")
d, f, s, p, kvs, prev = ctx.data, ctx.f, ctx.sessions, ctx.prs, ctx.kvs, ctx.prev
settings = ctx.settings

days = (f.end - f.start).days
st.caption(
    f"{f.start:%b %d, %Y} → {f.end:%b %d, %Y} ({days} days)"
    + (f" · deltas vs the preceding {days} days" if ctx.compare else "")
    + f" · scope: {d['meta'].get('scope', 'unknown')}"
)

st.header("At a glance")
for line in executive_summary(kvs, prev):
    st.markdown(f"- {ui.md_escape(line)}")

HELP = {
    "prs_merged": "Pull requests opened by Devin that were merged.",
    "merge_rate": "Share of Devin's PRs that were merged.",
    "sessions_shipped_rate": "Share of sessions that produced at least one merged PR.",
    "human_takeover_rate": "Share of Devin PRs a human took over (API-reported).",
    "total_cost": "ACUs consumed × configured ACU price.",
    "cost_per_merged_pr": "All ACU spend in the period divided by merged PRs.",
    "total_acus": "Agent Compute Units consumed by sessions in the period.",
    "acus_per_merged_pr": "All ACUs in the period divided by merged PRs.",
    "mau": "Distinct human users with a session in the last 30 days.",
    "wau": "Distinct human users with a session in the last 7 days.",
    "playbook_automation_share": "Share of sessions started from a playbook or automation.",
    "usage_limit_hit_rate": "Sessions stopped because an org or user usage limit was hit.",
}

hidden = []
st.header("Delivery")
hidden += ui.kpi_row(
    kvs, ("prs_merged", "merge_rate", "sessions_shipped_rate", "human_takeover_rate"), prev, HELP
)
st.header("Cost")
hidden += ui.kpi_row(
    kvs, ("total_cost", "cost_per_merged_pr", "total_acus", "acus_per_merged_pr"), prev, HELP
)
st.header("Adoption & risk")
hidden += ui.kpi_row(
    kvs, ("mau", "wau", "playbook_automation_share", "usage_limit_hit_rate"), prev, HELP
)
ui.setup_expander(hidden)

st.header("Trends")
left, right = st.columns(2)
wm = weekly_merged_prs(p, s)
fig = px.bar(wm, x="week", y="prs_merged", title="Merged PRs per week")
ui.chart(wm, fig, "weekly_merged_prs", col=left)
wa = weekly_acus(s)
price = settings.effective_acu_unit_price
if price is not None:
    wa = wa.assign(cost=wa.acus * price)
    fig = px.bar(wa, x="week", y="cost", title="Spend per week (USD)")
else:
    fig = px.bar(wa, x="week", y="acus", title="ACUs per week")
ui.chart(wa, fig, "weekly_spend", col=right)

st.header("All KPIs")
table = kpi_table(list(kvs.values()), list(prev.values()))
st.download_button(
    "Export all KPIs (CSV)",
    ui.csv_bytes(table),
    file_name=f"kpis_{f.start.date()}_{f.end.date()}.csv",
    mime="text/csv",
)
with st.expander("Show table"):
    include_setup = st.checkbox("Include KPIs that need optional setup", value=False)
    show = table if include_setup else table[table.available | (table.depends_on == "")]
    st.dataframe(
        show[
            [
                "group",
                "label",
                "value",
                "previous",
                "delta",
                "delta_pct",
                "unit",
                "available",
                "depends_on",
                "note",
            ]
        ],
        use_container_width=True,
        hide_index=True,
    )
st.caption(
    f"Generated {datetime.now(tz=UTC):%Y-%m-%d %H:%M} UTC · definitions on the Definitions page"
)
