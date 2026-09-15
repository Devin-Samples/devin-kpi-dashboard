"""Pure series function tests."""

import pandas as pd
from test_formulas import INSIGHTS, PRS, SESSIONS, _session

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


def test_rolling_actives_see_sessions_before_range():
    """MAU on day 1 of a 30-day range must count users active in the
    trailing 30 days even if their sessions fall outside the range."""
    day = 86400
    now = 60 * day  # arbitrary epoch
    sessions = pd.DataFrame(
        [
            _session("a1", "old_user", "finished", now - 31 * day, now - 31 * day + 100, 1.0),
            _session(
                "a2", "new_user", "finished", now - 30 * day + 3600, now - 30 * day + 3700, 1.0
            ),
        ]
    )
    mau = active_users_rolling(sessions, 30)
    from datetime import UTC, datetime

    from devin_kpi.kpis.filters import FilterSet, clip_dates

    f = FilterSet(
        start=datetime.fromtimestamp(now - 30 * day, tz=UTC),
        end=datetime.fromtimestamp(now + day, tz=UTC),
    )
    clipped = clip_dates(mau, "date", f)
    # day 1 of the range: old_user (session outside the range but inside
    # the trailing 30-day window) AND new_user are counted -> 2, not 1.
    # Computing the rolling window over range-filtered sessions would drop
    # old_user's session entirely.
    assert clipped.iloc[0].active_users == 2


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
