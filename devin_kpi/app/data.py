"""Data loading for the Streamlit app. Cached loaders read the local
SQLite store; in demo mode the synthetic DB is generated on first run."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from devin_kpi.config import Settings
from devin_kpi.store import Store


def get_settings() -> Settings:
    return Settings()


def db_path() -> str:
    settings = get_settings()
    if settings.demo_mode:
        from devin_kpi.synth.generate import ensure_demo_db

        ensure_demo_db(settings).close()
    return str(settings.resolved_db_path)


def store() -> Store:
    return Store(db_path())


@st.cache_data(ttl=300)
def load_table(table: str) -> pd.DataFrame:
    import pandas as pd  # noqa: F401

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
