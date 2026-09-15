"""Quality & efficiency page."""

import plotly.express as px
import streamlit as st

from devin_kpi.app import data, ui
from devin_kpi.kpis.filters import apply_filters
from devin_kpi.kpis.formulas import analysis_issue_counts, compute_all
from devin_kpi.kpis.metrics_reported import reported_metrics
from devin_kpi.kpis.series import weekly_user_messages
from devin_kpi.store import Store

st.set_page_config(page_title="Quality", layout="wide")
st.title("Quality & efficiency")
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

store = Store(data.db_path())
reported = reported_metrics(store, f.start, f.end)
store.close()

kvs = {
    k.key: k
    for k in compute_all(s, p, ins, d["issues"], d["consumption"], f, settings, reported=reported)
}
cols = st.columns(5)
for c, k in zip(
    cols,
    (
        "large_session_share",
        "user_messages_per_session",
        "closed_without_merge_rate",
        "review_comments_per_merged_pr",
        "review_rounds_per_merged_pr",
    ),
):
    ui.kpi_card(kvs[k], col=c)

st.subheader("Session size distribution")
sizes = ins.session_size.value_counts().reindex(["XS", "S", "M", "L", "XL"]).fillna(0)
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
