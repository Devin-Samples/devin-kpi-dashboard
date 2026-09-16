"""Activity page: audit-log event volume by action type. Actor identities
are never displayed — only distinct-actor counts."""

import plotly.express as px
import streamlit as st

from devin_kpi.app import data, ui
from devin_kpi.kpis.filters import clip_dates
from devin_kpi.kpis.series import audit_event_counts, daily_audit_events

ctx = data.page_context("Activity")
f = ctx.f
audit = clip_dates(ctx.data["audit_logs"], "occurred_at", f, unit="s")

st.caption(
    "Enterprise audit-log events in the selected date range (other sidebar filters do not "
    "apply). Shows what people and integrations are doing on the platform beyond sessions."
)

if audit.empty:
    st.info("No audit-log events in this period.")
    st.stop()

counts = audit_event_counts(audit)
days = max((f.end - f.start).days, 1)
logins = int(counts[counts.event_type == "login"].events.sum())
created = int(counts[counts.event_type == "create_session"].events.sum())
members = int(counts[counts.event_type.str.contains("member", na=False)].events.sum())

cols = st.columns(5)
cols[0].metric("Audit events", f"{len(audit):,}")
cols[1].metric("Events / day", f"{len(audit) / days:,.0f}")
cols[2].metric("Distinct actors", f"{audit.actor.nunique():,}")
cols[3].metric("Logins", f"{logins:,}")
cols[4].metric("Member changes", f"{members:,}")
if created:
    st.caption(f"{created:,} `create_session` events recorded in the audit log.")

st.subheader("Events per day by action")
daily = daily_audit_events(audit)
fig = px.bar(daily, x="date", y="events", color="event_type")
ui.chart(daily, fig, "audit_events_daily")

st.subheader("Action types")
fig = px.bar(counts.head(25), x="event_type", y="events")
ui.chart(counts, fig, "audit_event_types")
