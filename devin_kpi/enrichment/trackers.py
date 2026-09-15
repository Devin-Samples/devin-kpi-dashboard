"""Optional issue-tracker enrichment: story points for cost-per-point KPIs.

Jira:  GET {base}/rest/api/3/issue/{key}?fields={story_points_field}
Linear: GraphQL issue(id:) accepts identifiers like ENG-123, returns estimate.
No credentials -> no-op with a logged reason.
"""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from devin_kpi.config import Settings
from devin_kpi.store import Store
from devin_kpi.timeutil import utc_now_epoch

log = logging.getLogger(__name__)


class Tracker(Protocol):
    name: str

    def story_points(self, key: str) -> float | None: ...


class JiraTracker:
    name = "jira"

    def __init__(self, base_url: str, email: str, api_token: str, field: str) -> None:
        self.field = field
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            auth=(email, api_token),
            headers={"Accept": "application/json"},
            timeout=30.0,
        )

    def story_points(self, key: str) -> float | None:
        try:
            data = self._client.get(
                f"/rest/api/3/issue/{key}", params={"fields": self.field}
            ).json()
        except httpx.HTTPError as exc:
            log.warning("Jira fetch %s failed: %s", key, exc)
            return None
        value = (data.get("fields") or {}).get(self.field)
        return float(value) if value is not None else None


class LinearTracker:
    name = "linear"

    def __init__(self, api_key: str, base_url: str = "https://api.linear.app/graphql") -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": api_key, "Content-Type": "application/json"},
            timeout=30.0,
        )

    def story_points(self, key: str) -> float | None:
        query = "query($id: String!) { issue(id: $id) { estimate } }"
        try:
            data = self._client.post("", json={"query": query, "variables": {"id": key}}).json()
        except httpx.HTTPError as exc:
            log.warning("Linear fetch %s failed: %s", key, exc)
            return None
        est = ((data.get("data") or {}).get("issue") or {}).get("estimate")
        return float(est) if est is not None else None


def build_trackers(settings: Settings) -> list[Tracker]:
    trackers: list[Tracker] = []
    if settings.JIRA_BASE_URL and settings.JIRA_EMAIL and settings.JIRA_API_TOKEN:
        trackers.append(
            JiraTracker(
                settings.JIRA_BASE_URL,
                settings.JIRA_EMAIL,
                settings.JIRA_API_TOKEN,
                settings.JIRA_STORY_POINTS_FIELD,
            )
        )
    else:
        log.info("Jira enrichment disabled: JIRA_BASE_URL/JIRA_EMAIL/JIRA_API_TOKEN not set")
    if settings.LINEAR_API_KEY:
        trackers.append(LinearTracker(settings.LINEAR_API_KEY))
    else:
        log.info("Linear enrichment disabled: LINEAR_API_KEY not set")
    return trackers


def enrich_issues(store: Store, trackers: list[Tracker]) -> int:
    """Fill story_points on session_issues rows that have none."""
    if not trackers:
        return 0
    df = store.read_df("session_issues", "story_points IS NULL")
    enriched = 0
    for _, row in df.iterrows():
        for tracker in trackers:
            points = tracker.story_points(row["issue_key"])
            if points is not None:
                store.execute(
                    "UPDATE session_issues SET story_points=?, tracker=?, fetched_at=? "
                    "WHERE session_id=? AND issue_key=?",
                    (points, tracker.name, utc_now_epoch(), row["session_id"], row["issue_key"]),
                )
                enriched += 1
                break
    store.commit()
    log.info("enriched %d issue keys", enriched)
    return enriched
