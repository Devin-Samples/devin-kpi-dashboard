"""Cost page."""

import plotly.express as px
import streamlit as st

from devin_kpi.app import data, ui
from devin_kpi.kpis.filters import apply_filters
from devin_kpi.kpis.formulas import compute_all
from devin_kpi.kpis.metrics_reported import reported_metrics
from devin_kpi.store import Store

st.set_page_config(page_title="Cost", layout="wide")
st.title("Cost")
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

cols = st.columns(4)
for c, k in zip(
    cols, ("acus_per_session_mean", "acus_per_session_median", "acus_per_merged_pr", "total_acus")
):
    ui.kpi_card(kvs[k], col=c)
cols = st.columns(3)
for c, k in zip(cols, ("cost_per_merged_pr", "cost_per_session", "cost_per_story_point")):
    ui.kpi_card(kvs[k], col=c)
if kvs["acus_per_story_point"].available:
    ui.kpi_card(kvs["acus_per_story_point"])

st.subheader("ACU distribution by session size")
ins = d["insights"][d["insights"].session_id.isin(s.session_id)]
m = s.merge(ins[["session_id", "session_size"]], on="session_id", how="left")
fig = px.box(
    m.dropna(subset=["session_size"]),
    x="session_size",
    y="acus_consumed",
    category_orders={"session_size": ["XS", "S", "M", "L", "XL"]},
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
