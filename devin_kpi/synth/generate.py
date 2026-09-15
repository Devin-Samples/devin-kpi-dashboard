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
from datetime import UTC, datetime, timedelta
from pathlib import Path

from devin_kpi.store import Store

N_SESSIONS = 4000
N_USERS = 40
N_DAYS = 180

ORGS = [("org_synth_01", "org_alpha"), ("org_synth_02", "org_beta"), ("org_synth_03", "org_gamma")]
ORG_WEIGHTS = [0.5, 0.3, 0.2]
USERS = [f"user_synth_{i:03d}" for i in range(1, N_USERS + 1)]

SIZES = ["XS", "S", "M", "L", "XL"]
SIZE_WEIGHTS = [0.30, 0.30, 0.22, 0.12, 0.06]
SIZE_ACU_MEAN = {"XS": 0.5, "S": 1.5, "M": 4.0, "L": 10.0, "XL": 25.0}

CATEGORIES = {
    "feature_development": ["new_endpoint", "ui_change", "data_pipeline"],
    "bug_fixing": ["crash_fix", "regression", "test_failure"],
    "code_review": ["pr_review", "security_review"],
    "refactoring": ["cleanup", "migration", "dependency_upgrade"],
    "documentation": ["readme", "api_docs"],
}
CAT_WEIGHTS = [0.40, 0.25, 0.12, 0.15, 0.08]

ORIGINS = [
    "webapp",
    "slack",
    "api",
    "jira",
    "linear",
    "automation",
    "teams",
    "desktop",
    "code_scan",
]
ORIGIN_WEIGHTS = [0.45, 0.15, 0.10, 0.08, 0.05, 0.10, 0.03, 0.02, 0.02]

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

TERMINAL = ["finished", "stopped", "blocked", "expired"]
NON_TERMINAL = ["running", "working", "queued", "suspended"]


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
        terminal = rng.random() < 0.75
        status = rng.choice(TERMINAL if terminal else NON_TERMINAL)
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
                "devin_mode": rng.choice(["interactive", "batch"]),
                "repo_names_json": json.dumps([repo]),
                "raw_json": None,
            }
        )

        # PRs: ~55% of sessions
        if rng.random() < 0.55:
            pr_n = rng.randint(100, 9999)
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
                "issues": [{"type": rng.choice(ISSUE_TYPES)} for _ in range(rng.randint(1, 2))],
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
                    "prs_from_scans_count": 96,
                    "avg_pr_time_to_merge_seconds": 152000,
                    "open_findings": {"critical": 3, "high": 14, "medium": 51, "low": 120},
                }
            ),
        ),
    )

    # audit logs
    audit_rows = []
    for j in range(60):
        ts = int(start.timestamp()) + rng.randint(0, n_days * 86400)
        etype = rng.choice(
            ["user_added", "repo_connected", "org_created", "role_changed", "api_key_created"]
        )
        audit_rows.append(
            {
                "event_id": f"evt_synth_{j:04d}",
                "occurred_at": ts,
                "event_type": etype,
                "actor": rng.choice(users),
                "raw_json": json.dumps({"event_id": f"evt_synth_{j:04d}", "type": etype}),
            }
        )
    store.upsert_many("audit_logs", audit_rows)

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
    from zoneinfo import ZoneInfo

    return datetime.fromtimestamp(epoch, tz=ZoneInfo("America/Los_Angeles")).date().isoformat()


def ensure_demo_db(settings) -> Store:
    """Open (or create+generate) the demo database."""
    path = Path(settings.DEMO_DATABASE_PATH)
    if not path.exists():
        store = Store(path)
        generate(store)
        return store
    return Store(path)
