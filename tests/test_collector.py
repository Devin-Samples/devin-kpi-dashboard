"""Collector tests with respx: idempotency (run twice -> same row counts)
and issue-key extraction."""

from datetime import UTC, datetime, timedelta

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
    "devin_mode": "interactive",
    "repo_names": ["acme/widgets"],
    "pull_requests": [{"pr_url": "https://github.com/acme/widgets/pull/7", "pr_state": "merged"}],
}

INSIGHT = {
    "session_id": "ses_1",
    "num_user_messages": 3,
    "num_devin_messages": 9,
    "session_size": "S",
    "analysis": {"issues": [{"type": "flaky_ci"}]},
}


def _mock_all():
    respx.get(f"{BASE}/v3/enterprise/metrics/usage").mock(
        return_value=httpx.Response(200, json={"sessions_count": 1})
    )
    respx.get(f"{BASE}/v3/enterprise/sessions/insights").mock(
        return_value=httpx.Response(200, json={"items": [INSIGHT], "has_next_page": False})
    )
    respx.get(f"{BASE}/v3/enterprise/sessions").mock(
        return_value=httpx.Response(200, json={"items": [SESSION], "has_next_page": False})
    )
    for name in ("sessions", "prs", "sessions-by-category", "dau", "wau", "mau", "active-users"):
        respx.get(f"{BASE}/v3/enterprise/metrics/{name}").mock(
            return_value=httpx.Response(200, json={"sessions_created_count": 1})
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
                        "acus_by_product": {"devin": 2.0, "cascade": 0.5},
                    }
                ],
            },
        )
    )
    respx.get(f"{BASE}/v3/enterprise/consumption/cycles").mock(
        return_value=httpx.Response(
            200, json={"cycles": [{"cycle_start": 1_699_000_000, "cycle_end": 1_702_000_000}]}
        )
    )
    respx.get(f"{BASE}/v3/enterprise/code-scans/metrics").mock(
        return_value=httpx.Response(200, json={"scans_count": 5})
    )
    respx.get(f"{BASE}/v3/enterprise/audit-logs").mock(
        return_value=httpx.Response(
            200,
            json={
                "items": [
                    {
                        "event_id": "e1",
                        "occurred_at": 1_700_000_000,
                        "event_type": "user_added",
                        "actor": "u1",
                    }
                ],
                "has_next_page": False,
            },
        )
    )


def _settings(tmp_path) -> Settings:
    return Settings(DEVIN_API_KEY="cog_test", DATABASE_PATH=str(tmp_path / "t.sqlite"))


@respx.mock
def test_collect_idempotent(tmp_path):
    _mock_all()
    settings = _settings(tmp_path)
    store = Store(settings.DATABASE_PATH)
    client = DevinClient("cog_test", BASE)
    client._sleep = lambda s: None
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
        )
    }
    collect(settings, since, until, store, client=client)
    counts2 = {t: store.count(t) for t in counts1}
    assert counts1 == counts2
    assert counts1["sessions"] == 1
    assert counts1["session_prs"] == 1
    client.close()


@respx.mock
def test_issue_key_extraction(tmp_path):
    _mock_all()
    settings = _settings(tmp_path)
    store = Store(settings.DATABASE_PATH)
    client = DevinClient("cog_test", BASE)
    client._sleep = lambda s: None
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
    client = DevinClient("cog_test", BASE)
    client._sleep = lambda s: None
    since = datetime.fromtimestamp(1_699_999_000, tz=UTC)
    collect(settings, since, since + timedelta(days=1), store, client=client)
    pr = store.read_df("session_prs").iloc[0]
    assert pr.provider == "github"
    assert pr.repo_full_name == "acme/widgets"
    assert pr.pr_number == 7
    client.close()
