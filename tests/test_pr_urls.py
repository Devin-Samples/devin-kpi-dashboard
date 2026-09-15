from devin_kpi.enrichment.pr_urls import parse_pr_url


def test_github():
    p = parse_pr_url("https://github.com/acme/widgets/pull/42")
    assert (p.provider, p.repo_full_name, p.pr_number) == ("github", "acme/widgets", 42)


def test_gitlab():
    p = parse_pr_url("https://gitlab.com/acme/group/widgets/-/merge_requests/7")
    assert p.provider == "gitlab"
    assert p.repo_full_name == "acme/group/widgets"
    assert p.pr_number == 7


def test_azure_devops():
    p = parse_pr_url("https://dev.azure.com/myorg/MyProject/_git/widgets/pullrequest/99")
    assert p.provider == "azure_devops"
    assert p.repo_full_name == "myorg/MyProject/widgets"
    assert p.pr_number == 99


def test_unknown_returns_none():
    assert parse_pr_url("https://bitbucket.org/x/y/pull-requests/1") is None
