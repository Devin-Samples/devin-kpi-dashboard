"""API-reported counterpart numbers read from metrics_snapshots.

These are the counts the Devin API itself reports (metrics/usage,
metrics/sessions, metrics/prs, dau/wau/mau) for a date range — used to
cross-check KPIs computed from the fact tables. Date range only; the API
snapshots do not support org/user/category filters at read time.
"""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd

from devin_kpi.store import Store


def reported_metrics(store: Store, start: datetime, end: datetime) -> dict[str, dict]:
    """Aggregate metrics_snapshots whose window overlaps [start, end).

    Returns {endpoint: aggregated payload fields summed over windows}.
    """
    df = store.read_df(
        "metrics_snapshots",
        "window_start < ? AND window_end > ?",
        (int(end.timestamp()), int(start.timestamp())),
    )
    out: dict[str, dict] = {}
    for endpoint, grp in df.groupby("endpoint"):
        totals: dict[str, float] = {}
        sizes: dict[str, float] = {}
        origins: dict[str, float] = {}
        for raw in grp.payload_json:
            payload = json.loads(raw)
            for k, v in payload.items():
                if isinstance(v, int | float):
                    totals[k] = totals.get(k, 0.0) + float(v)
                elif k == "sessions_created_by_size" and isinstance(v, dict):
                    for sk, sv in v.items():
                        sizes[sk] = sizes.get(sk, 0.0) + float(sv)
                elif k == "sessions_created_by_origin" and isinstance(v, dict):
                    for ok, ov in v.items():
                        origins[ok] = origins.get(ok, 0.0) + float(ov)
            if endpoint in ("metrics_dau", "metrics_wau", "metrics_mau", "metrics_active_users"):
                # point-in-time counts: take max, not sum
                pass
        entry: dict = {"totals": totals}
        if sizes:
            entry["by_size"] = sizes
        if origins:
            entry["by_origin"] = origins
        out[endpoint] = entry
    # active-user endpoints: report max window count rather than sum
    for endpoint in ("metrics_dau", "metrics_wau", "metrics_mau", "metrics_active_users"):
        if endpoint in out:
            sub = df[df.endpoint == endpoint]
            vals = []
            for raw in sub.payload_json:
                p = json.loads(raw)
                for key in ("count", "active_users", "users_count", "dau", "wau", "mau"):
                    if isinstance(p.get(key), int | float):
                        vals.append(float(p[key]))
            if vals:
                out[endpoint]["totals"] = {"count": max(vals)}
    return out


def consumption_by_product(store: Store, start: datetime, end: datetime) -> pd.DataFrame:
    """Daily consumption rows for charting: date x product acus."""
    df = store.read_df(
        "consumption_daily",
        "date >= ? AND date < ?",
        (start.date().isoformat(), end.date().isoformat()),
    )
    return df
