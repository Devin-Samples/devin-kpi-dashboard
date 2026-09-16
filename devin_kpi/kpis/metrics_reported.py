"""API-reported counterpart numbers read from metrics_snapshots.

These are the counts the Devin API itself reports (metrics/usage,
metrics/sessions, metrics/prs, sessions-by-category, dau/wau/mau,
active-users) — used to cross-check KPIs computed from the fact tables.
Date range only; API snapshots do not support org/user/category filters
at read time.
"""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from devin_kpi.store import Store

# Payload fields that are nested dicts summed key-by-key.
NESTED_MAPS = {
    "sessions_created_by_size": "by_size",
    "sessions_with_merged_prs_by_size": "by_size_merged",
    "sessions_created_by_origin": "by_origin",
}

ACTIVE_ENDPOINTS = ("metrics_dau", "metrics_wau", "metrics_mau", "metrics_active_users")


def reported_metrics(store: Store, start: datetime, end: datetime) -> dict[str, dict]:
    """Aggregate metrics_snapshots whose window overlaps [start, end).

    Per-day count endpoints are summed across windows. dau/wau/mau
    payloads are arrays of {start_time,end_time,active_users} stored as a
    single whole-range snapshot -> returned under "series". active-users
    is a single object -> {"count": n}.
    """
    df = store.read_df(
        "metrics_snapshots",
        "window_start < ? AND window_end > ?",
        (int(end.timestamp()), int(start.timestamp())),
    )
    out: dict[str, dict] = {}
    for endpoint, grp in df.groupby("endpoint"):
        if endpoint in ACTIVE_ENDPOINTS:
            series: list[dict] = []
            for raw in grp.payload_json:
                payload = json.loads(raw)
                if isinstance(payload, list):
                    series.extend(payload)
                elif isinstance(payload, dict):
                    series.append(payload)
            series.sort(key=lambda r: r.get("start_time", 0))
            entry: dict = {"series": series}
            if series:
                entry["totals"] = {"active_users": max(r.get("active_users", 0) for r in series)}
            out[endpoint] = entry
            continue
        totals: dict[str, float] = {}
        nested: dict[str, dict[str, float]] = {}
        categories: list[dict] = []
        for raw in grp.payload_json:
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                continue
            for k, v in payload.items():
                if isinstance(v, int | float):
                    totals[k] = totals.get(k, 0.0) + float(v)
                elif k in NESTED_MAPS and isinstance(v, dict):
                    bucket = nested.setdefault(NESTED_MAPS[k], {})
                    for sk, sv in v.items():
                        if isinstance(sv, int | float):
                            bucket[sk] = bucket.get(sk, 0.0) + float(sv)
                elif k == "categories" and isinstance(v, list):
                    categories = _merge_categories(categories, v)
        entry = {"totals": totals}
        entry.update(nested)
        if categories:
            for c in categories:
                c["subcategories"] = list(c["subcategories"].values())
            entry["categories"] = categories
        out[endpoint] = entry
    return out


def _merge_categories(acc: list[dict], new: list[dict]) -> list[dict]:
    idx = {c["category"]: c for c in acc}
    for cat in new:
        name = cat.get("category")
        tgt = idx.get(name)
        if tgt is None:
            tgt = {"category": name, "sessions_count": 0.0, "acus": 0.0, "subcategories": {}}
            idx[name] = tgt
            acc.append(tgt)
        tgt["sessions_count"] += cat.get("sessions_count", 0) or 0
        tgt["acus"] += cat.get("acus", 0) or 0
        for sub in cat.get("subcategories") or []:
            sid = sub.get("subcategory_id")
            st = tgt["subcategories"].setdefault(
                sid,
                {
                    "subcategory_id": sid,
                    "display_name": sub.get("display_name"),
                    "sessions_count": 0.0,
                    "acus": 0.0,
                },
            )
            st["sessions_count"] += sub.get("sessions_count", 0) or 0
            st["acus"] += sub.get("acus", 0) or 0
    # subcategories stays a dict keyed by id during accumulation; the
    # caller converts to a list once merging is done
    return acc


def active_users_series(
    store: Store, endpoint: str, start: datetime, end: datetime
) -> pd.DataFrame:
    """DataFrame(start_time, end_time, active_users) for dau/wau/mau."""
    rep = reported_metrics(store, start, end)
    series = rep.get(endpoint, {}).get("series", [])
    return pd.DataFrame(series, columns=["start_time", "end_time", "active_users"])


def consumption_by_product(store: Store, start: datetime, end: datetime) -> pd.DataFrame:
    """Daily consumption rows for charting: date x product acus."""
    df = store.read_df(
        "consumption_daily",
        "date >= ? AND date < ?",
        (start.date().isoformat(), end.date().isoformat()),
    )
    return df


def code_scan_metrics(store: Store) -> dict | None:
    df = store.read_df("code_scan_metrics")
    if df.empty:
        return None
    return json.loads(df.sort_values("fetched_at").iloc[-1].payload_json)
