"""Overview page: KPI table, headline cards, one-click export."""

from datetime import UTC, datetime

import streamlit as st

from devin_kpi.app import data, ui
from devin_kpi.kpis.filters import apply_filters, previous_period
from devin_kpi.kpis.formulas import compute_all, kpi_table
from devin_kpi.kpis.metrics_reported import reported_metrics
from devin_kpi.store import Store

st.set_page_config(page_title="Devin KPI Dashboard", layout="wide")
st.title("Devin Enterprise KPI Dashboard")

data.demo_banner()
d = data.load_all()
settings = data.get_settings()
f, compare = ui.sidebar_filters(d)

s, p = apply_filters(d["sessions"], d["prs"], f)
ins = (
    d["insights"][d["insights"].session_id.isin(s.session_id)]
    if not d["insights"].empty
    else d["insights"]
)
iss = (
    d["issues"][d["issues"].session_id.isin(s.session_id)] if not d["issues"].empty else d["issues"]
)

store = Store(data.db_path())
reported = reported_metrics(store, f.start, f.end)
store.close()

cur = compute_all(s, p, ins, iss, d["consumption"], f, settings, reported=reported)
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
prev = compute_all(ps, pp, pins, piss, d["consumption"], pf, settings, reported=reported)
table = kpi_table(cur, prev if compare else [])

by_key = {k.key: k for k in cur}
prev_by_key = {k.key: k for k in prev}

st.header("Headline")
cols = st.columns(4)
for c, key in zip(cols, ("sessions_completed", "merge_rate", "acus_per_session_mean", "dau")):
    kv = by_key[key]
    ui.kpi_card(kv, prev_by_key[key].value if compare else None, col=c)

st.header("All KPIs")
show = table[
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
]
st.dataframe(show, use_container_width=True, hide_index=True)
st.download_button(
    "Export all KPIs (CSV)",
    ui.csv_bytes(table),
    file_name=f"kpis_{f.start.date()}_{f.end.date()}.csv",
    mime="text/csv",
)
st.caption(
    f"Period {f.start.date()} → {f.end.date()} · scope "
    f"{d['meta'].get('scope', 'unknown')} · generated "
    f"{datetime.now(tz=UTC):%Y-%m-%d %H:%M} UTC"
)
