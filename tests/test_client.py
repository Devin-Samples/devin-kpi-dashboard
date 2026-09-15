import httpx
import pytest
import respx

from devin_kpi.api.client import DevinClient, ScopeError

BASE = "https://api.devin.ai"


def make_client(org_id=None):
    c = DevinClient("cog_test", BASE, org_id)
    c._sleep = lambda s: None  # no real backoff in tests
    return c


@respx.mock
def test_paginate_three_pages():
    route = respx.get(f"{BASE}/v3/enterprise/sessions")
    route.side_effect = [
        httpx.Response(
            200, json={"items": [{"session_id": "a"}], "end_cursor": "c1", "has_next_page": True}
        ),
        httpx.Response(
            200, json={"items": [{"session_id": "b"}], "end_cursor": "c2", "has_next_page": True}
        ),
        httpx.Response(
            200, json={"items": [{"session_id": "c"}], "end_cursor": "c3", "has_next_page": False}
        ),
    ]
    client = make_client()
    items = list(client.paginate("/v3/enterprise/sessions"))
    assert [i["session_id"] for i in items] == ["a", "b", "c"]
    # cursor forwarded
    assert route.calls[1].request.url.params["after"] == "c1"


@respx.mock
def test_retry_on_429_honors_retry_after():
    route = respx.get(f"{BASE}/v3/x")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "0.01"}),
        httpx.Response(200, json={"ok": True}),
    ]
    client = make_client()
    assert client.get("/v3/x") == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_retry_exhausts_and_raises():
    respx.get(f"{BASE}/v3/x").mock(return_value=httpx.Response(500))
    client = make_client()
    with pytest.raises(httpx.HTTPStatusError):
        client.get("/v3/x")


@respx.mock
def test_detect_scope_enterprise():
    respx.get(f"{BASE}/v3/enterprise/metrics/usage").mock(return_value=httpx.Response(200, json={}))
    assert make_client().detect_scope(1_700_000_000) == "enterprise"


@respx.mock
def test_detect_scope_falls_back_to_org():
    respx.get(f"{BASE}/v3/enterprise/metrics/usage").mock(return_value=httpx.Response(403, json={}))
    respx.get(f"{BASE}/v3/organizations/org_1/metrics/usage").mock(
        return_value=httpx.Response(200, json={})
    )
    assert make_client(org_id="org_1").detect_scope(1_700_000_000) == "organization"


@respx.mock
def test_detect_scope_raises_without_org():
    respx.get(f"{BASE}/v3/enterprise/metrics/usage").mock(return_value=httpx.Response(403, json={}))
    with pytest.raises(ScopeError):
        make_client().detect_scope(1_700_000_000)
