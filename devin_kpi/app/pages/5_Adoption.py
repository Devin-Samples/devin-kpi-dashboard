"""Adoption page: DAU/WAU/MAU series, origins, playbook share, seats."""

from dataclasses import replace
from datetime import UTC, datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from devin_kpi.app import data, ui
from devin_kpi.kpis.filters import apply_filters, clip_dates
from devin_kpi.kpis.formulas import human_sessions, is_service_session
from devin_kpi.kpis.metrics_reported import active_users_series
from devin_kpi.kpis.series import active_users_rolling, daily_active_users

ctx = data.page_context("Adoption")
d, f, s, kvs, prev, settings = ctx.data, ctx.f, ctx.sessions, ctx.kvs, ctx.prev, ctx.settings

hidden = ui.kpi_row(kvs, ("dau", "wau", "mau", "stickiness", "active_vs_licensed"), prev)
ui.setup_expander(hidden)

store = data.store()
try:
    dau_rep = clip_dates(
        active_users_series(store, "metrics_dau", f.start, f.end), "start_time", f, unit="s"
    )
    wau_rep = clip_dates(
        active_users_series(store, "metrics_wau", f.start, f.end), "start_time", f, unit="s"
    )
    mau_rep = clip_dates(
        active_users_series(store, "metrics_mau", f.start, f.end), "start_time", f, unit="s"
    )
finally:
    store.close()

st.subheader("Active users")
st.caption(
    "Computed series count human users only (service users and code-scan / automation "
    "sessions excluded). Dotted lines are the API's own DAU/WAU/MAU."
)
# Rolling actives must see sessions outside the date window (a user whose
# last session was 20 days ago still counts toward MAU on day 1), so they
# are computed over sessions filtered by everything except the date range,
# then clipped to it.
f_no_dates = replace(
    f,
    start=datetime(1970, 1, 1, tzinfo=UTC),
    end=datetime(2100, 1, 1, tzinfo=UTC),
)
s_nd, _ = apply_filters(d["sessions"], d["prs"], f_no_dates)
h, h_nd = human_sessions(s), human_sessions(s_nd)
dau_c = clip_dates(daily_active_users(h), "date", f)
wau_c = clip_dates(active_users_rolling(h_nd, 7), "date", f)
mau_c = clip_dates(active_users_rolling(h_nd, 30), "date", f)
fig = go.Figure()
if not dau_c.empty:
    fig.add_scatter(x=dau_c.date, y=dau_c.active_users, name="DAU (computed)")
if not wau_c.empty:
    fig.add_scatter(x=wau_c.date, y=wau_c.active_users, name="WAU (computed)")
if not mau_c.empty:
    fig.add_scatter(x=mau_c.date, y=mau_c.active_users, name="MAU (computed)")
for ser, name in ((dau_rep, "DAU (API)"), (wau_rep, "WAU (API)"), (mau_rep, "MAU (API)")):
    if not ser.empty:
        fig.add_scatter(
            x=pd.to_datetime(ser.start_time, unit="s", utc=True),
            y=ser.active_users,
            name=name,
            line={"dash": "dot"},
        )
merged_series = pd.concat(
    [dau_c.assign(metric="dau"), wau_c.assign(metric="wau"), mau_c.assign(metric="mau")]
)
ui.chart(merged_series, fig, "active_users")

st.subheader("Sessions by origin")
orig = (
    s.assign(kind=is_service_session(s).map({True: "service / automation", False: "human"}))
    .groupby(["origin", "kind"], dropna=False)
    .size()
    .reset_index(name="sessions")
)
fig = px.bar(orig, x="origin", y="sessions", color="kind")
ui.chart(orig, fig, "sessions_by_origin")

st.subheader("Playbook & automation")
ui.kpi_card(kvs["playbook_automation_share"], ctx.prev_value("playbook_automation_share"))

if settings.SEAT_COUNT:
    st.subheader("Active vs licensed seats")
    active = h.user_id.nunique()
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=active,
            gauge={"axis": {"range": [0, settings.SEAT_COUNT]}},
            title={"text": f"human users active of {settings.SEAT_COUNT} seats"},
        )
    )
    st.plotly_chart(fig, use_container_width=True)
