"""Deterministic synthetic dataset for demo mode.

Generates ~4000 sessions over 180 days across 3 orgs and ~40 users, with
PR outcomes, enrichment fields, insights, issue links, consumption rows,
billing cycles, code-scan metrics and audit events — all written straight
into a Store with the same schema the collector uses. Seedable (default
42) so the demo dataset is reproducible.
"""

from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from devin_kpi.store import Store
from devin_kpi.timeutil import pacific_day_start

N_SESSIONS = 4000
N_USERS = 40
N_DAYS = 180

ORGS = [("org_synth_01", "org_alpha"), ("org_synth_02", "org_beta"), ("org_synth_03", "org_gamma")]
ORG_WEIGHTS = [0.5, 0.3, 0.2]
USERS = [f"user_synth_{i:03d}" for i in range(1, N_USERS + 1)]
# Service accounts (API keys / integrations). Sessions from code_scan and
# automation origins, and most api-origin sessions, are attributed to one.
SERVICE_USERS = [f"svc_synth_{i:02d}" for i in range(1, 5)]
SERVICE_ORIGINS = {"code_scan", "automation"}

SIZES = ["xs", "s", "m", "l", "xl"]
SIZE_WEIGHTS = [0.30, 0.30, 0.22, 0.12, 0.06]
SIZE_ACU_MEAN = {"xs": 0.5, "s": 1.5, "m": 4.0, "l": 10.0, "xl": 25.0}

CATEGORIES = {
    "feature_development": ["new_endpoint", "ui_change", "data_pipeline"],
    "bug_fixing": ["crash_fix", "regression", "test_failure"],
    "code_review": ["pr_review", "security_review"],
    "refactoring": ["cleanup", "migration", "dependency_upgrade"],
    "documentation": ["readme", "api_docs"],
}
CAT_WEIGHTS = [0.40, 0.25, 0.12, 0.15, 0.08]

# Real session origins vocabulary.
ORIGINS = [
    "webapp",
    "slack",
    "api",
    "automation",
    "code_scan",
    "desktop",
]
ORIGIN_WEIGHTS = [0.45, 0.15, 0.15, 0.12, 0.08, 0.05]

REPOS = [
    "example-org/payments-api",
    "example-org/web-frontend",
    "example-org/etl-jobs",
    "example-org/mobile-app",
    "example-org/infra-terraform",
    "example-org/auth-service",
    "example-org/notifications",
    "example-org/search-indexer",
    "example-org/data-warehouse",
    "example-org/cli-tools",
    "example-org/billing",
    "example-org/ml-pipeline",
]

ISSUE_TYPES = [
    "missing_tests",
    "unclear_requirements",
    "context_switch",
    "permission_error",
    "flaky_ci",
    "large_diff",
]

# Real session vocabulary: status is always running | suspended | exit.
STATUSES = ["running", "suspended", "exit"]
STATUS_WEIGHTS = [0.01, 0.95, 0.04]

# status_detail vocab per status (real API values).
STATUS_DETAILS = {
    "running": (["working", "waiting_for_user"], [0.6, 0.4]),
    "suspended": (
        ["inactivity", "user_request", "usage_limit_exceeded"],
        [0.80, 0.15, 0.05],
    ),
    "exit": (["user_request", "error"], [0.85, 0.15]),
}


AUDIT_ACTIONS = [
    "search_query",
    "permission_response",
    "add_member",
    "add_enterprise_member",
    "connect_repo",
    "assign_roles",
    "create_api_key",
    "create_playbook",
    "update_playbook",
    "create_automation",
    "update_automation",
]
AUDIT_WEIGHTS = [0.35, 0.25, 0.08, 0.04, 0.05, 0.04, 0.03, 0.06, 0.04, 0.03, 0.03]


def _pick(rng: random.Random, items, weights):
    return rng.choices(items, weights=weights, k=1)[0]


def generate(
    store: Store,
    seed: int = 42,
    n_sessions: int = N_SESSIONS,
    n_days: int = N_DAYS,
    now: datetime | None = None,
) -> dict:
    rng = random.Random(seed)
    now = now or datetime.now(tz=UTC)
    start = now - timedelta(days=n_days)

    users = list(USERS)
    user_org = {u: _pick(rng, [o[0] for o in ORGS], ORG_WEIGHTS) for u in users}

    sessions_rows, prs_rows, insights_rows, issues_rows = [], [], [], []
    # consumption bookkeeping: {(org_id, date_str): {product: acus}}
    consumption: dict[tuple[str, str], dict[str, float]] = {}
    merged_ids = set()

    day_weights = []
    for i in range(n_days):
        d = (start + timedelta(days=i)).date()
        weekday = 1.0 if d.weekday() < 5 else 0.25
        trend = 1.0 + 0.5 * (i / n_days)  # mild upward trend
        day_weights.append(weekday * trend)

    for i in range(n_sessions):
        day_idx = _pick(rng, list(range(n_days)), day_weights)
        created = int((start + timedelta(days=day_idx)).timestamp()) + rng.randint(0, 23 * 3600)
        sid = f"ses_synth_{i:05d}"
        user = rng.choice(users)
        org_id = user_org[user]
        size = _pick(rng, SIZES, SIZE_WEIGHTS)
        acus = max(0.05, rng.lognormvariate(math.log(SIZE_ACU_MEAN[size]), 0.55))
        cat = _pick(rng, list(CATEGORIES), CAT_WEIGHTS)
        subcat = rng.choice(CATEGORIES[cat])
        origin = _pick(rng, ORIGINS, ORIGIN_WEIGHTS)
        service_user = None
        if origin in SERVICE_ORIGINS or (origin == "api" and rng.random() < 0.7):
            service_user = rng.choice(SERVICE_USERS)
            user = service_user
        status = _pick(rng, STATUSES, STATUS_WEIGHTS)
        details, detail_weights = STATUS_DETAILS[status]
        status_detail = _pick(rng, details, detail_weights)
        duration_h = max(0.05, rng.lognormvariate(math.log(1.2), 0.9))
        updated = created + int(duration_h * 3600)

        has_issue_key = rng.random() < 0.30
        issue_key = f"SYN-{rng.randint(100, 9999)}" if has_issue_key else None
        title_bits = ["Fix", "Implement", "Refactor", "Review"]
        title = f"{rng.choice(title_bits)} {subcat.replace('_', ' ')}"
        if issue_key:
            title = f"[{issue_key}] {title}"

        playbook_id = f"pb_{rng.randint(1, 12)}" if rng.random() < 0.20 else None
        automation_id = f"auto_{rng.randint(1, 6)}" if rng.random() < 0.10 else None
        tags = rng.sample(["frontend", "backend", "infra", "urgent", "debt"], k=rng.randint(0, 2))
        repo = rng.choice(REPOS)

        sessions_rows.append(
            {
                "session_id": sid,
                "org_id": org_id,
                "user_id": user,
                "status": status,
                "title": title,
                "tags_json": json.dumps(tags),
                "created_at": created,
                "updated_at": updated,
                "acus_consumed": round(acus, 3),
                "origin": origin,
                "category": cat,
                "subcategory": subcat,
                "playbook_id": playbook_id,
                "automation_id": automation_id,
                "devin_mode": rng.choice(["normal", "lite"]),
                "is_archived": 0,
                "parent_session_id": None,
                "service_user_id": service_user,
                "status_detail": status_detail,
                "url": f"https://app.devin.ai/sessions/{sid}",
                "repo_names_json": json.dumps([repo]),
                "raw_json": None,
            }
        )

        # PRs: ~55% of sessions
        if rng.random() < 0.55:
            pr_n = 100 + i  # unique per session so PR URLs never collide
            url = f"https://github.com/{repo}/pull/{pr_n}"
            r = rng.random()
            state = "merged" if r < 0.60 else ("open" if r < 0.85 else "closed")
            enriched = rng.random() < 0.80
            if enriched:
                pr_created = created + rng.randint(300, 5 * 3600)
                merged_at = pr_created + rng.randint(3600, 4 * 86400) if state == "merged" else None
                closed_at = pr_created + rng.randint(3600, 4 * 86400) if state == "closed" else None
                rc = rng.randint(0, 15)
                rr = rng.randint(0, 4)
                add = int(max(1, rng.lognormvariate(math.log(120), 1.0)))
                dele = int(add * rng.random() * 0.6)
                enr_at = pr_created + rng.randint(0, 86400)
            else:
                pr_created = merged_at = closed_at = rc = rr = add = dele = enr_at = None
            prs_rows.append(
                {
                    "session_id": sid,
                    "pr_url": url,
                    "pr_state": state,
                    "provider": "github",
                    "repo_full_name": repo,
                    "pr_number": pr_n,
                    "pr_created_at": pr_created,
                    "merged_at": merged_at,
                    "closed_at": closed_at,
                    "review_comments": rc,
                    "review_rounds": rr,
                    "additions": add,
                    "deletions": dele,
                    "enriched_at": enr_at,
                }
            )
            if state == "merged":
                merged_ids.add(sid)

        # issue link
        if issue_key:
            points = rng.choice([1, 2, 3, 5, 8]) if rng.random() < 0.70 else None
            issues_rows.append(
                {
                    "session_id": sid,
                    "issue_key": issue_key,
                    "tracker": "jira" if points is not None else None,
                    "story_points": points,
                    "fetched_at": created,
                }
            )

        # insights: all sessions; analysis for ~40%
        analysis = None
        if rng.random() < 0.40:
            analysis = {
                "classification": {
                    "category": cat,
                    "confidence": round(rng.uniform(0.5, 0.99), 2),
                    "languages": rng.sample(["python", "typescript", "go"], k=1),
                },
                "issues": [
                    {
                        "id": f"iss_{rng.randint(1000, 9999)}",
                        "impact": rng.choice(["low", "medium", "high"]),
                        "issue": "synthetic issue",
                        "label": rng.choice(ISSUE_TYPES),
                        "title": rng.choice(ISSUE_TYPES).replace("_", " "),
                    }
                    for _ in range(rng.randint(1, 2))
                ],
                "action_items": [],
            }
        insights_rows.append(
            {
                "session_id": sid,
                "num_user_messages": max(0, int(rng.lognormvariate(math.log(2.2), 0.8))),
                "num_devin_messages": max(1, int(rng.lognormvariate(math.log(6), 0.9))),
                "session_size": size,
                "analysis_json": json.dumps(analysis) if analysis else None,
            }
        )

        # consumption split ~70/15/10/5 devin/cascade/terminal/review
        date_str = _pacific_date_str(created)
        bucket = consumption.setdefault(
            (org_id, date_str), {"devin": 0.0, "cascade": 0.0, "terminal": 0.0, "review": 0.0}
        )
        bucket["devin"] += acus * 0.70
        bucket["cascade"] += acus * 0.15
        bucket["terminal"] += acus * 0.10
        bucket["review"] += acus * 0.05

    store.upsert_many("sessions", sessions_rows)
    store.upsert_many("session_prs", prs_rows)
    store.upsert_many("session_insights", insights_rows)
    store.upsert_many("session_issues", issues_rows)

    # consumption_daily: per org + enterprise total per product
    cons_rows = []
    for (org_id, date_str), prods in consumption.items():
        for scope, scope_id in (("organization", org_id),):
            for product, acus in prods.items():
                cons_rows.append(
                    {
                        "scope": scope,
                        "scope_id": scope_id,
                        "date": date_str,
                        "product": product,
                        "acus": round(acus, 4),
                    }
                )
            cons_rows.append(
                {
                    "scope": scope,
                    "scope_id": scope_id,
                    "date": date_str,
                    "product": "total",
                    "acus": round(sum(prods.values()), 4),
                }
            )
    ent: dict[str, dict[str, float]] = {}
    for (org_id, date_str), prods in consumption.items():
        b = ent.setdefault(date_str, {"devin": 0.0, "cascade": 0.0, "terminal": 0.0, "review": 0.0})
        for k, v in prods.items():
            b[k] += v
    for date_str, prods in ent.items():
        for product, acus in prods.items():
            cons_rows.append(
                {
                    "scope": "enterprise",
                    "scope_id": "enterprise",
                    "date": date_str,
                    "product": product,
                    "acus": round(acus, 4),
                }
            )
        cons_rows.append(
            {
                "scope": "enterprise",
                "scope_id": "enterprise",
                "date": date_str,
                "product": "total",
                "acus": round(sum(prods.values()), 4),
            }
        )
    store.upsert_many("consumption_daily", cons_rows)

    _generate_snapshots(store, sessions_rows, prs_rows, rng, start, now)

    # billing cycles: monthly over the range
    cyc_start = (start - timedelta(days=start.day - 1)).date().replace(day=1)
    cyc_rows = []
    while True:
        nxt = (cyc_start.replace(day=28) + timedelta(days=5)).replace(day=1)
        cs = int(datetime.combine(cyc_start, datetime.min.time(), tzinfo=UTC).timestamp())
        ce = int(datetime.combine(nxt, datetime.min.time(), tzinfo=UTC).timestamp())
        if cs > int(now.timestamp()):
            break
        cyc_rows.append(
            {
                "cycle_start": cs,
                "cycle_end": ce,
                "raw_json": json.dumps({"cycle_start": cs, "cycle_end": ce}),
            }
        )
        cyc_start = nxt
    store.upsert_many("billing_cycles", cyc_rows)

    # code scan metrics
    store.execute(
        "INSERT INTO code_scan_metrics (window_start, window_end, fetched_at, payload_json) VALUES (?,?,?,?)",
        (
            int(start.timestamp()),
            int(now.timestamp()),
            int(now.timestamp()),
            json.dumps(
                {
                    "scans_count": 320,
                    "repos_scanned_count": 12,
                    "prs_created_count": 96,
                    "prs_open_count": 22,
                    "prs_merged_count": 61,
                    "prs_closed_count": 13,
                    "avg_pr_time_to_merge_seconds": 152000,
                    "avg_pr_open_duration_seconds": 71000,
                    "open_critical_findings_count": 3,
                    "open_high_findings_count": 14,
                    "open_medium_findings_count": 51,
                    "open_low_findings_count": 120,
                }
            ),
        ),
    )

    # audit logs: one login + create_session per human session plus a
    # weighted mix of the other action types seen in real logs.
    audit_rows = []
    for s in sessions_rows:
        if s["service_user_id"]:
            continue
        audit_rows.append((s["created_at"] - rng.randint(60, 1800), "login", s["user_id"]))
        audit_rows.append((s["created_at"], "create_session", s["user_id"]))
        for _ in range(rng.randint(0, 3)):
            audit_rows.append(
                (s["created_at"] + rng.randint(60, 7200), "send_message", s["user_id"])
            )
    for _ in range(n_sessions // 4):
        ts = int(start.timestamp()) + rng.randint(0, n_days * 86400)
        etype = _pick(rng, AUDIT_ACTIONS, AUDIT_WEIGHTS)
        audit_rows.append((ts, etype, rng.choice(users)))
    store.upsert_many(
        "audit_logs",
        [
            {
                "event_id": f"al_synth_{j:06d}",
                "occurred_at": ts,
                "event_type": etype,
                "actor": actor,
                "raw_json": json.dumps(
                    {
                        "audit_log_id": f"al_synth_{j:06d}",
                        "action": etype,
                        "created_at": ts,
                        "user_id": actor,
                    }
                ),
            }
            for j, (ts, etype, actor) in enumerate(sorted(audit_rows))
        ],
    )

    store.set_meta("demo", "true")
    store.set_meta("scope", "enterprise")
    store.set_meta("synth_seed", str(seed))
    store.commit()
    return {
        "sessions": len(sessions_rows),
        "prs": len(prs_rows),
        "merged_prs": len(merged_ids),
        "issues": len(issues_rows),
    }


def _pacific_date_str(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, tz=ZoneInfo("America/Los_Angeles")).date().isoformat()


def _generate_snapshots(store, sessions_rows, prs_rows, rng, start, now) -> None:
    """Write metrics_snapshots payloads matching the real API response
    shapes: per-day windows for the count metrics, and whole-range
    snapshots for dau/wau/mau/active-users."""
    zone = ZoneInfo("America/Los_Angeles")
    size_l = {k: k for k in ("xs", "s", "m", "l", "xl")}
    pr_by_sid = defaultdict(list)
    for pr in prs_rows:
        pr_by_sid[pr["session_id"]].append(pr)

    # per-day aggregates keyed by Pacific-day start epoch
    day_stats: dict[int, dict] = {}
    for s in sessions_rows:
        d = datetime.fromtimestamp(s["created_at"], tz=zone).date()
        ws = pacific_day_start(d)
        st = day_stats.setdefault(
            ws,
            {
                "n": 0,
                "acus": 0.0,
                "playbook": 0,
                "merged_sessions": 0,
                "users": set(),
                "sizes": defaultdict(int),
                "origins": defaultdict(int),
                "merged_by_size": defaultdict(int),
                "prs": 0,
                "prs_merged": 0,
                "prs_closed": 0,
                "cats": defaultdict(lambda: [0, 0.0, defaultdict(lambda: [0, 0.0])]),
            },
        )
        st["n"] += 1
        st["acus"] += s["acus_consumed"] or 0
        st["playbook"] += 1 if s["playbook_id"] else 0
        if not s["service_user_id"]:
            st["users"].add(s["user_id"])
        st["origins"][s["origin"]] += 1
        c = st["cats"][s["category"]]
        c[0] += 1
        c[1] += s["acus_consumed"] or 0
        sc = c[2][s["subcategory"]]
        sc[0] += 1
        sc[1] += s["acus_consumed"] or 0
        prs = pr_by_sid.get(s["session_id"], [])
        st["prs"] += len(prs)
        st["prs_merged"] += sum(1 for p in prs if p["pr_state"] == "merged")
        st["prs_closed"] += sum(1 for p in prs if p["pr_state"] == "closed")
        if any(p["pr_state"] == "merged" for p in prs):
            st["merged_sessions"] += 1

    size_by_sid = {}  # filled below from insights is unavailable; infer via ACU
    for s in sessions_rows:
        size_by_sid[s["session_id"]] = _size_for_acus(s["acus_consumed"])
    for s in sessions_rows:
        d = datetime.fromtimestamp(s["created_at"], tz=zone).date()
        st = day_stats[pacific_day_start(d)]
        st["sizes"][size_by_sid[s["session_id"]]] += 1
        if any(p["pr_state"] == "merged" for p in pr_by_sid.get(s["session_id"], [])):
            st["merged_by_size"][size_by_sid[s["session_id"]]] += 1

    now_ts = int(now.timestamp())
    origins_all = [
        "api",
        "automation",
        "code_scan",
        "desktop",
        "jira",
        "linear",
        "slack",
        "teams",
        "webapp",
    ]
    for ws, st in sorted(day_stats.items()):
        we = ws + 86400
        base = {
            "endpoint": None,
            "scope": "enterprise",
            "params_json": json.dumps({"time_after": ws, "time_before": we}),
            "window_start": ws,
            "window_end": we,
            "fetched_at": now_ts,
        }

        def snap(endpoint, payload, base=base):
            store.insert_snapshot(
                {**base, "endpoint": endpoint, "payload_json": json.dumps(payload)}
            )

        snap(
            "metrics_usage",
            {
                "sessions_count": st["n"],
                "searches_count": int(st["n"] * 0.3),
                "prs_created_count": st["prs"],
                "prs_merged_count": st["prs_merged"],
            },
        )
        snap(
            "metrics_sessions",
            {
                "sessions_created_count": st["n"],
                "sessions_created_by_size": {k: st["sizes"].get(k, 0) for k in size_l},
                "sessions_created_by_origin": {o: st["origins"].get(o, 0) for o in origins_all},
                "sessions_created_with_playbook_count": st["playbook"],
                "sessions_created_with_search_count": int(st["n"] * 0.1),
                "sessions_with_merged_prs_count": st["merged_sessions"],
                "sessions_with_merged_prs_by_size": {
                    k: st["merged_by_size"].get(k, 0) for k in size_l
                },
                "avg_acus_per_session": round(st["acus"] / st["n"], 4),
            },
        )
        taken = int(st["prs"] * 0.08)
        snap(
            "metrics_prs",
            {
                "prs_created_count": st["prs"],
                "prs_opened_count": st["prs"] - st["prs_merged"] - st["prs_closed"],
                "prs_merged_count": st["prs_merged"],
                "prs_closed_count": st["prs_closed"],
                "prs_taken_over_count": taken,
                "prs_taken_over_opened_count": int(taken * 0.3),
                "prs_taken_over_merged_count": int(taken * 0.5),
                "prs_taken_over_closed_count": taken - int(taken * 0.3) - int(taken * 0.5),
            },
        )
        snap(
            "metrics_by_category",
            {
                "categories": [
                    {
                        "category": cat,
                        "sessions_count": c[0],
                        "acus": round(c[1], 4),
                        "subcategories": [
                            {
                                "subcategory_id": sid,
                                "display_name": sid.replace("_", " "),
                                "sessions_count": sc[0],
                                "acus": round(sc[1], 4),
                            }
                            for sid, sc in c[2].items()
                        ],
                    }
                    for cat, c in st["cats"].items()
                ]
            },
        )

    # dau/wau/mau whole-range arrays
    start_ts, end_ts = int(start.timestamp()), now_ts
    dau = [
        {"start_time": ws, "end_time": ws + 86400, "active_users": len(st["users"])}
        for ws, st in sorted(day_stats.items())
    ]
    wau = []
    wk = sorted(day_stats)
    for i in range(0, len(wk), 7):
        chunk = wk[i : i + 7]
        users: set = set()
        for ws in chunk:
            users |= day_stats[ws]["users"]
        wau.append(
            {"start_time": chunk[0], "end_time": chunk[-1] + 86400, "active_users": len(users)}
        )
    mau = []
    by_month: dict[tuple, set] = {}
    for ws, st in day_stats.items():
        d = datetime.fromtimestamp(ws, tz=zone).date()
        by_month.setdefault((d.year, d.month), set()).update(st["users"])
    for (y, m), us in sorted(by_month.items()):
        ms = pacific_day_start(datetime(y, m, 1, tzinfo=zone).date())
        nxt = datetime(y + (m == 12), (m % 12) + 1, 1, tzinfo=zone).date()
        mau.append({"start_time": ms, "end_time": pacific_day_start(nxt), "active_users": len(us)})

    base = {
        "scope": "enterprise",
        "window_start": start_ts,
        "window_end": end_ts,
        "fetched_at": now_ts,
        "params_json": json.dumps({"time_after": start_ts, "time_before": end_ts}),
    }
    for endpoint, series in (("metrics_dau", dau), ("metrics_wau", wau), ("metrics_mau", mau)):
        store.insert_snapshot({**base, "endpoint": endpoint, "payload_json": json.dumps(series)})
    all_users = {s["user_id"] for s in sessions_rows}
    store.insert_snapshot(
        {
            **base,
            "endpoint": "metrics_active_users",
            "payload_json": json.dumps(
                {"start_time": start_ts, "end_time": end_ts, "active_users": len(all_users)}
            ),
        }
    )


def _size_for_acus(acus: float | None) -> str:
    a = acus or 0
    if a < 1.0:
        return "xs"
    if a < 3.0:
        return "s"
    if a < 7.0:
        return "m"
    if a < 17.0:
        return "l"
    return "xl"


def ensure_demo_db(settings) -> Store:
    """Open (or create+generate) the demo database."""
    path = Path(settings.DEMO_DATABASE_PATH)
    if not path.exists():
        store = Store(path)
        generate(store)
        return store
    return Store(path)
