"""Plain-English executive summary built from computed KPI values.

Pure functions (no Streamlit) so the wording can be unit-tested. Every
sentence only mentions numbers that are actually available; nothing is
invented when an input is missing.
"""

from __future__ import annotations

from devin_kpi.kpis.formulas import KpiValue


def _val(kvs: dict[str, KpiValue], key: str) -> float | None:
    kv = kvs.get(key)
    return kv.value if kv and kv.available else None


def _n(v: float) -> str:
    return f"{round(v):,}"


def _pct(v: float) -> str:
    return f"{v:.0%}"


def _usd(v: float) -> str:
    return f"${v:,.0f}" if abs(v) >= 1000 else f"${v:,.2f}"


def _trend(cur: float | None, prev: float | None, lower_is_better: bool = False) -> str:
    """' (up 12% vs prior period)' style suffix, or '' when not comparable."""
    if cur is None or prev is None or prev == 0:
        return ""
    change = (cur - prev) / prev
    if abs(change) < 0.005:
        return " (flat vs prior period)"
    direction = "up" if change > 0 else "down"
    return f" ({direction} {abs(change):.0%} vs prior period)"


def executive_summary(
    kvs: dict[str, KpiValue], prev: dict[str, KpiValue] | None = None
) -> list[str]:
    """Return 2-4 markdown sentences covering delivery, cost, adoption and
    risk. Sentences whose inputs are unavailable are omitted."""
    prev = prev or {}
    lines: list[str] = []

    merged = _val(kvs, "prs_merged")
    completed = _val(kvs, "sessions_completed")
    merge_rate = _val(kvs, "merge_rate")
    if merged is not None and completed is not None:
        s = f"Devin merged **{_n(merged)} pull requests** from {_n(completed)} completed sessions"
        s += _trend(merged, _val(prev, "prs_merged"))
        if merge_rate is not None:
            s += f"; {_pct(merge_rate)} of the PRs it opened were merged"
        lines.append(s + ".")

    total_cost = _val(kvs, "total_cost")
    total_acus = _val(kvs, "total_acus")
    cpm = _val(kvs, "cost_per_merged_pr")
    apm = _val(kvs, "acus_per_merged_pr")
    if total_cost is not None:
        s = f"Total spend was **{_usd(total_cost)}** ({_n(total_acus or 0)} ACUs)"
        s += _trend(total_cost, _val(prev, "total_cost"))
        if cpm is not None:
            s += f" — **{_usd(cpm)} per merged PR**"
            s += _trend(cpm, _val(prev, "cost_per_merged_pr"))
        lines.append(s + ".")
    elif total_acus is not None:
        s = f"Devin consumed **{_n(total_acus)} ACUs**"
        s += _trend(total_acus, _val(prev, "total_acus"))
        if apm is not None:
            s += f" — {apm:,.1f} ACUs per merged PR"
        lines.append(s + ".")

    mau = _val(kvs, "mau")
    pb = _val(kvs, "playbook_automation_share")
    if mau is not None:
        s = f"**{_n(mau)} engineers** used Devin in the last 30 days"
        s += _trend(mau, _val(prev, "mau"))
        if pb is not None:
            s += f"; {_pct(pb)} of sessions ran through playbooks or automations"
        lines.append(s + ".")

    takeover = _val(kvs, "human_takeover_rate")
    limit = _val(kvs, "usage_limit_hit_rate")
    error = _val(kvs, "session_error_rate")
    risk: list[str] = []
    if takeover is not None:
        risk.append(f"{_pct(takeover)} of PRs needed a human takeover")
    if limit is not None and limit > 0:
        risk.append(f"{_pct(limit)} of sessions were stopped by usage limits")
    if error is not None and error > 0:
        risk.append(f"{_pct(error)} ended in error")
    if risk:
        lines.append("Watch items: " + "; ".join(risk) + ".")
    return lines
