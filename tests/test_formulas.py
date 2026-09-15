"""Every KPI formula against a small hand-built fixture with expected numbers."""

import json
from datetime import UTC, datetime

import pandas as pd
import pytest

from devin_kpi.config import Settings
from devin_kpi.kpis.filters import FilterSet, previous_period
from devin_kpi.kpis.formulas import (
    compute_all,
    current_and_previous,
    human_sessions,
    is_service_session,
    leaderboard,
    status_detail_breakdown,
)


def ep(ts):
    return datetime.fromtimestamp(ts, tz=UTC)


def _session(sid, user, status, created, updated, acus, **kw):
    row = dict(
        session_id=sid,
        org_id="o1",
        user_id=user,
        status=status,
        title="t",
        tags_json="[]",
        created_at=created,
        updated_at=updated,
        acus_consumed=acus,
        origin="webapp",
        category="bug_fixing",
        subcategory="crash",
        playbook_id=None,
        automation_id=None,
        devin_mode="interactive",
        repo_names_json="[]",
        service_user_id=None,
        status_detail="user_request",
    )
    row.update(kw)
    return row


SESSIONS = pd.DataFrame(
    [
        _session("s5", "u9", "exit", 20000, 25000, 10.0),  # previous period only
        _session("s1", "u1", "exit", 100000, 107200, 4.0),
        _session("s2", "u2", "exit", 200000, 203600, 2.0),
        _session("s3", "u3", "running", 300000, 301800, 6.0),
        _session("s4", "u4", "exit", 400000, 407200, 8.0, playbook_id="pb1"),
    ]
)

# Machine-generated sessions inside the window: one via a service user
# (api origin), one via origin alone (code_scan). Both must be excluded from
# human adoption counts but still count toward volume/cost.
SERVICE_SESSIONS = pd.DataFrame(
    [
        _session(
            "s6",
            "svc1",
            "exit",
            405000,
            405600,
            1.0,
            origin="api",
            service_user_id="svc1",
            status_detail="usage_limit_exceeded",
        ),
        _session(
            "s7",
            "u7",
            "exit",
            406000,
            406600,
            1.0,
            origin="code_scan",
            status_detail="error",
        ),
    ]
)

PRS = pd.DataFrame(
    [
        dict(
            session_id="s1",
            pr_url="https://github.com/a/r/pull/1",
            pr_state="merged",
            provider="github",
            repo_full_name="a/r",
            pr_number=1,
            pr_created_at=100600,
            merged_at=108000,
            closed_at=108000,
            review_comments=3,
            review_rounds=2,
            additions=100,
            deletions=10,
            enriched_at=109000,
        ),
        dict(
            session_id="s2",
            pr_url="https://github.com/a/r/pull/2",
            pr_state="closed",
            provider="github",
            repo_full_name="a/r",
            pr_number=2,
            pr_created_at=None,
            merged_at=None,
            closed_at=None,
            review_comments=None,
            review_rounds=None,
            additions=None,
            deletions=None,
            enriched_at=None,
        ),
        dict(
            session_id="s4",
            pr_url="https://github.com/a/r/pull/3",
            pr_state="merged",
            provider="github",
            repo_full_name="a/r",
            pr_number=3,
            pr_created_at=None,
            merged_at=None,
            closed_at=None,
            review_comments=None,
            review_rounds=None,
            additions=None,
            deletions=None,
            enriched_at=None,
        ),
    ]
)

INSIGHTS = pd.DataFrame(
    [
        dict(
            session_id="s1",
            num_user_messages=4,
            num_devin_messages=8,
            session_size="S",
            analysis_json=None,
        ),
        dict(
            session_id="s2",
            num_user_messages=2,
            num_devin_messages=4,
            session_size="XS",
            analysis_json=json.dumps({"issues": [{"type": "flaky_ci"}]}),
        ),
        dict(
            session_id="s3",
            num_user_messages=6,
            num_devin_messages=12,
            session_size="M",
            analysis_json=None,
        ),
        dict(
            session_id="s4",
            num_user_messages=8,
            num_devin_messages=16,
            session_size="L",
            analysis_json=None,
        ),
        dict(
            session_id="s5",
            num_user_messages=1,
            num_devin_messages=2,
            session_size="XS",
            analysis_json=None,
        ),
    ]
)

ISSUES = pd.DataFrame(
    [
        dict(
            session_id="s1", issue_key="ENG-10", tracker="jira", story_points=5.0, fetched_at=100000
        ),
    ]
)

EMPTY_ISSUES = ISSUES.iloc[0:0]

F = FilterSet(start=ep(50000), end=ep(410000))


def results(settings=None, sessions=SESSIONS, prs=PRS, insights=INSIGHTS, issues=ISSUES, f=F):
    settings = settings or Settings(DEVIN_API_KEY="k", ACU_UNIT_PRICE=2.0, SEAT_COUNT=10)
    out = compute_all(sessions, prs, insights, issues, pd.DataFrame(), f, settings)
    return {k.key: k for k in out}


def test_throughput():
    r = results()
    assert r["sessions_completed"].value == 3
    assert r["prs_created"].value == 3
    assert r["prs_merged"].value == 2
    assert r["prs_closed_unmerged"].value == 1
    assert r["merge_rate"].value == pytest.approx(2 / 3)
    assert r["sessions_shipped_rate"].value == pytest.approx(0.5)
    assert r["human_takeover_rate"].available is False


def test_takeover_rate_from_reported():
    reported = {
        "metrics_prs": {"totals": {"prs_created_count": 100.0, "prs_taken_over_count": 12.0}}
    }
    settings = Settings(DEVIN_API_KEY="k", ACU_UNIT_PRICE=2.0, SEAT_COUNT=10)
    out = compute_all(
        SESSIONS, PRS, INSIGHTS, ISSUES, pd.DataFrame(), F, settings, reported=reported
    )
    r = {k.key: k for k in out}
    assert r["human_takeover_rate"].available is True
    assert r["human_takeover_rate"].value == pytest.approx(0.12)
    assert "API-reported" in r["human_takeover_rate"].note


def test_cycle_time():
    r = results()
    # terminal durations: 2h, 1h, 2h -> median 2h
    assert r["session_duration_median"].value == pytest.approx(2.0)
    assert r["session_duration_p90"].value == pytest.approx(2.0)
    # only s1 has merged_at: (108000-100000)/3600
    assert r["request_to_merge_median"].value == pytest.approx(8000 / 3600)
    # open->merge: (108000-100600)/3600
    assert r["pr_open_to_merge_median"].value == pytest.approx(7400 / 3600)


def test_cost():
    r = results()
    assert r["acus_per_session_mean"].value == pytest.approx(5.0)
    assert r["acus_per_session_median"].value == pytest.approx(5.0)
    assert r["total_acus"].value == pytest.approx(20.0)
    assert r["acus_per_merged_pr"].value == pytest.approx(10.0)
    assert r["cost_per_merged_pr"].value == pytest.approx(20.0)
    assert r["cost_per_session"].value == pytest.approx(10.0)
    # s1 linked, 4 acus / 5 pts = 0.8 acu/pt, *2 = 1.6
    assert r["acus_per_story_point"].value == pytest.approx(0.8)
    assert r["cost_per_story_point"].value == pytest.approx(1.6)
    assert r["total_cost"].value == pytest.approx(40.0)


def test_total_cost_unavailable_without_price():
    r = results(settings=Settings(DEVIN_API_KEY="k"))
    assert r["total_cost"].available is False
    assert "ACU_UNIT_PRICE" in r["total_cost"].depends_on


def test_adoption():
    r = results()
    assert r["dau"].value == 1  # only s4 within last day of window
    assert r["wau"].value == 4
    assert r["mau"].value == 4
    assert r["stickiness"].value == pytest.approx(0.25)
    assert r["active_vs_licensed"].value == pytest.approx(4 / 10)
    assert r["playbook_automation_share"].value == pytest.approx(0.25)


def test_service_session_detection():
    all_s = pd.concat([SESSIONS, SERVICE_SESSIONS], ignore_index=True)
    flags = is_service_session(all_s)
    assert list(all_s[flags].session_id) == ["s6", "s7"]
    assert set(human_sessions(all_s).session_id) == {"s1", "s2", "s3", "s4", "s5"}
    assert is_service_session(all_s.iloc[0:0]).empty


def test_adoption_excludes_service_sessions():
    all_s = pd.concat([SESSIONS, SERVICE_SESSIONS], ignore_index=True)
    r = results(sessions=all_s)
    # volume counts every session ...
    assert r["sessions_completed"].value == 5
    assert r["total_acus"].value == pytest.approx(22.0)
    # ... but adoption only counts humans (s6/s7 are on the last day)
    assert r["dau"].value == 1
    assert r["wau"].value == 4
    assert r["mau"].value == 4
    assert r["active_vs_licensed"].value == pytest.approx(4 / 10)
    assert "excludes 2 service" in r["mau"].note


def test_outcome_rates():
    all_s = pd.concat([SESSIONS, SERVICE_SESSIONS], ignore_index=True)
    r = results(sessions=all_s)
    assert r["usage_limit_hit_rate"].value == pytest.approx(1 / 6)
    assert r["usage_limit_hit_rate"].numerator == 1
    assert r["session_error_rate"].value == pytest.approx(1 / 6)
    empty = results(sessions=SESSIONS.iloc[0:0])
    assert empty["usage_limit_hit_rate"].available is False


def test_status_detail_breakdown():
    all_s = pd.concat([SESSIONS, SERVICE_SESSIONS], ignore_index=True)
    b = status_detail_breakdown(all_s).set_index("status_detail")
    assert b.loc["user_request", "sessions"] == 5
    assert b.loc["usage_limit_exceeded", "sessions"] == 1
    assert b.loc["error", "sessions"] == 1
    assert b.sessions.sum() == 7
    assert b.share.sum() == pytest.approx(1.0)
    assert list(status_detail_breakdown(all_s.iloc[0:0]).columns) == [
        "status_detail",
        "sessions",
        "share",
    ]


def test_leaderboard_by_user():
    lb = leaderboard(SESSIONS, PRS, "user_id", acu_price=2.0).set_index("user_id")
    assert list(lb.index[:2]) == ["u9", "u4"]  # sorted by ACUs desc: 10, 8
    assert lb.loc["u1", "sessions"] == 1
    assert lb.loc["u1", "prs_created"] == 1
    assert lb.loc["u1", "prs_merged"] == 1
    assert lb.loc["u1", "merge_rate"] == pytest.approx(1.0)
    assert lb.loc["u1", "acus_per_merged_pr"] == pytest.approx(4.0)
    assert lb.loc["u1", "cost"] == pytest.approx(8.0)
    assert lb.loc["u2", "merge_rate"] == pytest.approx(0.0)
    assert pd.isna(lb.loc["u3", "merge_rate"])  # no PRs
    assert pd.isna(lb.loc["u3", "acus_per_merged_pr"])


def test_leaderboard_by_org_and_top():
    lb = leaderboard(SESSIONS, PRS, "org_id")
    assert len(lb) == 1
    assert lb.iloc[0].sessions == 5
    assert lb.iloc[0].prs_merged == 2
    assert "cost" not in lb.columns
    assert len(leaderboard(SESSIONS, PRS, "user_id", top=2)) == 2
    assert leaderboard(SESSIONS.iloc[0:0], PRS, "user_id").empty
    no_prs = leaderboard(SESSIONS, PRS.iloc[0:0], "user_id")
    assert (no_prs.prs_created == 0).all()


def test_quality():
    r = results()
    assert r["large_session_share"].value == pytest.approx(0.25)
    assert r["user_messages_per_session"].value == pytest.approx(5.0)
    assert r["closed_without_merge_rate"].value == pytest.approx(1 / 3)
    assert r["review_comments_per_merged_pr"].value == pytest.approx(3.0)
    assert r["review_rounds_per_merged_pr"].value == pytest.approx(2.0)


def test_unavailable_without_price():
    r = results(settings=Settings(DEVIN_API_KEY="k"))
    assert r["cost_per_merged_pr"].available is False
    assert r["cost_per_session"].available is False
    assert r["cost_per_story_point"].available is False
    # ACU versions still fine
    assert r["acus_per_merged_pr"].available is True


def test_demo_mode_assumes_two_dollar_acu():
    settings = Settings()  # no key, no price -> demo mode
    assert settings.demo_mode
    assert settings.effective_acu_unit_price == 2.0
    r = results(settings=settings)
    # dollar KPIs render with the assumed price: mean 5 acu * $2 = $10
    assert r["cost_per_session"].value == pytest.approx(10.0)
    # explicit price still wins
    assert Settings(DEVIN_API_KEY=None, ACU_UNIT_PRICE=3.0).effective_acu_unit_price == 3.0
    assert Settings(DEVIN_API_KEY="k").effective_acu_unit_price is None


def test_unavailable_without_git_enrichment():
    prs = PRS.assign(enriched_at=None, merged_at=None)
    r = results(prs=prs)
    for k in (
        "request_to_merge_median",
        "request_to_merge_p90",
        "pr_open_to_merge_median",
        "pr_open_to_merge_p90",
        "review_comments_per_merged_pr",
        "review_rounds_per_merged_pr",
    ):
        assert r[k].available is False, k


def test_unavailable_without_tracker():
    r = results(issues=EMPTY_ISSUES)
    assert r["acus_per_story_point"].available is False
    assert r["cost_per_story_point"].available is False


def test_unavailable_without_seat_count():
    r = results(settings=Settings(DEVIN_API_KEY="k", ACU_UNIT_PRICE=2.0))
    assert r["active_vs_licensed"].available is False


def test_period_comparison():
    settings = Settings(DEVIN_API_KEY="k", ACU_UNIT_PRICE=2.0, SEAT_COUNT=10)
    table = current_and_previous(SESSIONS, PRS, INSIGHTS, ISSUES, pd.DataFrame(), F, settings)
    row = table.set_index("key").loc["sessions_completed"]
    assert row["value"] == 3
    assert row["previous"] == 1  # s5 in previous window
    assert row["delta"] == 2
    assert row["delta_pct"] == pytest.approx(2.0)


def test_previous_period_window():
    p = previous_period(F)
    assert abs((p.end - p.start) - (F.end - F.start)).total_seconds() < 1
    assert p.end < F.start


def test_org_filter():
    f = FilterSet(start=ep(0), end=ep(500000), org_ids=["nope"])
    r = results(f=f)
    assert r["sessions_completed"].value == 0
