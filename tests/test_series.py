"""Pure series function tests."""

import pandas as pd
from test_formulas import INSIGHTS, PRS, SESSIONS

from devin_kpi.kpis.series import (
    active_users_rolling,
    daily_active_users,
    weekly_pr_counts,
    weekly_session_counts,
    weekly_user_messages,
)


def test_daily_active_users():
    df = daily_active_users(SESSIONS)
    assert df.active_users.sum() == SESSIONS.user_id.nunique()
    assert (
        len(df)
        == SESSIONS.created_at.map(
            lambda t: int(pd.Timestamp(t, unit="s", tz="UTC").floor("D").timestamp())
        ).nunique()
    )


def test_active_users_rolling():
    wau = active_users_rolling(SESSIONS, 7)
    # all sessions within seconds of each other -> rolling 7d sees all users
    assert wau.active_users.max() == SESSIONS.user_id.nunique()


def test_weekly_session_counts():
    df = weekly_session_counts(SESSIONS)
    assert df.sessions.sum() == len(SESSIONS)


def test_weekly_pr_counts():
    df = weekly_pr_counts(PRS, SESSIONS)
    assert df.prs.sum() == len(PRS)
    assert set(df.pr_state) == {"merged", "closed"}


def test_weekly_user_messages():
    df = weekly_user_messages(SESSIONS, INSIGHTS)
    assert df.avg_user_messages.notna().all()


def test_empty_inputs():
    empty = SESSIONS.iloc[0:0]
    assert daily_active_users(empty).empty
    assert weekly_session_counts(empty).empty
