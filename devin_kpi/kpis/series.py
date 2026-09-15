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
