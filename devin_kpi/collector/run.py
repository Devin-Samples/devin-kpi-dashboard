"""Collector: idempotent, resumable pull of all Devin API endpoints into
the local SQLite store.

Sessions are collected in daily windows (collector_runs tracks
window+endpoint -> status='done' for resume). Metrics snapshots are stored
per window; consumption/daily uses Pacific-day boundaries; cycles,
code-scan metrics and audit logs cover the whole range.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta

import httpx

from devin_kpi.api.client import DevinClient, Endpoints, Scope
from devin_kpi.config import Settings
from devin_kpi.enrichment.pr_urls import parse_pr_url
from devin_kpi.store import Store
from devin_kpi.timeutil import day_windows, utc_now_epoch

log = logging.getLogger(__name__)

DAILY_METRIC_ENDPOINTS = [
    "metrics_usage",
    "metrics_sessions",
    "metrics_prs",
    "metrics_by_category",
    "metrics_dau",
    "metrics_active_users",
]


def collect(
    settings: Settings,
    since: datetime,
    until: datetime,
    store: Store,
    client: DevinClient | None = None,
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

        for start, end in day_windows(since, until, tz):
            _collect_sessions_window(client, store, ep, start, end, settings)
            for name in DAILY_METRIC_ENDPOINTS:
                _collect_metric_window(client, store, ep, name, scope, start, end)

        # Weekly / monthly active windows.
        _collect_periodic_actives(client, store, ep, scope, since, until, tz)

        _collect_consumption(client, store, ep, scope, since, until, tz)
        _collect_cycles(client, store, ep)
        _collect_code_scans(client, store, ep, since, until)
        _collect_audit_logs(client, store, ep, since, until)

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
) -> None:
    issue_re = re.compile(settings.ISSUE_KEY_REGEX)

    for name, path in (("sessions", ep.path("sessions")), ("insights", ep.path("insights"))):
        if path is None or store.run_done(start, end, name):
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
) -> None:
    if store.run_done(start, end, name):
        return
    path = ep.path(name)
    if path is None:
        store.mark_run(start, end, name, "skipped", utc_now_epoch())
        return
    params = {"start_time": start, "end_time": end}
    try:
        payload = client.get(path, params)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (403, 404):
            log.info("skipping %s: %s", name, exc.response.status_code)
            store.mark_run(start, end, name, "skipped", utc_now_epoch())
            return
        raise
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


def _collect_periodic_actives(
    client: DevinClient,
    store: Store,
    ep: Endpoints,
    scope: Scope,
    since: datetime,
    until: datetime,
    tz: str,
) -> None:
    """WAU per ISO week and MAU per calendar month."""
    for name, spans in (
        ("metrics_wau", _iso_week_spans(since, until, tz)),
        ("metrics_mau", _month_spans(since, until, tz)),
    ):
        if ep.path(name) is None:
            continue
        for start, end in spans:
            _collect_metric_window(client, store, ep, name, scope, start, end)


def _iso_week_spans(since: datetime, until: datetime, tz: str) -> list[tuple[int, int]]:
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(tz)
    d = since.astimezone(zone).date()
    d -= timedelta(days=d.weekday())  # Monday
    end_d = until.astimezone(zone).date()
    spans = []
    while d <= end_d:
        from devin_kpi.timeutil import pacific_day_start

        spans.append((pacific_day_start(d, tz), pacific_day_start(d + timedelta(days=7), tz)))
        d += timedelta(days=7)
    return spans


def _month_spans(since: datetime, until: datetime, tz: str) -> list[tuple[int, int]]:
    from zoneinfo import ZoneInfo

    from devin_kpi.timeutil import pacific_day_start

    zone = ZoneInfo(tz)
    d = since.astimezone(zone).date().replace(day=1)
    end_d = until.astimezone(zone).date()
    spans = []
    while d <= end_d:
        if d.month == 12:
            nxt = d.replace(year=d.year + 1, month=1)
        else:
            nxt = d.replace(month=d.month + 1)
        spans.append((pacific_day_start(d, tz), pacific_day_start(nxt, tz)))
        d = nxt
    return spans


# ------------------------------------------------------------- consumption


def _collect_consumption(
    client: DevinClient,
    store: Store,
    ep: Endpoints,
    scope: Scope,
    since: datetime,
    until: datetime,
    tz: str,
) -> None:
    path = ep.path("consumption_daily")
    if path is None:
        return
    if store.run_done(int(since.timestamp()), int(until.timestamp()), "consumption_daily"):
        return
    payload = client.get(
        path, {"start_time": int(since.timestamp()), "end_time": int(until.timestamp())}
    )
    scope_id = client.org_id if scope == "organization" else "enterprise"
    from zoneinfo import ZoneInfo

    zone = ZoneInfo(tz)
    rows = []
    for day in payload.get("consumption_by_date", []):
        ts = day.get("date") or day.get("start_time")
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
            acus = float(by_product.get(product, 0.0))
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
    store.mark_run(
        int(since.timestamp()), int(until.timestamp()), "consumption_daily", "done", utc_now_epoch()
    )
    store.commit()


def _collect_cycles(client: DevinClient, store: Store, ep: Endpoints) -> None:
    path = ep.path("consumption_cycles")
    if path is None or store.count("billing_cycles") > 0:
        return
    try:
        payload = client.get(path)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (403, 404):
            return
        raise
    cycles = payload.get("cycles", payload if isinstance(payload, list) else [])
    for c in cycles:
        store.upsert(
            "billing_cycles",
            {
                "cycle_start": c.get("cycle_start") or c.get("start_time"),
                "cycle_end": c.get("cycle_end") or c.get("end_time"),
                "raw_json": json.dumps(c),
            },
        )
    store.commit()


def _collect_code_scans(client: DevinClient, store: Store, ep: Endpoints, since, until) -> None:
    path = ep.path("code_scan_metrics")
    if path is None:
        return
    if store.count("code_scan_metrics") > 0:
        return
    try:
        payload = client.get(
            path, {"start_time": int(since.timestamp()), "end_time": int(until.timestamp())}
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (403, 404):
            return
        raise
    store.execute(
        "INSERT INTO code_scan_metrics (window_start, window_end, fetched_at, payload_json) VALUES (?,?,?,?)",
        (int(since.timestamp()), int(until.timestamp()), utc_now_epoch(), json.dumps(payload)),
    )
    store.commit()


def _collect_audit_logs(
    client: DevinClient, store: Store, ep: Endpoints, since: datetime, until: datetime
) -> None:
    path = ep.path("audit_logs")
    if path is None:
        return
    if store.run_done(int(since.timestamp()), int(until.timestamp()), "audit_logs"):
        return
    try:
        for item in client.paginate(
            path, {"start_time": int(since.timestamp()), "end_time": int(until.timestamp())}
        ):
            store.upsert(
                "audit_logs",
                {
                    "event_id": item.get("event_id") or item.get("id"),
                    "occurred_at": item.get("occurred_at") or item.get("created_at"),
                    "event_type": item.get("event_type") or item.get("type"),
                    "actor": item.get("actor"),
                    "raw_json": json.dumps(item),
                },
            )
        store.mark_run(
            int(since.timestamp()), int(until.timestamp()), "audit_logs", "done", utc_now_epoch()
        )
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (403, 404):
            log.info("audit-logs unavailable (%s); skipped", exc.response.status_code)
            store.mark_run(
                int(since.timestamp()),
                int(until.timestamp()),
                "audit_logs",
                "skipped",
                utc_now_epoch(),
            )
        else:
            raise
    store.commit()
