"""Data status page: scope, freshness, row counts, enrichment coverage."""

from datetime import UTC, datetime

import pandas as pd
import streamlit as st

from devin_kpi.app import data

st.set_page_config(page_title="Data status", layout="wide")
st.title("Data status")
data.demo_banner()
d = data.load_all()
settings = data.get_settings()
meta = d["meta"]

st.subheader("Connection")
st.write(
    {
        "demo_mode": settings.demo_mode,
        "scope": meta.get("scope"),
        "last_collect_at": (
            datetime.fromtimestamp(int(meta["last_collect_at"]), tz=UTC).isoformat()
            if meta.get("last_collect_at")
            else None
        ),
        "database": data.db_path(),
    }
)

st.subheader("Row counts")
counts = {
    t: len(d[t])
    for t in (
        "sessions",
        "prs",
        "insights",
        "issues",
        "consumption",
        "cycles",
        "snapshots",
        "audit_logs",
        "collector_runs",
    )
}
st.dataframe(pd.DataFrame([{"table": k, "rows": v} for k, v in counts.items()]), hide_index=True)

st.subheader("Enrichment coverage")
prs, issues = d["prs"], d["issues"]
pr_cov = prs.enriched_at.notna().mean() if not prs.empty else 0.0
iss_cov = issues.story_points.notna().mean() if not issues.empty else 0.0
st.metric("PRs enriched", f"{pr_cov:.0%}")
st.metric("Issue links with story points", f"{iss_cov:.0%}")

st.subheader("Collector runs")
runs = d["collector_runs"].copy()
if not runs.empty:
    runs["window_start"] = pd.to_datetime(runs.window_start, unit="s", utc=True)
    runs["window_end"] = pd.to_datetime(runs.window_end, unit="s", utc=True)
    st.dataframe(
        runs.sort_values("window_start", ascending=False), hide_index=True, use_container_width=True
    )
else:
    st.caption("No collector runs recorded.")
