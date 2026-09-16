"""Optional git-provider enrichment for PR metadata the Devin API does not
return: when a PR was opened/merged/closed, review activity, and diff size.

review_rounds counts reviews in state APPROVED or CHANGES_REQUESTED (i.e.
completed human review passes). review_comments is the PR's review comment
count (inline review comments) plus top-level review bodies — kept simple:
GitHub's `comments` (issue comments) are NOT included.
"""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from devin_kpi.config import Settings
from devin_kpi.store import Store
from devin_kpi.timeutil import utc_now_epoch

log = logging.getLogger(__name__)


def _epoch(iso: str | None) -> int | None:
    if not iso:
        return None
    from datetime import datetime

    return int(
        datetime.fromisoformat(
            iso.removesuffix("Z") + "+00:00" if iso.endswith("Z") else iso
        ).timestamp()
    )


@dataclass
class PRMetadata:
    pr_created_at: int | None = None
    merged_at: int | None = None
    closed_at: int | None = None
    review_comments: int | None = None
    review_rounds: int | None = None
    additions: int | None = None
    deletions: int | None = None


class PullRequestProvider(Protocol):
    def fetch(self, repo_full_name: str, number: int) -> PRMetadata | None: ...


class GitHubProvider:
    def __init__(self, token: str, base_url: str = "https://api.github.com") -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=30.0,
        )

    def fetch(self, repo_full_name: str, number: int) -> PRMetadata | None:
        try:
            pr = self._client.get(f"/repos/{repo_full_name}/pulls/{number}").json()
            reviews = self._client.get(f"/repos/{repo_full_name}/pulls/{number}/reviews").json()
            comments = self._client.get(f"/repos/{repo_full_name}/pulls/{number}/comments").json()
        except httpx.HTTPError as exc:
            log.warning("GitHub fetch %s#%s failed: %s", repo_full_name, number, exc)
            return None
        rounds = sum(1 for r in reviews if r.get("state") in ("APPROVED", "CHANGES_REQUESTED"))
        return PRMetadata(
            pr_created_at=_epoch(pr.get("created_at")),
            merged_at=_epoch(pr.get("merged_at")),
            closed_at=_epoch(pr.get("closed_at")),
            review_comments=len(comments) + int(pr.get("review_comments") or 0),
            review_rounds=rounds,
            additions=pr.get("additions"),
            deletions=pr.get("deletions"),
        )


class GitLabProvider:
    def __init__(self, token: str, base_url: str = "https://gitlab.com/api/v4") -> None:
        self._client = httpx.Client(
            base_url=base_url, headers={"PRIVATE-TOKEN": token}, timeout=30.0
        )

    def fetch(self, repo_full_name: str, number: int) -> PRMetadata | None:
        from urllib.parse import quote

        proj = quote(repo_full_name, safe="")
        try:
            mr = self._client.get(f"/projects/{proj}/merge_requests/{number}").json()
            approvals = self._client.get(
                f"/projects/{proj}/merge_requests/{number}/approvals"
            ).json()
        except httpx.HTTPError as exc:
            log.warning("GitLab fetch %s!%s failed: %s", repo_full_name, number, exc)
            return None
        diff = mr.get("changes_count")
        return PRMetadata(
            pr_created_at=_epoch(mr.get("created_at")),
            merged_at=_epoch(mr.get("merged_at")),
            closed_at=_epoch(mr.get("closed_at")),
            review_comments=mr.get("user_notes_count"),
            review_rounds=approvals.get("approved_by") and len(approvals["approved_by"]),
            additions=int(diff.split("+")[0]) if diff and "+" in str(diff) else None,
            deletions=None,
        )


class AzureDevOpsProvider:
    def __init__(self, pat: str, base_url: str = "https://dev.azure.com") -> None:
        auth = base64.b64encode(f":{pat}".encode()).decode()
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Basic {auth}"},
            params={"api-version": "7.1"},
            timeout=30.0,
        )

    def fetch(self, repo_full_name: str, number: int) -> PRMetadata | None:
        # repo_full_name is "{org}/{project}/{repo}"
        try:
            org, project, repo = repo_full_name.split("/", 2)
            pr = self._client.get(
                f"/{org}/{project}/_apis/git/repositories/{repo}/pullRequests/{number}"
            ).json()
            threads = self._client.get(
                f"/{org}/{project}/_apis/git/repositories/{repo}/pullRequests/{number}/threads"
            ).json()
        except httpx.HTTPError as exc:
            log.warning("ADO fetch %s#%s failed: %s", repo_full_name, number, exc)
            return None
        n_comments = sum(len(t.get("comments", [])) for t in threads.get("value", []))
        return PRMetadata(
            pr_created_at=_epoch(pr.get("creationDate")),
            merged_at=_epoch(pr.get("closedDate") if pr.get("status") == "completed" else None),
            closed_at=_epoch(pr.get("closedDate")),
            review_comments=n_comments,
            review_rounds=None,
            additions=None,
            deletions=None,
        )


def build_providers(settings: Settings) -> dict[str, PullRequestProvider]:
    providers: dict[str, PullRequestProvider] = {}
    if settings.GITHUB_TOKEN:
        providers["github"] = GitHubProvider(settings.GITHUB_TOKEN)
    if settings.GITLAB_TOKEN:
        providers["gitlab"] = GitLabProvider(settings.GITLAB_TOKEN)
    if settings.AZURE_DEVOPS_PAT:
        providers["azure_devops"] = AzureDevOpsProvider(settings.AZURE_DEVOPS_PAT)
    return providers


def enrich_prs(store: Store, providers: dict[str, PullRequestProvider]) -> int:
    """Fill session_prs enrichment fields for unenriched rows. Returns the
    number of PRs enriched. Providers without a token simply never appear in
    `providers`, so their rows are skipped."""
    df = store.unenriched_prs()
    enriched = 0
    for _, row in df.iterrows():
        provider = providers.get(row["provider"])
        if provider is None:
            continue
        meta = provider.fetch(row["repo_full_name"], int(row["pr_number"]))
        now = utc_now_epoch()
        if meta is None:
            # mark attempted so we don't hammer failing PRs
            store.execute(
                "UPDATE session_prs SET enriched_at=? WHERE pr_url=?",
                (now, row["pr_url"]),
            )
            continue
        store.execute(
            """UPDATE session_prs SET pr_created_at=?, merged_at=?, closed_at=?,
               review_comments=?, review_rounds=?, additions=?, deletions=?,
               enriched_at=? WHERE pr_url=?""",
            (
                meta.pr_created_at,
                meta.merged_at,
                meta.closed_at,
                meta.review_comments,
                meta.review_rounds,
                meta.additions,
                meta.deletions,
                now,
                row["pr_url"],
            ),
        )
        enriched += 1
    store.set_meta("enrichment_prs_at", str(utc_now_epoch()))
    store.commit()
    log.info("enriched %d PRs", enriched)
    return enriched
