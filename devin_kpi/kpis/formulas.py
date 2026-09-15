"""KPI formulas: pure functions over pandas DataFrames. Every KPI returns a
KpiValue; KPIs whose inputs are unavailable return available=False with a
note, so the UI can degrade gracefully."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import pandas as pd

from devin_kpi.config import Settings
from devin_kpi.kpis.definitions import DEFINITIONS
from devin_kpi.kpis.filters import FilterSet, apply_filters, previous_period

# Adjustable: statuses treated as terminal for "sessions completed" and
# session-duration KPIs.
TERMINAL_STATUSES = ("finished", "stopped", "blocked", "expired", "completed")

MERGED_STATES = ("merged",)
CLOSED_STATES = ("closed", "closed_unmerged")

DAY = 86400


@dataclass
class KpiValue:
    key: str
    group: str
    label: str
    value: float | None
    unit: str
    numerator: float | None = None
    denominator: float | None = None
    available: bool = True
    depends_on: list[str] = field(default_factory=list)
    note: str | None = None


def _is_terminal(status: pd.Series) -> pd.Series:
    return status.fillna("").str.lower().apply(lambda s: any(t in s for t in TERMINAL_STATUSES))


def _median(series: pd.Series) -> float | None:
    s = series.dropna()
    return float(s.median()) if len(s) else None


def _p90(series: pd.Series) -> float | None:
    s = series.dropna()
    return float(s.quantile(0.9)) if len(s) else None


def _kv(
    key: str, value: float | None, unit: str, num=None, den=None, available=True, note=None
) -> KpiValue:
    d = DEFINITIONS[key]
    return KpiValue(
        key=key,
        group=d["group"],
        label=d["label"],
        value=value,
        unit=unit,
        numerator=num,
        denominator=den,
        available=available,
        depends_on=list(d["depends_on"]),
        note=note,
    )


def _unavailable(key: str, unit: str, note: str) -> KpiValue:
    return _kv(key, None, unit, available=False, note=note)


# ---------------------------------------------------------------- compute


def compute_all(
    sessions: pd.DataFrame,
    prs: pd.DataFrame,
    insights: pd.DataFrame,
    issues: pd.DataFrame,
    consumption: pd.DataFrame,
    f: FilterSet,
    settings: Settings,
    reported: dict | None = None,
) -> list[KpiValue]:
    s, p = apply_filters(sessions, prs, f)
    ins = insights[insights.session_id.isin(s.session_id)] if not insights.empty else insights
    iss = issues[issues.session_id.isin(s.session_id)] if not issues.empty else issues
    out: list[KpiValue] = []

    n_sessions = len(s)
    terminal = s[_is_terminal(s.status)] if n_sessions else s

    # ---- Throughput
    out.append(
        _kv(
            "sessions_completed",
            float(len(terminal)),
            "sessions",
            num=len(terminal),
            den=n_sessions,
        )
    )

    n_prs = len(p)
    merged = p[p.pr_state.str.lower().isin(MERGED_STATES)] if n_prs else p
    closed_unm = p[p.pr_state.str.lower().isin(CLOSED_STATES)] if n_prs else p
    n_merged, n_closed = len(merged), len(closed_unm)
    out.append(_kv("prs_created", float(n_prs), "prs", num=n_prs))
    out.append(_kv("prs_merged", float(n_merged), "prs", num=n_merged, den=n_prs))
    out.append(_kv("prs_closed_unmerged", float(n_closed), "prs", num=n_closed, den=n_prs))
    out.append(
        _kv(
            "merge_rate",
            n_merged / n_prs if n_prs else None,
            "ratio",
            num=n_merged,
            den=n_prs,
            available=bool(n_prs),
            note=None if n_prs else "no PRs in period",
        )
    )
    n_shipped = s.session_id.isin(merged.session_id).sum() if n_sessions else 0
    out.append(
        _kv(
            "sessions_shipped_rate",
            n_shipped / n_sessions if n_sessions else None,
            "ratio",
            num=int(n_shipped),
            den=n_sessions,
            available=bool(n_sessions),
            note=None if n_sessions else "no sessions in period",
        )
    )
    prs_rep = (reported or {}).get("metrics_prs", {}).get("totals", {})
    taken_over = prs_rep.get("prs_taken_over_count")
    rep_created = prs_rep.get("prs_created_count")
    if taken_over is not None and rep_created:
        out.append(
            _kv(
                "human_takeover_rate",
                taken_over / rep_created,
                "ratio",
                num=taken_over,
                den=rep_created,
                note="API-reported (metrics/prs); ignores non-date filters",
            )
        )
    else:
        out.append(
            _unavailable(
                "human_takeover_rate",
                "ratio",
                "requires a metrics/prs API snapshot covering this range",
            )
        )

    # ---- Cycle time
    duration = (s.updated_at - s.created_at) / 3600.0
    duration = duration.where(_is_terminal(s.status))
    out.append(_kv("session_duration_median", _median(duration), "hours"))
    out.append(_kv("session_duration_p90", _p90(duration), "hours"))

    git_ok = n_prs and p.enriched_at.notna().any()
    if git_ok:
        m = merged.merge(
            s[["session_id", "created_at"]].rename(columns={"created_at": "sess_created"}),
            on="session_id",
        )
        req_to_merge = (m.merged_at - m.sess_created) / 3600.0
        open_to_merge = (m.merged_at - m.pr_created_at) / 3600.0
        out.append(_kv("request_to_merge_median", _median(req_to_merge), "hours"))
        out.append(_kv("request_to_merge_p90", _p90(req_to_merge), "hours"))
        out.append(_kv("pr_open_to_merge_median", _median(open_to_merge), "hours"))
        out.append(_kv("pr_open_to_merge_p90", _p90(open_to_merge), "hours"))
    else:
        note = "requires git enrichment (GITHUB_TOKEN / GITLAB_TOKEN / AZURE_DEVOPS_PAT)"
        for k in (
            "request_to_merge_median",
            "request_to_merge_p90",
            "pr_open_to_merge_median",
            "pr_open_to_merge_p90",
        ):
            out.append(_unavailable(k, "hours", note))

    # ---- Cost
    acus = s.acus_consumed.dropna() if n_sessions else s.acus_consumed
    acus_mean = float(acus.mean()) if len(acus) else None
    acus_med = _median(acus)
    total_acus = float(acus.sum()) if len(acus) else 0.0
    out.append(_kv("acus_per_session_mean", acus_mean, "acu", num=total_acus, den=n_sessions))
    out.append(_kv("acus_per_session_median", acus_med, "acu"))
    out.append(_kv("total_acus", total_acus, "acu"))
    acus_per_merged = total_acus / n_merged if n_merged else None
    out.append(
        _kv(
            "acus_per_merged_pr",
            acus_per_merged,
            "acu",
            num=total_acus,
            den=n_merged,
            available=bool(n_merged),
            note=None if n_merged else "no merged PRs",
        )
    )

    if settings.effective_acu_unit_price is not None:
        price = settings.effective_acu_unit_price
        out.append(
            _kv(
                "cost_per_merged_pr",
                acus_per_merged * price if acus_per_merged is not None else None,
                "usd",
                available=acus_per_merged is not None,
            )
        )
        out.append(
            _kv(
                "cost_per_session",
                acus_mean * price if acus_mean is not None else None,
                "usd",
                available=acus_mean is not None,
            )
        )
    else:
        note = "requires ACU_UNIT_PRICE configuration"
        out.append(_unavailable("cost_per_merged_pr", "usd", note))
        out.append(_unavailable("cost_per_session", "usd", note))

    pointed = iss[iss.story_points.notna()] if not iss.empty else iss
    if len(pointed):
        pts = float(pointed.story_points.sum())
        acus_linked = float(s[s.session_id.isin(pointed.session_id)].acus_consumed.fillna(0).sum())
        acus_per_pt = acus_linked / pts if pts else None
        out.append(_kv("acus_per_story_point", acus_per_pt, "acu", num=acus_linked, den=pts))
        if settings.effective_acu_unit_price is not None:
            out.append(
                _kv(
                    "cost_per_story_point",
                    acus_per_pt * settings.effective_acu_unit_price
                    if acus_per_pt is not None
                    else None,
                    "usd",
                    num=acus_linked,
                    den=pts,
                )
            )
        else:
            out.append(
                _unavailable("cost_per_story_point", "usd", "requires ACU_UNIT_PRICE configuration")
            )
    else:
        note = "requires tracker enrichment (Jira/Linear) with story points"
        out.append(_unavailable("acus_per_story_point", "acu", note))
        out.append(_unavailable("cost_per_story_point", "usd", note))

    # ---- Adoption
    if n_sessions:
        end_ts = int(f.end.timestamp())
        dau = s[s.created_at >= end_ts - DAY].user_id.nunique()
        wau = s[s.created_at >= end_ts - 7 * DAY].user_id.nunique()
        mau = s[s.created_at >= end_ts - 30 * DAY].user_id.nunique()
        active = s.user_id.nunique()
        pb = int((s.playbook_id.notna() | s.automation_id.notna()).sum())
    else:
        dau = wau = mau = active = pb = 0
    out.append(_kv("dau", float(dau), "users"))
    out.append(_kv("wau", float(wau), "users"))
    out.append(_kv("mau", float(mau), "users"))
    out.append(
        _kv(
            "stickiness",
            dau / mau if mau else None,
            "ratio",
            num=dau,
            den=mau,
            available=bool(mau),
            note=None if mau else "no monthly active users",
        )
    )
    if settings.SEAT_COUNT:
        out.append(
            _kv(
                "active_vs_licensed",
                active / settings.SEAT_COUNT,
                "ratio",
                num=active,
                den=settings.SEAT_COUNT,
            )
        )
    else:
        out.append(_unavailable("active_vs_licensed", "ratio", "requires SEAT_COUNT configuration"))
    out.append(
        _kv(
            "playbook_automation_share",
            pb / n_sessions if n_sessions else None,
            "ratio",
            num=pb,
            den=n_sessions,
            available=bool(n_sessions),
        )
    )

    # ---- Quality & efficiency
    sized = ins[ins.session_size.notna()] if not ins.empty else ins
    n_sized = len(sized)
    n_large = int(sized.session_size.isin(["L", "XL"]).sum()) if n_sized else 0
    out.append(
        _kv(
            "large_session_share",
            n_large / n_sized if n_sized else None,
            "ratio",
            num=n_large,
            den=n_sized,
            available=bool(n_sized),
            note=None if n_sized else "no session size data",
        )
    )
    um = (
        ins.num_user_messages.dropna()
        if not ins.empty
        else ins.get("num_user_messages", pd.Series(dtype=float))
    )
    out.append(
        _kv(
            "user_messages_per_session",
            float(um.mean()) if len(um) else None,
            "messages",
            available=bool(len(um)),
        )
    )
    out.append(
        _kv(
            "closed_without_merge_rate",
            n_closed / n_prs if n_prs else None,
            "ratio",
            num=n_closed,
            den=n_prs,
            available=bool(n_prs),
        )
    )
    if git_ok:
        rc = merged.review_comments.dropna()
        rr = merged.review_rounds.dropna()
        out.append(
            _kv(
                "review_comments_per_merged_pr",
                float(rc.mean()) if len(rc) else None,
                "comments",
                available=bool(len(rc)),
            )
        )
        out.append(
            _kv(
                "review_rounds_per_merged_pr",
                float(rr.mean()) if len(rr) else None,
                "rounds",
                available=bool(len(rr)),
            )
        )
    else:
        note = "requires git enrichment"
        out.append(_unavailable("review_comments_per_merged_pr", "comments", note))
        out.append(_unavailable("review_rounds_per_merged_pr", "rounds", note))

    return out


# ------------------------------------------------------------- kpi_table


def kpi_table(current: list[KpiValue], previous: list[KpiValue]) -> pd.DataFrame:
    """Comparison table: value, previous, delta, delta_pct plus definition
    metadata."""
    prev = {k.key: k for k in previous}
    rows = []
    for k in current:
        p = prev.get(k.key)
        delta = pct = None
        if k.value is not None and p and p.value is not None:
            delta = k.value - p.value
            pct = delta / p.value if p.value else None
        rows.append(
            {
                "key": k.key,
                "group": k.group,
                "label": k.label,
                "value": k.value,
                "previous": p.value if p else None,
                "delta": delta,
                "delta_pct": pct,
                "unit": k.unit,
                "available": k.available,
                "depends_on": ",".join(k.depends_on),
                "formula": DEFINITIONS[k.key]["formula"],
                "note": k.note,
            }
        )
    return pd.DataFrame(rows)


def current_and_previous(
    sessions: pd.DataFrame,
    prs: pd.DataFrame,
    insights: pd.DataFrame,
    issues: pd.DataFrame,
    consumption: pd.DataFrame,
    f: FilterSet,
    settings: Settings,
    reported: dict | None = None,
) -> pd.DataFrame:
    cur = compute_all(sessions, prs, insights, issues, consumption, f, settings, reported=reported)
    prev = compute_all(
        sessions,
        prs,
        insights,
        issues,
        consumption,
        previous_period(f),
        settings,
        reported=reported,
    )
    return kpi_table(cur, prev)


def analysis_issue_counts(insights: pd.DataFrame) -> pd.Series:
    """Frequency of analysis.issues types across sessions (insights)."""
    counts: dict[str, int] = {}
    for raw in insights.analysis_json.dropna():
        try:
            analysis = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            continue
        for issue in (analysis or {}).get("issues") or []:
            if isinstance(issue, dict):
                t = issue.get("label") or issue.get("title") or issue.get("type") or "unknown"
            else:
                t = str(issue)
            counts[t] = counts.get(t, 0) + 1
    return pd.Series(counts).sort_values(ascending=False)
