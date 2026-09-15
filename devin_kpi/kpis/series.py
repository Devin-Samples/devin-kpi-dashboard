"""Pure time-series helpers over fact-table DataFrames (no DB access).

All functions take already-loaded DataFrames and return small DataFrames
suitable for plotting; callers filter first so every chart respects the
sidebar filters.
"""

from __future__ import annotations

import pandas as pd


def _ts(epochs: pd.Series) -> pd.Series:
    return pd.to_datetime(epochs, unit="s", utc=True)


def daily_active_users(sessions: pd.DataFrame) -> pd.DataFrame:
    """One row per day: distinct users with >=1 session that day.
    Returns columns [date, active_users]."""
    if sessions.empty:
        return pd.DataFrame(columns=["date", "active_users"])
    df = sessions.assign(date=_ts(sessions.created_at).dt.floor("D"))
    out = df.groupby("date").user_id.nunique().reset_index(name="active_users")
    return out


def active_users_rolling(sessions: pd.DataFrame, window_days: int) -> pd.DataFrame:
    """Rolling distinct-user count over `window_days` ending each day.
    Returns columns [date, active_users]."""
    if sessions.empty:
        return pd.DataFrame(columns=["date", "active_users"])
    df = sessions.assign(date=_ts(sessions.created_at).dt.floor("D"))
    days = pd.date_range(df.date.min(), df.date.max(), freq="D", tz="UTC")
    rows = []
    for d in days:
        mask = (df.date > d - pd.Timedelta(days=window_days)) & (df.date <= d)
        rows.append({"date": d, "active_users": df[mask].user_id.nunique()})
    return pd.DataFrame(rows)


def weekly_session_counts(sessions: pd.DataFrame) -> pd.DataFrame:
    """Sessions created per ISO week. Columns [week, sessions]."""
    if sessions.empty:
        return pd.DataFrame(columns=["week", "sessions"])
    df = sessions.assign(week=_ts(sessions.created_at).dt.to_period("W-SUN").dt.start_time)
    return df.groupby("week").size().reset_index(name="sessions")


def weekly_acus(sessions: pd.DataFrame) -> pd.DataFrame:
    """ACUs consumed per ISO week (by session creation). Columns [week, acus]."""
    if sessions.empty:
        return pd.DataFrame(columns=["week", "acus"])
    df = sessions.assign(week=_ts(sessions.created_at).dt.to_period("W-SUN").dt.start_time)
    return df.groupby("week").acus_consumed.sum(min_count=1).fillna(0.0).reset_index(name="acus")


def weekly_merged_prs(prs: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    """Merged PRs per ISO week. Columns [week, prs_merged]."""
    wk = weekly_pr_counts(prs, sessions)
    if wk.empty:
        return pd.DataFrame(columns=["week", "prs_merged"])
    merged = wk[wk.pr_state == "merged"]
    return merged.groupby("week").prs.sum().reset_index(name="prs_merged")


def daily_audit_events(audit: pd.DataFrame, top: int = 8) -> pd.DataFrame:
    """Audit events per day by action type; types outside the `top` most
    frequent are folded into "other". Columns [date, event_type, events].
    Never includes actor columns."""
    if audit.empty:
        return pd.DataFrame(columns=["date", "event_type", "events"])
    df = audit.assign(
        date=_ts(audit.occurred_at).dt.floor("D"),
        event_type=audit.event_type.fillna("unknown"),
    )
    keep = df.event_type.value_counts().head(top).index
    df["event_type"] = df.event_type.where(df.event_type.isin(keep), "other")
    return df.groupby(["date", "event_type"]).size().reset_index(name="events")


def audit_event_counts(audit: pd.DataFrame) -> pd.DataFrame:
    """Total events per action type. Columns [event_type, events]."""
    if audit.empty:
        return pd.DataFrame(columns=["event_type", "events"])
    return (
        audit.event_type.fillna("unknown")
        .value_counts()
        .rename_axis("event_type")
        .reset_index(name="events")
    )


def weekly_pr_counts(prs: pd.DataFrame, sessions: pd.DataFrame) -> pd.DataFrame:
    """PRs per week by state. Columns [week, pr_state, prs]."""
    if prs.empty or sessions.empty:
        return pd.DataFrame(columns=["week", "pr_state", "prs"])
    m = prs.merge(sessions[["session_id", "created_at"]], on="session_id")
    m = m.assign(
        week=_ts(m.created_at).dt.to_period("W-SUN").dt.start_time,
        pr_state=m.pr_state.str.lower(),
    )
    return m.groupby(["week", "pr_state"]).size().reset_index(name="prs")


def weekly_user_messages(sessions: pd.DataFrame, insights: pd.DataFrame) -> pd.DataFrame:
    """Mean num_user_messages per week. Columns [week, avg_user_messages]."""
    if sessions.empty or insights.empty:
        return pd.DataFrame(columns=["week", "avg_user_messages"])
    m = insights.merge(sessions[["session_id", "created_at"]], on="session_id")
    m = m.assign(week=_ts(m.created_at).dt.to_period("W-SUN").dt.start_time)
    return m.groupby("week").num_user_messages.mean().reset_index(name="avg_user_messages")


def request_to_merge_hours(sessions: pd.DataFrame, prs: pd.DataFrame) -> pd.DataFrame:
    """Hours from session creation to PR merge for merged, enriched PRs.
    Columns [session_id, hours]."""
    if prs.empty or sessions.empty:
        return pd.DataFrame(columns=["session_id", "hours"])
    m = prs[prs.pr_state.str.lower() == "merged"].merge(
        sessions[["session_id", "created_at"]], on="session_id"
    )
    m = m.assign(hours=(m.merged_at - m.created_at) / 3600.0)
    return m[["session_id", "hours"]].dropna()


def session_duration_hours(sessions: pd.DataFrame, terminal_mask: pd.Series) -> pd.DataFrame:
    """Hours updated-created for terminal sessions. Columns [session_id, hours]."""
    t = sessions[terminal_mask]
    return t.assign(hours=(t.updated_at - t.created_at) / 3600.0)[["session_id", "hours"]]
