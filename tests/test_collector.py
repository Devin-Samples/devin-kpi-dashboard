"""Collector tests with respx: idempotency, refresh re-pull, issue-key
extraction, PR url parsing."""

from datetime import UTC, date, datetime, timedelta

import httpx
import respx

from devin_kpi.api.client import DevinClient
from devin_kpi.collector.run import collect
from devin_kpi.config import Settings
from devin_kpi.store import Store

BASE = "https://api.devin.ai"

SESSION = {
    "session_id": "ses_1",
    "org_id": "o1",
    "user_id": "u1",
    "status": "finished",
    "title": "[ABC-123] fix crash",
    "tags": ["backend", "ABC-123"],
    "created_at": 1_700_000_000,
    "updated_at": 1_700_003_600,
    "acus_consumed": 2.5,
    "origin": "webapp",
    "category": "bug_fixing",
    "subcategory": "crash_fix",
    "playbook_id": None,
    "automation_id": None,
    "devin_mode": "normal",
    "is_archived": False,
    "parent_session_id": None,
    "service_user_id": None,
    "status_detail": "finished",
    "url": "https://app.devin.ai/sessions/ses_1",
    "repo_names": ["acme/widgets"],
    "pull_requests": [{"pr_url": "https://github.com/acme/widgets/pull/7", "pr_state": "merged"}],
}

INSIGHT = {
    "session_id": "ses_1",
    "num_user_messages": 3,
    "num_devin_messages": 9,
    "session_size": "S",
    "analysis": {
        "issues": [{"id": "i1", "label": "flaky_ci", "title": "Flaky CI", "impact": "medium"}]
    },
}


def _mock_all():
    respx.get(f"{BASE}/v3/enterprise/metrics/usage").mock(
        return_value=httpx.Response(
            200,
            json={
                "sessions_count": 1,
                "searches_count": 0,
                "prs_created_count": 1,
                "prs_merged_count": 1,
            },
        )
    )
    respx.get(f"{BASE}/v3/enterprise/sessions/insights").mock(
        return_value=httpx.Response(200, json={"items": [INSIGHT], "has_next_page": False})
    )
    respx.get(f"{BASE}/v3/enterprise/sessions").mock(
        return_value=httpx.Response(200, json={"items": [SESSION], "has_next_page": False})
    )
    respx.get(f"{BASE}/v3/enterprise/metrics/sessions").mock(
        return_value=httpx.Response(
            200,
            json={
                "sessions_created_count": 1,
                "sessions_created_by_size": {"xs": 0, "s": 1, "m": 0, "l": 0, "xl": 0},
                "sessions_created_by_origin": {"webapp": 1},
                "sessions_created_with_playbook_count": 0,
                "sessions_created_with_search_count": 0,
                "sessions_with_merged_prs_count": 1,
                "sessions_with_merged_prs_by_size": {"xs": 0, "s": 1, "m": 0, "l": 0, "xl": 0},
                "avg_acus_per_session": 2.5,
            },
        )
    )
    respx.get(f"{BASE}/v3/enterprise/metrics/prs").mock(
        return_value=httpx.Response(
            200,
            json={
                "prs_created_count": 1,
                "prs_opened_count": 0,
                "prs_merged_count": 1,
                "prs_closed_count": 0,
                "prs_taken_over_count": 0,
                "prs_taken_over_opened_count": 0,
                "prs_taken_over_merged_count": 0,
                "prs_taken_over_closed_count": 0,
            },
        )
    )
    respx.get(f"{BASE}/v3/enterprise/metrics/sessions-by-category").mock(
        return_value=httpx.Response(
            200,
            json={
                "categories": [
                    {
                        "category": "bug_fixing",
                        "sessions_count": 1,
                        "acus": 2.5,
                        "subcategories": [
                            {
                                "subcategory_id": "crash_fix",
                                "display_name": "Crash fix",
                                "sessions_count": 1,
                                "acus": 2.5,
                            }
                        ],
                    }
                ]
            },
        )
    )
    active_series = [{"start_time": 1_699_900_000, "end_time": 1_700_000_000, "active_users": 3}]
    for name in ("dau", "wau", "mau"):
        respx.get(f"{BASE}/v3/enterprise/metrics/{name}").mock(
            return_value=httpx.Response(200, json=active_series)
        )
    respx.get(f"{BASE}/v3/enterprise/metrics/active-users").mock(
        return_value=httpx.Response(
            200, json={"start_time": 1_699_900_000, "end_time": 1_700_000_000, "active_users": 5}
        )
    )
    respx.get(f"{BASE}/v3/enterprise/consumption/daily").mock(
        return_value=httpx.Response(
            200,
            json={
                "total_acus": 2.5,
                "consumption_by_date": [
                    {
                        "date": 1_700_000_000,
                        "acus": 2.5,
                        "acus_by_product": {
                            "devin": 2.0,
                            "cascade": 0.5,
                            "terminal": None,
                            "review": 0.0,
                        },
                    }
                ],
            },
        )
    )
    respx.get(f"{BASE}/v3/enterprise/consumption/cycles").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [{"after": 1_699_000_000, "before": 1_702_000_000}],
                "has_next_page": False,
            },
        )
    )
    respx.get(f"{BASE}/v3/enterprise/code-scans/metrics").mock(
        return_value=httpx.Response(
            200,
            json={
                "scans_count": 5,
                "repos_scanned_count": 2,
                "prs_created_count": 4,
                "prs_open_count": 1,
                "prs_merged_count": 3,
                "prs_closed_count": 0,
                "avg_pr_time_to_merge_seconds": 86400,
                "avg_pr_open_duration_seconds": 40000,
                "open_critical_findings_count": 0,
                "open_high_findings_count": 1,
                "open_medium_findings_count": 2,
                "open_low_findings_count": 9,
            },
        )
    )
    respx.get(f"{BASE}/v3/enterprise/audit-logs").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "audit_log_id": "al_1",
                        "created_at": 1_700_000_000,
                        "action": "add_member",
                        "user_id": "u1",
                        "service_user_id": None,
                        "user_email": "u1@example.com",
                        "org_id": "o1",
                        "data": {},
                    }
                ],
                "has_next_page": False,
            },
        )
    )


def _settings(tmp_path) -> Settings:
    return Settings(DEVIN_API_KEY="cog_test", DATABASE_PATH=str(tmp_path / "t.sqlite"))


def _client() -> DevinClient:
    c = DevinClient("cog_test", BASE)
    c._sleep = lambda s: None
    return c


@respx.mock
def test_collect_idempotent_old_windows(tmp_path):
    """Windows older than refresh_days are not re-pulled on a second run."""
    _mock_all()
    settings = _settings(tmp_path)
    store = Store(settings.DATABASE_PATH)
    client = _client()
    since = datetime.fromtimestamp(1_699_999_000, tz=UTC)
    until = since + timedelta(days=1)

    collect(settings, since, until, store, client=client)
    counts1 = {
        t: store.count(t)
        for t in (
            "sessions",
            "session_prs",
            "session_insights",
            "session_issues",
            "consumption_daily",
            "billing_cycles",
            "audit_logs",
            "metrics_snapshots",
        )
    }
    collect(settings, since, until, store, client=client)
    counts2 = {t: store.count(t) for t in counts1}
    assert counts1 == counts2
    assert counts1["sessions"] == 1
    assert counts1["session_prs"] == 1
    # new session fields persisted
    row = store.read_df("sessions").iloc[0]
    assert row.url == "https://app.devin.ai/sessions/ses_1"
    assert row.status_detail == "finished"
    client.close()


@respx.mock
def test_collect_refresh_repulls_recent_window(tmp_path):
    """A window ending within refresh_days is re-pulled, idempotently."""
    _mock_all()
    settings = _settings(tmp_path)
    store = Store(settings.DATABASE_PATH)
    client = _client()
    # until = now -> the window ending now is inside the refresh window
    until = datetime.now(tz=UTC)
    since = until - timedelta(days=1)

    collect(settings, since, until, store, client=client)
    n_snaps = store.count("metrics_snapshots")
    collect(settings, since, until, store, client=client)
    # second run re-pulled (window end within refresh_days) but snapshots
    # were replaced, not duplicated
    assert store.count("metrics_snapshots") == n_snaps
    assert store.count("sessions") == 1
    client.close()


@respx.mock
def test_audit_actor_never_email(tmp_path):
    _mock_all()
    settings = _settings(tmp_path)
    store = Store(settings.DATABASE_PATH)
    client = _client()
    since = datetime.fromtimestamp(1_699_999_000, tz=UTC)
    collect(settings, since, since + timedelta(days=1), store, client=client)
    row = store.read_df("audit_logs").iloc[0]
    assert row.event_id == "al_1"
    assert row.event_type == "add_member"
    assert row.actor == "u1"  # user_id, not user_email
    client.close()


@respx.mock
def test_issue_key_extraction(tmp_path):
    _mock_all()
    settings = _settings(tmp_path)
    store = Store(settings.DATABASE_PATH)
    client = _client()
    since = datetime.fromtimestamp(1_699_999_000, tz=UTC)
    collect(settings, since, since + timedelta(days=1), store, client=client)
    df = store.read_df("session_issues")
    assert set(df.issue_key) == {"ABC-123"}  # deduped across title+tags
    client.close()


@respx.mock
def test_pr_url_parsed_in_collect(tmp_path):
    _mock_all()
    settings = _settings(tmp_path)
    store = Store(settings.DATABASE_PATH)
    client = _client()
    since = datetime.fromtimestamp(1_699_999_000, tz=UTC)
    collect(settings, since, since + timedelta(days=1), store, client=client)
    pr = store.read_df("session_prs").iloc[0]
    assert pr.provider == "github"
    assert pr.repo_full_name == "acme/widgets"
    assert pr.pr_number == 7
    client.close()


@respx.mock
def test_consumption_request_snapped_to_pacific(tmp_path):
    _mock_all()
    settings = _settings(tmp_path)
    store = Store(settings.DATABASE_PATH)
    client = _client()
    since = datetime(2024, 7, 14, 12, 0, tzinfo=UTC)  # mid-day PDT
    until = since + timedelta(hours=20)
    collect(settings, since, until, store, client=client)
    req = respx.get(f"{BASE}/v3/enterprise/consumption/daily").calls[0].request
    from devin_kpi.timeutil import pacific_day_start

    assert int(req.url.params["time_after"]) == pacific_day_start(date(2024, 7, 14))
    # until (2024-07-15 08:00Z) is 2024-07-15 in LA -> +1 day boundary
    assert int(req.url.params["time_before"]) == pacific_day_start(date(2024, 7, 16))
    client.close()
