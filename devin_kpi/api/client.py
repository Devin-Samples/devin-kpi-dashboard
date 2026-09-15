"""Read-only httpx client for the Devin Enterprise API.

Implements bearer auth, retry on 429/5xx with Retry-After + exponential
backoff, cursor pagination (first/after -> items/end_cursor/has_next_page),
and enterprise-vs-organization scope detection. Only GET is ever used.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from typing import Any, Literal

import httpx

log = logging.getLogger(__name__)

Scope = Literal["enterprise", "organization"]

MAX_TRIES = 5
PAGE_SIZE = 200


class ScopeError(RuntimeError):
    """Raised when neither enterprise nor organization scope is reachable."""


class DevinClient:
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.devin.ai",
        org_id: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.org_id = org_id
        self._client = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        self._sleep = time.sleep  # injectable for tests

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> DevinClient:  # noqa: PYI034
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET with retry on 429 and 5xx. Honors Retry-After; otherwise
        exponential backoff (1s, 2s, 4s, 8s). Raises for other 4xx."""
        params = {k: v for k, v in (params or {}).items() if v is not None}
        last_exc: Exception | None = None
        for attempt in range(1, MAX_TRIES + 1):
            try:
                resp = self._client.get(path, params=params)
            except httpx.TransportError as exc:  # network-level, retry
                last_exc = exc
                self._backoff(attempt, None)
                continue
            if resp.status_code in (429,) or resp.status_code >= 500:
                retry_after = resp.headers.get("Retry-After")
                if attempt == MAX_TRIES:
                    resp.raise_for_status()
                self._backoff(attempt, float(retry_after) if retry_after else None)
                continue
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"GET {path} failed after {MAX_TRIES} tries") from last_exc

    def _backoff(self, attempt: int, retry_after: float | None) -> None:
        delay = retry_after if retry_after is not None else 2.0 ** (attempt - 1)
        log.warning("request failed (attempt %d); retrying in %.1fs", attempt, delay)
        self._sleep(delay)

    def paginate(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        """Yield items across all pages of a cursor-paginated endpoint."""
        params = dict(params or {})
        params["first"] = PAGE_SIZE
        while True:
            page = self.get(path, params)
            yield from page.get("items", [])
            if not page.get("has_next_page"):
                return
            params["after"] = page.get("end_cursor")

    def detect_scope(self, now_epoch: int) -> Scope:
        """Probe enterprise metrics; fall back to organization scope."""
        params = {"start_time": now_epoch - 86400, "end_time": now_epoch}
        try:
            self.get("/v3/enterprise/metrics/usage", params)
            return "enterprise"
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code not in (401, 403, 404):
                raise
        if self.org_id:
            self.get(f"/v3/organizations/{self.org_id}/metrics/usage", params)
            return "organization"
        raise ScopeError(
            "API key has no enterprise scope and no DEVIN_ORG_ID is set "
            "for an organization-scoped fallback."
        )


# Logical name -> (enterprise path, org path template or None)
_ENDPOINTS: dict[str, tuple[str, str | None]] = {
    "sessions": ("/v3/enterprise/sessions", "/v3/organizations/{org_id}/sessions"),
    "insights": (
        "/v3/enterprise/sessions/insights",
        "/v3/organizations/{org_id}/sessions/insights",
    ),
    "metrics_usage": ("/v3/enterprise/metrics/usage", "/v3/organizations/{org_id}/metrics/usage"),
    "metrics_sessions": (
        "/v3/enterprise/metrics/sessions",
        "/v3/organizations/{org_id}/metrics/sessions",
    ),
    "metrics_prs": ("/v3/enterprise/metrics/prs", "/v3/organizations/{org_id}/metrics/prs"),
    "metrics_by_category": (
        "/v3/enterprise/metrics/sessions-by-category",
        "/v3/organizations/{org_id}/metrics/sessions-by-category",
    ),
    "metrics_dau": ("/v3/enterprise/metrics/dau", "/v3/organizations/{org_id}/metrics/dau"),
    "metrics_wau": ("/v3/enterprise/metrics/wau", "/v3/organizations/{org_id}/metrics/wau"),
    "metrics_mau": ("/v3/enterprise/metrics/mau", "/v3/organizations/{org_id}/metrics/mau"),
    "metrics_active_users": (
        "/v3/enterprise/metrics/active-users",
        "/v3/organizations/{org_id}/metrics/active-users",
    ),
    "consumption_daily": (
        "/v3/enterprise/consumption/daily",
        "/v3/organizations/{org_id}/consumption/daily",
    ),
    "consumption_cycles": ("/v3/enterprise/consumption/cycles", None),
    "code_scan_metrics": ("/v3/enterprise/code-scans/metrics", None),
    "audit_logs": ("/v3/enterprise/audit-logs", None),
}


class Endpoints:
    """Maps logical endpoint names to concrete paths for a scope."""

    def __init__(self, scope: Scope, org_id: str | None = None) -> None:
        self.scope = scope
        self.org_id = org_id

    def path(self, name: str) -> str | None:
        """Return the path for `name`, or None when unavailable in this scope
        (the collector skips those endpoints)."""
        enterprise_path, org_path = _ENDPOINTS[name]
        if self.scope == "enterprise":
            return enterprise_path
        if org_path is None or not self.org_id:
            return None
        return org_path.format(org_id=self.org_id)

    def names(self) -> list[str]:
        return list(_ENDPOINTS)
