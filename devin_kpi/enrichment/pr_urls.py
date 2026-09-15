"""Parse provider / repo / PR number out of a pull request URL.

Supported shapes:
  GitHub:      https://github.com/{owner}/{repo}/pull/{n}
  GitLab:      https://gitlab.com/{group}/{repo}/-/merge_requests/{n}
  Azure DevOps: https://dev.azure.com/{org}/{project}/_git/{repo}/pullrequest/{n}
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_GITHUB_RE = re.compile(r"^https?://(?:www\.)?github\.com/([^/]+)/([^/]+)/pull/(\d+)")
_GITLAB_RE = re.compile(r"^https?://(?:www\.)?gitlab\.com/(.+?)/([^/]+)/-/merge_requests/(\d+)")
_ADO_RE = re.compile(r"^https?://dev\.azure\.com/([^/]+)/([^/]+)/_git/([^/]+)/pullrequest/(\d+)")


@dataclass
class ParsedPRUrl:
    provider: str  # "github" | "gitlab" | "azure_devops"
    repo_full_name: str
    pr_number: int


def parse_pr_url(url: str) -> ParsedPRUrl | None:
    if m := _GITHUB_RE.match(url):
        return ParsedPRUrl("github", f"{m.group(1)}/{m.group(2)}", int(m.group(3)))
    if m := _GITLAB_RE.match(url):
        group, repo = m.group(1), m.group(2)
        return ParsedPRUrl("gitlab", f"{group}/{repo}", int(m.group(3)))
    if m := _ADO_RE.match(url):
        org, project, repo, n = m.group(1), m.group(2), m.group(3), int(m.group(4))
        return ParsedPRUrl("azure_devops", f"{org}/{project}/{repo}", n)
    return None
