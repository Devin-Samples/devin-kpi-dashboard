"""Code scans page: scan volume, remediation PRs and open findings as
reported by the code-scans metrics endpoint (latest snapshot)."""

import pandas as pd
import plotly.express as px
import streamlit as st

from devin_kpi.app import data, ui
from devin_kpi.kpis.metrics_reported import code_scan_metrics

st.set_page_config(page_title="Code scans", layout="wide")
st.title("Code scans")
data.demo_banner()

store = data.store()
try:
    m = code_scan_metrics(store)
finally:
    store.close()

if not m:
    st.info("No code-scan metrics collected yet. Run `python -m devin_kpi collect` first.")
    st.stop()

st.caption(
    "Latest snapshot of the code-scans metrics endpoint for the collected range. "
    "The sidebar filters do not apply to this page."
)


def _n(key: str) -> int:
    v = m.get(key)
    return int(v) if v is not None else 0


def _hours(key: str) -> str:
    v = m.get(key)
    return f"{v / 3600:,.1f} h" if v else "—"


prs_created = _n("prs_created_count")
merged = _n("prs_merged_count")
merge_rate = merged / prs_created if prs_created else None

st.subheader("Scanning & remediation")
cols = st.columns(5)
cols[0].metric("Scans run", f"{_n('scans_count'):,}")
cols[1].metric("Repositories scanned", f"{_n('repos_scanned_count'):,}")
cols[2].metric("Remediation PRs opened", f"{prs_created:,}")
cols[3].metric("Remediation PRs merged", f"{merged:,}")
cols[4].metric("Merge rate", f"{merge_rate:.0%}" if merge_rate is not None else "—")

cols = st.columns(3)
cols[0].metric("PRs still open", f"{_n('prs_open_count'):,}")
cols[1].metric("Avg time to merge", _hours("avg_pr_time_to_merge_seconds"))
cols[2].metric("Avg time open (unmerged)", _hours("avg_pr_open_duration_seconds"))

st.subheader("Open findings by severity")
sev = pd.DataFrame(
    {
        "severity": ["critical", "high", "medium", "low"],
        "open_findings": [
            _n("open_critical_findings_count"),
            _n("open_high_findings_count"),
            _n("open_medium_findings_count"),
            _n("open_low_findings_count"),
        ],
    }
)
crit_high = int(sev.open_findings.iloc[:2].sum())
if crit_high:
    st.warning(f"{crit_high:,} open critical/high findings need attention.")
fig = px.bar(
    sev,
    x="severity",
    y="open_findings",
    color="severity",
    color_discrete_map={
        "critical": "#b00020",
        "high": "#e65100",
        "medium": "#f9a825",
        "low": "#9e9e9e",
    },
    category_orders={"severity": ["critical", "high", "medium", "low"]},
)
fig.update_layout(showlegend=False)
ui.chart(sev, fig, "open_findings_by_severity")

st.subheader("PR pipeline")
pipe = pd.DataFrame(
    {
        "state": ["open", "merged", "closed"],
        "prs": [_n("prs_open_count"), merged, _n("prs_closed_count")],
    }
)
fig = px.pie(pipe, names="state", values="prs", hole=0.5)
ui.chart(pipe, fig, "code_scan_pr_states")

with st.expander("Raw snapshot"):
    st.json(m)
