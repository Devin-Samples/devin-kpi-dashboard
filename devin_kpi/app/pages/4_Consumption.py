"""Consumption page: daily stacked bar by product, cycle boundaries."""

import pandas as pd
import plotly.express as px
import streamlit as st

from devin_kpi.app import data, ui

st.set_page_config(page_title="Consumption", layout="wide")
st.title("Consumption")
data.demo_banner()
d = data.load_all()
f, _compare = ui.sidebar_filters(d)

cons = d["consumption"]
cons = cons[
    (cons.scope == "enterprise")
    & (cons.date >= f.start.date().isoformat())
    & (cons.date < f.end.date().isoformat())
]
daily = cons[cons["product"] != "total"]

st.subheader("Daily ACUs by product")
fig = px.bar(daily, x="date", y="acus", color="product")
# overlay billing cycle boundaries
cyc = d["cycles"]
for _, c in cyc.iterrows():
    ts = pd.to_datetime(c.cycle_start, unit="s", utc=True).strftime("%Y-%m-%d")
    fig.add_vline(x=ts, line_dash="dot", line_color="gray")
ui.chart(daily, fig, "consumption_daily")

st.subheader("Per-cycle totals")
totals = cons[cons["product"] == "total"][["date", "acus"]]
if not cyc.empty and not totals.empty:
    totals = totals.assign(date=pd.to_datetime(totals.date))
    cyc = cyc.assign(
        cs=pd.to_datetime(cyc.cycle_start, unit="s", utc=True).dt.tz_localize(None),
        ce=pd.to_datetime(cyc.cycle_end, unit="s", utc=True).dt.tz_localize(None),
    )
    rows = []
    for _, c in cyc.iterrows():
        acus = totals[(totals.date >= c.cs) & (totals.date < c.ce)].acus.sum()
        rows.append(
            {"cycle_start": c.cs.date(), "cycle_end": c.ce.date(), "total_acus": round(acus, 2)}
        )
    per_cycle = pd.DataFrame(rows)
else:
    per_cycle = pd.DataFrame(columns=["cycle_start", "cycle_end", "total_acus"])
st.dataframe(per_cycle, hide_index=True, use_container_width=True)
st.download_button(
    "Download per-cycle totals (CSV)",
    ui.csv_bytes(per_cycle),
    file_name="consumption_cycles.csv",
    mime="text/csv",
)
