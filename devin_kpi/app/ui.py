"""Shared Streamlit UI helpers: sidebar filters, KPI cards, chart + CSV
export."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pandas as pd
import streamlit as st

from devin_kpi.kpis.filters import FilterSet

DEPENDS_LABELS = {
    "git_enrichment": "needs git token (GITHUB_TOKEN / GITLAB_TOKEN / AZURE_DEVOPS_PAT)",
    "tracker_enrichment": "needs tracker credentials (Jira / Linear)",
    "ACU_UNIT_PRICE": "needs ACU_UNIT_PRICE",
    "SEAT_COUNT": "needs SEAT_COUNT",
}


def csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode()


def sidebar_filters(data: dict) -> tuple[FilterSet, bool]:
    """Render the sidebar; returns (FilterSet, compare_previous)."""
    sessions = data["sessions"]
    st.sidebar.header("Filters")

    preset = st.sidebar.selectbox(
        "Date range", ["Last 7 days", "Last 30 days", "Last 90 days", "Custom"], index=2
    )
    end = datetime.now(tz=UTC)
    if preset == "Custom":
        if not sessions.empty:
            lo = _ts(sessions.created_at.min()).date()
            hi = _ts(sessions.created_at.max()).date()
        else:
            lo, hi = (end - timedelta(days=90)).date(), end.date()
        picked = st.sidebar.date_input("Range", value=(lo, hi), min_value=lo, max_value=hi)
        if isinstance(picked, tuple) and len(picked) == 2:
            start_d, end_d = picked
        else:
            start_d, end_d = lo, hi
        start = datetime.combine(start_d, datetime.min.time(), tzinfo=UTC)
        end = datetime.combine(end_d, datetime.min.time(), tzinfo=UTC) + timedelta(days=1)
    else:
        days = {"Last 7 days": 7, "Last 30 days": 30, "Last 90 days": 90}[preset]
        start = end - timedelta(days=days)

    def multi(label, values):
        return st.sidebar.multiselect(label, sorted(v for v in values if pd.notna(v)))

    org_ids = multi("Organizations", sessions.org_id.unique() if not sessions.empty else [])
    user_ids = multi("Users", sessions.user_id.unique() if not sessions.empty else [])
    categories = multi("Categories", sessions.category.unique() if not sessions.empty else [])
    origins = multi("Origins", sessions.origin.unique() if not sessions.empty else [])
    repos = multi("Repositories", _json_values(sessions.repo_names_json))
    tags = multi("Tags", _json_values(sessions.tags_json))
    compare = st.sidebar.checkbox("Compare with previous period", value=True)
    f = FilterSet(
        start=start,
        end=end,
        org_ids=org_ids,
        user_ids=user_ids,
        categories=categories,
        origins=origins,
        repos=repos,
        tags=tags,
    )
    return f, compare


def _ts(epoch: float) -> datetime:
    return datetime.fromtimestamp(epoch, tz=UTC)


def _json_values(col: pd.Series) -> list:
    vals: set = set()
    for raw in col.dropna():
        vals.update(json.loads(raw) if isinstance(raw, str) else (raw or []))
    return sorted(vals)


def format_value(kv) -> str:
    if kv.value is None:
        return "—"
    if kv.unit == "usd":
        return f"${kv.value:,.2f}"
    if kv.unit == "ratio":
        return f"{kv.value:.1%}"
    if kv.unit == "hours":
        return f"{kv.value:,.1f} h"
    return (
        f"{kv.value:,.1f}"
        if isinstance(kv.value, float) and not kv.value.is_integer()
        else f"{int(kv.value):,}"
    )


def format_delta(kv, prev_value: float | None) -> str | None:
    """Formatted delta vs a previous-period value, styled by unit."""
    if prev_value is None or kv.value is None:
        return None
    d = kv.value - prev_value
    if kv.unit == "usd":
        return f"{'+' if d >= 0 else '-'}${abs(d):,.2f}"
    if kv.unit == "ratio":
        return f"{d * 100:+.1f} pp"
    if kv.unit == "hours":
        return f"{d:+.1f} h"
    return f"{d:+,.0f}"


def kpi_card(kv, prev_value: float | None = None, col=None) -> None:
    """Render one KPI as a metric card with dependency badges."""
    c = col or st
    if not kv.available:
        c.metric(kv.label, "n/a")
        c.caption(
            f"not available: {kv.note or ', '.join(DEPENDS_LABELS.get(d, d) for d in kv.depends_on)}"
        )
        return
    c.metric(kv.label, format_value(kv), delta=format_delta(kv, prev_value))
    badges = [DEPENDS_LABELS.get(d, d) for d in kv.depends_on]
    if badges:
        c.caption("; ".join(badges))
    if kv.note:
        c.caption(kv.note)


def chart(df: pd.DataFrame, fig, name: str, col=None) -> None:
    """Render a plotly figure plus a CSV download of its source data."""
    c = col or st
    c.plotly_chart(fig, use_container_width=True)
    c.download_button(
        f"Download {name} (CSV)",
        csv_bytes(df),
        file_name=f"{name}.csv",
        mime="text/csv",
        key=f"csv_{name}",
    )
