"""Filter set applied to fact-table DataFrames before KPI computation."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pandas as pd


@dataclass
class FilterSet:
    start: datetime
    end: datetime
    org_ids: list[str] = field(default_factory=list)
    user_ids: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    origins: list[str] = field(default_factory=list)
    repos: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)


def _contains_any(json_col: pd.Series, values: list[str]) -> pd.Series:
    wanted = set(values)
    return json_col.fillna("[]").apply(
        lambda s: bool(wanted & set(json.loads(s) if isinstance(s, str) else (s or [])))
    )


def apply_filters(
    sessions: pd.DataFrame, prs: pd.DataFrame, f: FilterSet
) -> tuple[pd.DataFrame, pd.DataFrame]:
    s = sessions
    if not s.empty:
        mask = (s.created_at >= int(f.start.timestamp())) & (s.created_at < int(f.end.timestamp()))
        if f.org_ids:
            mask &= s.org_id.isin(f.org_ids)
        if f.user_ids:
            mask &= s.user_id.isin(f.user_ids)
        if f.categories:
            mask &= s.category.isin(f.categories)
        if f.origins:
            mask &= s.origin.isin(f.origins)
        if f.tags:
            mask &= _contains_any(s.tags_json, f.tags)
        if f.repos:
            mask &= _contains_any(s.repo_names_json, f.repos) | s.session_id.isin(
                prs[prs.repo_full_name.isin(f.repos)].session_id
            )
        s = s[mask]
    p = prs if prs.empty else prs[prs.session_id.isin(s.session_id)]
    return s, p


def clip_dates(df: pd.DataFrame, col: str, f: FilterSet, unit: str | None = None) -> pd.DataFrame:
    """Keep rows whose `col` timestamp falls in [f.start, f.end).

    `unit="s"` for integer epoch columns; None (default) parses ISO strings
    or already-datetime columns.
    """
    if df.empty:
        return df
    ts = pd.to_datetime(df[col], unit=unit, utc=True)
    mask = (ts >= pd.Timestamp(f.start)) & (ts < pd.Timestamp(f.end))
    return df[mask]


def previous_period(f: FilterSet) -> FilterSet:
    """Same-length window immediately preceding the current one."""
    span = f.end - f.start
    return FilterSet(
        start=f.start - span,
        end=f.start - timedelta(microseconds=1),
        org_ids=list(f.org_ids),
        user_ids=list(f.user_ids),
        categories=list(f.categories),
        origins=list(f.origins),
        repos=list(f.repos),
        tags=list(f.tags),
    )
