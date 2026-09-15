import httpx
import respx

from devin_kpi.enrichment.git_providers import GitHubProvider, enrich_prs
from devin_kpi.enrichment.trackers import JiraTracker
from devin_kpi.store import Store

GH = "https://api.github.com"


@respx.mock
def test_github_provider_fetch():
    respx.get(f"{GH}/repos/acme/widgets/pulls/7").mock(
        return_value=httpx.Response(
            200,
            json={
                "created_at": "2024-01-10T10:00:00Z",
                "merged_at": "2024-01-11T10:00:00Z",
                "closed_at": "2024-01-11T10:00:00Z",
                "review_comments": 2,
                "additions": 100,
                "deletions": 20,
            },
        )
    )
    respx.get(f"{GH}/repos/acme/widgets/pulls/7/reviews").mock(
        return_value=httpx.Response(
            200,
            json=[{"state": "CHANGES_REQUESTED"}, {"state": "APPROVED"}, {"state": "COMMENTED"}],
        )
    )
    respx.get(f"{GH}/repos/acme/widgets/pulls/7/comments").mock(
        return_value=httpx.Response(200, json=[{"id": 1}, {"id": 2}, {"id": 3}])
    )
    meta = GitHubProvider("tok").fetch("acme/widgets", 7)
    assert meta.review_rounds == 2  # APPROVED + CHANGES_REQUESTED
    assert meta.review_comments == 3 + 2
    assert meta.additions == 100
    assert meta.merged_at is not None


@respx.mock
def test_enrich_prs_updates_store(tmp_path):
    respx.get(f"{GH}/repos/acme/widgets/pulls/7").mock(
        return_value=httpx.Response(
            200,
            json={
                "created_at": "2024-01-10T10:00:00Z",
                "merged_at": None,
                "closed_at": None,
                "review_comments": 1,
                "additions": 5,
                "deletions": 1,
            },
        )
    )
    respx.get(f"{GH}/repos/acme/widgets/pulls/7/reviews").mock(
        return_value=httpx.Response(200, json=[])
    )
    respx.get(f"{GH}/repos/acme/widgets/pulls/7/comments").mock(
        return_value=httpx.Response(200, json=[])
    )
    store = Store(tmp_path / "s.sqlite")
    store.upsert(
        "session_prs",
        {
            "session_id": "s1",
            "pr_url": "https://github.com/acme/widgets/pull/7",
            "pr_state": "open",
            "provider": "github",
            "repo_full_name": "acme/widgets",
            "pr_number": 7,
            "pr_created_at": None,
            "merged_at": None,
            "closed_at": None,
            "review_comments": None,
            "review_rounds": None,
            "additions": None,
            "deletions": None,
            "enriched_at": None,
        },
    )
    store.commit()
    n = enrich_prs(store, {"github": GitHubProvider("tok")})
    assert n == 1
    row = store.read_df("session_prs").iloc[0]
    assert row.pr_created_at is not None
    assert row.enriched_at is not None


@respx.mock
def test_jira_story_points():
    respx.get("https://jira.example.com/rest/api/3/issue/ABC-1").mock(
        return_value=httpx.Response(200, json={"fields": {"customfield_10016": 5}})
    )
    t = JiraTracker("https://jira.example.com", "e@x.com", "tok", "customfield_10016")
    assert t.story_points("ABC-1") == 5.0
