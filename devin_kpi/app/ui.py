"""Shared Streamlit UI helpers: sidebar filters, KPI cards, chart + CSV
export."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pandas as pd
import streamlit as st

from devin_kpi.kpis.filters import FilterSet
from devin_kpi.kpis.formulas import LOWER_IS_BETTER, NEUTRAL, KpiValue

DEPENDS_LABELS = {
    "git_enrichment": "needs git token (GITHUB_TOKEN / GITLAB_TOKEN / AZURE_DEVOPS_PAT)",
    "tracker_enrichment": "needs tracker credentials (Jira / Linear)",
    "ACU_UNIT_PRICE": "needs ACU_UNIT_PRICE",
    "SEAT_COUNT": "needs SEAT_COUNT",
}


def needs_setup(kv: KpiValue) -> bool:
    """True when the KPI is unavailable because an optional integration or
    config value is missing (as opposed to simply having no data in the
    period). Such KPIs are hidden from the main layout."""
    return not kv.available and bool(kv.depends_on)


def split_configured(kvs: list[KpiValue]) -> tuple[list[KpiValue], list[KpiValue]]:
    shown = [k for k in kvs if not needs_setup(k)]
    hidden = [k for k in kvs if needs_setup(k)]
    return shown, hidden


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

    def optional_multi(label, values):
        # Filters with nothing to pick from (e.g. the API returned no repo
        # names) are omitted rather than shown empty.
        return multi(label, values) if values else []

    org_ids = multi("Organizations", sessions.org_id.unique() if not sessions.empty else [])
    user_ids = multi("Users", sessions.user_id.unique() if not sessions.empty else [])
    categories = multi("Categories", sessions.category.unique() if not sessions.empty else [])
    origins = multi("Origins", sessions.origin.unique() if not sessions.empty else [])
    repos = optional_multi(
        "Repositories", _json_values(sessions.repo_names_json) if not sessions.empty else []
    )
    tags = optional_multi("Tags", _json_values(sessions.tags_json) if not sessions.empty else [])
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
        return f"${kv.value:,.0f}" if abs(kv.value) >= 1000 else f"${kv.value:,.2f}"
    if kv.unit == "ratio":
        return f"{kv.value:.1%}"
    if kv.unit == "hours":
        return f"{kv.value:,.1f} h"
    return (
        f"{kv.value:,.1f}"
        if isinstance(kv.value, float) and not kv.value.is_integer()
        else f"{int(kv.value):,}"
    )


def md_escape(text: str) -> str:
    """Escape `$` so Streamlit markdown does not treat dollar amounts as LaTeX."""
    return text.replace("$", r"\$")


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


def delta_color(kv: KpiValue, prev_value: float | None = None) -> str:
    """Streamlit delta colour: neutral for volume KPIs and for a delta that
    rounds to zero (which would otherwise render as a green/red arrow)."""
    if kv.key in NEUTRAL or _is_flat(kv, prev_value):
        return "off"
    return "inverse" if kv.key in LOWER_IS_BETTER else "normal"


def _is_flat(kv: KpiValue, prev_value: float | None) -> bool:
    if prev_value is None or kv.value is None:
        return False
    # half of the smallest increment `format_delta` prints for this unit
    tol = {"ratio": 0.0005, "usd": 0.005, "hours": 0.05}.get(kv.unit, 0.5)
    return abs(kv.value - prev_value) < tol


def kpi_card(kv, prev_value: float | None = None, col=None, help_text: str | None = None) -> None:
    """Render one KPI as a metric card with dependency badges."""
    c = col or st
    if not kv.available:
        c.metric(kv.label, "n/a", help=help_text)
        c.caption(
            f"not available: {kv.note or ', '.join(DEPENDS_LABELS.get(d, d) for d in kv.depends_on)}"
        )
        return
    c.metric(
        kv.label,
        format_value(kv),
        delta=format_delta(kv, prev_value),
        delta_color=delta_color(kv, prev_value),
        help=help_text,
    )
    if kv.note:
        c.caption(kv.note)


def kpi_row(
    kvs: dict[str, KpiValue],
    keys: tuple[str, ...] | list[str],
    prev: dict[str, KpiValue] | None = None,
    help_texts: dict[str, str] | None = None,
) -> list[KpiValue]:
    """Render a row of KPI cards, skipping KPIs that need setup.

    Returns the skipped KPIs so the page can list them once via
    `setup_expander`."""
    shown, hidden = split_configured([kvs[k] for k in keys])
    if shown:
        for c, kv in zip(st.columns(len(shown)), shown):
            pv = prev[kv.key].value if prev and kv.key in prev else None
            kpi_card(kv, pv, col=c, help_text=(help_texts or {}).get(kv.key))
    return hidden


def setup_expander(hidden: list[KpiValue]) -> None:
    """Collapsed list of KPIs that would appear once optional setup exists."""
    if not hidden:
        return
    with st.expander(f"{len(hidden)} more KPIs available with optional setup"):
        for kv in hidden:
            st.markdown(
                f"- **{kv.label}** — " + "; ".join(DEPENDS_LABELS.get(d, d) for d in kv.depends_on)
            )


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
