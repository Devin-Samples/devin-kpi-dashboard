"""Cost page."""

import plotly.express as px
import streamlit as st

from devin_kpi.app import data, ui

ctx = data.page_context("Cost")
s, kvs, prev = ctx.sessions, ctx.kvs, ctx.prev

hidden = ui.kpi_row(kvs, ("total_cost", "cost_per_merged_pr", "cost_per_session"), prev)
hidden += ui.kpi_row(
    kvs,
    ("total_acus", "acus_per_merged_pr", "acus_per_session_mean", "acus_per_session_median"),
    prev,
)
hidden += ui.kpi_row(kvs, ("cost_per_story_point", "acus_per_story_point"), prev)
ui.setup_expander(hidden)

st.subheader("ACU distribution by session size")
ins = ctx.insights
m = s.merge(ins[["session_id", "session_size"]], on="session_id", how="left").assign(
    session_size=lambda df: df.session_size.str.lower()
)
fig = px.box(
    m.dropna(subset=["session_size"]),
    x="session_size",
    y="acus_consumed",
    category_orders={"session_size": ["xs", "s", "m", "l", "xl"]},
)
ui.chart(m[["session_size", "acus_consumed"]].dropna(), fig, "acus_by_size")

st.subheader("ACUs by category / subcategory")
cat = (
    s.groupby(["category", "subcategory"], dropna=False)
    .agg(acus=("acus_consumed", "sum"), sessions=("session_id", "count"))
    .reset_index()
)
cat["share_of_spend"] = cat.acus / cat.acus.sum() if cat.acus.sum() else 0
cat["acus_per_session"] = cat.acus / cat.sessions
fig = px.bar(
    cat,
    x="category",
    y="acus",
    color="subcategory",
    hover_data=["share_of_spend", "acus_per_session"],
)
ui.chart(cat, fig, "acus_by_category")
