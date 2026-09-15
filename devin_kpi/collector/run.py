"""Collector: idempotent, resumable pull of all Devin API endpoints into
the local SQLite store.

Sessions/insights and the count metrics are collected in daily windows
(collector_runs tracks window+endpoint -> status='done' for resume). The
dau/wau/mau endpoints return a whole-range array, so they are fetched once
per range; metrics/active-users likewise. consumption/daily is requested
with time_after/time_before snapped to Pacific-day boundaries. cycles is
paginated. Windows ending within `refresh_days` are re-pulled even if
marked done, so late-arriving status/ACU updates are picked up.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from devin_kpi.api.client import DevinClient, Endpoints, Scope
from devin_kpi.config import Settings
from devin_kpi.enrichment.pr_urls import parse_pr_url
from devin_kpi.store import Store
from devin_kpi.timeutil import day_windows, pacific_day_start, utc_now_epoch

log = logging.getLogger(__name__)

# Per-day windowed metrics.
DAILY_METRIC_ENDPOINTS = [
    "metrics_usage",
    "metrics_sessions",
    "metrics_prs",
    "metrics_by_category",
]

# Whole-range endpoints returning arrays of {start_time,end_time,active_users}
# (dau/wau/mau) or a single object (active-users).
RANGE_ACTIVE_ENDPOINTS = [
    "metrics_dau",
    "metrics_wau",
    "metrics_mau",
    "metrics_active_users",
]


def collect(
    settings: Settings,
    since: datetime,
    until: datetime,
    store: Store,
    client: DevinClient | None = None,
    refresh_days: int = 7,
) -> None:
    now = utc_now_epoch()
    own_client = client is None
    if own_client:
        assert settings.DEVIN_API_KEY, "collect requires DEVIN_API_KEY"
        client = DevinClient(
            settings.DEVIN_API_KEY, settings.DEVIN_API_BASE_URL, settings.DEVIN_ORG_ID
        )
    try:
        scope = client.detect_scope(now)
        store.set_meta("scope", scope)
        store.set_meta("demo", "false")
        ep = Endpoints(scope, client.org_id)
        tz = settings.CONSUMPTION_DAY_TZ

        def done(start: int, end: int, name: str) -> bool:
            """Window done and old enough to skip. Windows ending within
            refresh_days are re-pulled to pick up late updates."""
            if end >= now - refresh_days * 86400:
                return False
            return store.run_done(start, end, name)

        for start, end in day_windows(since, until, tz):
            _collect_sessions_window(client, store, ep, start, end, settings, done)
            for name in DAILY_METRIC_ENDPOINTS:
                _collect_metric_window(client, store, ep, name, scope, start, end, done)

        since_ts, until_ts = int(since.timestamp()), int(until.timestamp())
        for name in RANGE_ACTIVE_ENDPOINTS:
            _collect_metric_window(client, store, ep, name, scope, since_ts, until_ts, done)

        _collect_consumption(client, store, ep, scope, since, until, tz, done)
        _collect_cycles(client, store, ep)  # re-pulled every run
        _collect_code_scans(client, store, ep, since, until)  # re-pulled every run
        _collect_audit_logs(client, store, ep, since, until, done)

        store.set_meta("last_collect_at", str(utc_now_epoch()))
        store.commit()
    finally:
        if own_client:
            client.close()


# ---------------------------------------------------------------- sessions


def _collect_sessions_window(
    client: DevinClient,
    store: Store,
    ep: Endpoints,
    start: int,
    end: int,
    settings: Settings,
    done,
) -> None:
    issue_re = re.compile(settings.ISSUE_KEY_REGEX)

    for name, path in (("sessions", ep.path("sessions")), ("insights", ep.path("insights"))):
        if path is None or done(start, end, name):
            continue
        params = {"created_after": start, "created_before": end}
        for item in client.paginate(path, params):
            if name == "sessions":
                _store_session(store, item, issue_re)
            else:
                _store_insight(store, item)
        store.mark_run(start, end, name, "done", utc_now_epoch())
        store.commit()


def _store_session(store: Store, s: dict, issue_re: re.Pattern[str]) -> None:
    sid = s["session_id"]
    tags = s.get("tags") or []
    prs = s.get("pull_requests") or []
    repo_names = s.get("repo_names") or []
    store.upsert(
        "sessions",
        {
            "session_id": sid,
            "org_id": s.get("org_id"),
            "user_id": s.get("user_id"),
            "status": s.get("status"),
            "title": s.get("title"),
            "tags_json": json.dumps(tags),
            "created_at": s.get("created_at"),
            "updated_at": s.get("updated_at"),
            "acus_consumed": s.get("acus_consumed"),
            "origin": s.get("origin"),
            "category": s.get("category"),
            "subcategory": s.get("subcategory"),
            "playbook_id": s.get("playbook_id"),
            "automation_id": s.get("automation_id"),
            "devin_mode": s.get("devin_mode"),
            "is_archived": s.get("is_archived"),
            "parent_session_id": s.get("parent_session_id"),
            "service_user_id": s.get("service_user_id"),
            "status_detail": s.get("status_detail"),
            "url": s.get("url"),
            "repo_names_json": json.dumps(repo_names),
            "raw_json": json.dumps(s),
        },
    )
    now = utc_now_epoch()
    for pr in prs:
        url = pr.get("pr_url")
        if not url:
            continue
        parsed = parse_pr_url(url)
        store.upsert(
            "session_prs",
            {
                "session_id": sid,
                "pr_url": url,
                "pr_state": pr.get("pr_state"),
                "provider": parsed.provider if parsed else None,
                "repo_full_name": parsed.repo_full_name if parsed else None,
                "pr_number": parsed.pr_number if parsed else None,
                "pr_created_at": None,
                "merged_at": None,
                "closed_at": None,
                "review_comments": None,
                "review_rounds": None,
                "additions": None,
                "deletions": None,
                "enriched_at": None,
            },
        )
    # issue keys from title + tags
    haystacks = [s.get("title") or "", *tags]
    for key in {k for h in haystacks for k in issue_re.findall(h)}:
        store.upsert(
            "session_issues",
            {
                "session_id": sid,
                "issue_key": key,
                "tracker": None,
                "story_points": None,
                "fetched_at": now,
            },
        )


def _store_insight(store: Store, item: dict) -> None:
    store.upsert(
        "session_insights",
        {
            "session_id": item["session_id"],
            "num_user_messages": item.get("num_user_messages"),
            "num_devin_messages": item.get("num_devin_messages"),
            "session_size": item.get("session_size"),
            "analysis_json": json.dumps(item.get("analysis")) if item.get("analysis") else None,
        },
    )


# ----------------------------------------------------------------- metrics


def _collect_metric_window(
    client: DevinClient,
    store: Store,
    ep: Endpoints,
    name: str,
    scope: Scope,
    start: int,
    end: int,
    done,
) -> None:
    if done(start, end, name):
        return
    path = ep.path(name)
    if path is None:
        store.mark_run(start, end, name, "skipped", utc_now_epoch())
        return
    params = {"time_after": start, "time_before": end}
    try:
        payload = client.get(path, params)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (403, 404):
            log.info("skipping %s: %s", name, exc.response.status_code)
            store.mark_run(start, end, name, "skipped", utc_now_epoch())
            return
        raise
    # replace prior snapshot for this window (refresh re-pulls are common)
    store.delete_snapshots(name, start, end)
    store.insert_snapshot(
        {
            "endpoint": name,
            "scope": scope,
            "params_json": json.dumps(params),
            "window_start": start,
            "window_end": end,
            "fetched_at": utc_now_epoch(),
            "payload_json": json.dumps(payload),
        }
    )
    store.mark_run(start, end, name, "done", utc_now_epoch())
    store.commit()


# ------------------------------------------------------------- consumption


def _collect_consumption(
    client: DevinClient,
    store: Store,
    ep: Endpoints,
    scope: Scope,
    since: datetime,
    until: datetime,
    tz: str,
    done,
) -> None:
    path = ep.path("consumption_daily")
    if path is None:
        return
    zone = ZoneInfo(tz)
    # Snap request bounds to Pacific-day starts so buckets align with the
    # web app's daily consumption view.
    start_ts = pacific_day_start(since.astimezone(zone).date(), tz)
    end_ts = pacific_day_start(until.astimezone(zone).date() + timedelta(days=1), tz)
    if done(start_ts, end_ts, "consumption_daily"):
        return
    payload = client.get(path, {"time_after": start_ts, "time_before": end_ts})
    scope_id = client.org_id if scope == "organization" else "enterprise"
    rows = []
    for day in payload.get("consumption_by_date", []):
        ts = day.get("date")
        if ts is None:
            continue
        date_str = (
            datetime.fromtimestamp(ts, tz=zone).date().isoformat()
            if isinstance(ts, int | float)
            else str(ts)[:10]
        )
        by_product = day.get("acus_by_product") or {}
        total = 0.0
        for product in ("devin", "cascade", "terminal", "review"):
            acus = float(by_product.get(product) or 0.0)
            total += acus
            rows.append(
                {
                    "scope": scope,
                    "scope_id": scope_id,
                    "date": date_str,
                    "product": product,
                    "acus": acus,
                }
            )
        rows.append(
            {
                "scope": scope,
                "scope_id": scope_id,
                "date": date_str,
                "product": "total",
                "acus": float(day.get("acus", total)),
            }
        )
    store.upsert_many("consumption_daily", rows)
    store.mark_run(start_ts, end_ts, "consumption_daily", "done", utc_now_epoch())
    store.commit()


def _collect_cycles(client: DevinClient, store: Store, ep: Endpoints) -> None:
    """Billing cycles; paginated, re-pulled every run (idempotent upsert)."""
    path = ep.path("consumption_cycles")
    if path is None:
        return
    try:
        for item in client.paginate(path):
            store.upsert(
                "billing_cycles",
                {
                    "cycle_start": item.get("after"),
                    "cycle_end": item.get("before"),
                    "raw_json": json.dumps(item),
                },
            )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (403, 404):
            return
        raise
    store.commit()


def _collect_code_scans(client: DevinClient, store: Store, ep: Endpoints, since, until) -> None:
    """Code-scan metrics for the whole range; re-pulled every run."""
    path = ep.path("code_scan_metrics")
    if path is None:
        return
    start_ts, end_ts = int(since.timestamp()), int(until.timestamp())
    try:
        payload = client.get(path, {"time_after": start_ts, "time_before": end_ts})
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (403, 404):
            return
        raise
    store.execute(
        "DELETE FROM code_scan_metrics WHERE window_start=? AND window_end=?",
        (start_ts, end_ts),
    )
    store.execute(
        "INSERT INTO code_scan_metrics (window_start, window_end, fetched_at, payload_json) VALUES (?,?,?,?)",
        (start_ts, end_ts, utc_now_epoch(), json.dumps(payload)),
    )
    store.commit()


def _collect_audit_logs(
    client: DevinClient, store: Store, ep: Endpoints, since: datetime, until: datetime, done
) -> None:
    path = ep.path("audit_logs")
    if path is None:
        return
    start_ts, end_ts = int(since.timestamp()), int(until.timestamp())
    if done(start_ts, end_ts, "audit_logs"):
        return
    try:
        for item in client.paginate(path, {"time_after": start_ts, "time_before": end_ts}):
            store.upsert(
                "audit_logs",
                {
                    "event_id": item.get("audit_log_id"),
                    "occurred_at": item.get("created_at"),
                    "event_type": item.get("action"),
                    # never store user_email in the actor column
                    "actor": item.get("user_id") or item.get("service_user_id"),
                    "raw_json": json.dumps(item),
                },
            )
        store.mark_run(start_ts, end_ts, "audit_logs", "done", utc_now_epoch())
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (403, 404):
            log.info("audit-logs unavailable (%s); skipped", exc.response.status_code)
            store.mark_run(start_ts, end_ts, "audit_logs", "skipped", utc_now_epoch())
        else:
            raise
    store.commit()
