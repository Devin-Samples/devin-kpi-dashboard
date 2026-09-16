"""Data loading for the Streamlit app. Cached loaders read the local
SQLite store; in demo mode the synthetic DB is generated on first run."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st

from devin_kpi.app.ui import sidebar_filters
from devin_kpi.config import Settings
from devin_kpi.kpis.filters import FilterSet, apply_filters, previous_period
from devin_kpi.kpis.formulas import KpiValue, compute_all
from devin_kpi.kpis.metrics_reported import reported_metrics
from devin_kpi.store import Store
from devin_kpi.synth.generate import ensure_demo_db


def get_settings() -> Settings:
    return Settings()


def db_path() -> str:
    settings = get_settings()
    if settings.demo_mode:
        ensure_demo_db(settings).close()
    return str(settings.resolved_db_path)


def store() -> Store:
    return Store(db_path())


@st.cache_data(ttl=300)
def load_table(table: str) -> pd.DataFrame:
    s = store()
    try:
        return s.read_df(table)
    finally:
        s.close()


@st.cache_data(ttl=300)
def load_all() -> dict:
    s = store()
    try:
        return {
            "sessions": s.read_df("sessions"),
            "prs": s.read_df("session_prs"),
            "insights": s.read_df("session_insights"),
            "issues": s.read_df("session_issues"),
            "consumption": s.read_df("consumption_daily"),
            "cycles": s.read_df("billing_cycles"),
            "snapshots": s.read_df("metrics_snapshots"),
            "audit_logs": s.read_df("audit_logs"),
            "collector_runs": s.read_df("collector_runs"),
            "meta": {r.key: r.value for r in s.read_df("meta").itertuples()},
        }
    finally:
        s.close()


@dataclass
class PageContext:
    """Everything a KPI page needs after the sidebar has been rendered."""

    data: dict
    settings: Settings
    f: FilterSet
    compare: bool
    sessions: pd.DataFrame
    prs: pd.DataFrame
    insights: pd.DataFrame
    issues: pd.DataFrame
    reported: dict
    kvs: dict[str, KpiValue]
    prev: dict[str, KpiValue]

    def prev_value(self, key: str) -> float | None:
        kv = self.prev.get(key)
        return kv.value if kv else None


def _subset(df: pd.DataFrame, session_ids: pd.Series) -> pd.DataFrame:
    return df[df.session_id.isin(session_ids)] if not df.empty else df


def _compute(d: dict, f: FilterSet, settings: Settings, reported: dict) -> dict[str, KpiValue]:
    # compute_all applies `f` itself; it needs the unfiltered facts so that
    # trailing-window KPIs (DAU/WAU/MAU) can look back past the period start.
    kvs = compute_all(
        d["sessions"],
        d["prs"],
        d["insights"],
        d["issues"],
        d["consumption"],
        f,
        settings,
        reported=reported,
    )
    return {k.key: k for k in kvs}


def page_context(title: str) -> PageContext:
    """Render page chrome + sidebar, load data and compute current (and, if
    requested, previous-period) KPIs. Shared by every page."""
    st.set_page_config(page_title=title, layout="wide")
    st.title(title)
    demo_banner()
    d = load_all()
    settings = get_settings()
    f, compare = sidebar_filters(d)
    s, p = apply_filters(d["sessions"], d["prs"], f)

    st_ = store()
    try:
        reported = reported_metrics(st_, f.start, f.end)
    finally:
        st_.close()

    kvs = _compute(d, f, settings, reported)
    prev = _compute(d, previous_period(f), settings, reported) if compare else {}
    return PageContext(
        data=d,
        settings=settings,
        f=f,
        compare=compare,
        sessions=s,
        prs=p,
        insights=_subset(d["insights"], s.session_id),
        issues=_subset(d["issues"], s.session_id),
        reported=reported,
        kvs=kvs,
        prev=prev,
    )


def demo_banner() -> None:
    """Render the persistent demo banner / empty-DB instructions."""
    settings = get_settings()
    if settings.demo_mode:
        st.warning("DEMO MODE — synthetic data. Set DEVIN_API_KEY to use real data.")
    else:
        s = store()
        try:
            empty = s.count("sessions") == 0
        finally:
            s.close()
        if empty:
            st.info(
                "No data collected yet. Run: `python -m devin_kpi collect --since 90d` "
                "(then `python -m devin_kpi enrich` for optional PR/tracker enrichment)."
            )
