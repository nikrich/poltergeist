"""/v1/import route family: browse endpoints, bulk POST, 409/422 mapping."""
from pathlib import Path

from fastapi.testclient import TestClient

from ghostbrain.api.tests.conftest import write_import_routing, write_live_config
from ghostbrain.api.tests.test_import_items import ISSUE_RAW, PAGE_RAW
from ghostbrain.api.tests.test_import_repo import ISSUE_LIST_ITEM, PAGE_LIST_ITEM

CONFLUENCE_409 = "confluence connector not configured — run onboarding"
JIRA_409 = "jira connector not configured — run onboarding"


def test_spaces_ok(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/space"] = {
        "results": [{"key": "DIG", "name": "Digisure"}]
    }
    res = client.get("/v1/import/confluence/spaces", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert {s["key"] for s in data} == {"DIG", "SPE"}
    by_key = {s["key"]: s for s in data}
    assert by_key["DIG"]["name"] == "Digisure"
    assert by_key["SPE"]["name"] == "SPE"  # lookup miss → key fallback
    assert by_key["DIG"]["siteSlug"] == "sft"
    assert by_key["DIG"]["context"] == "sanlam"


def test_spaces_409_when_unconfigured(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    res = client.get("/v1/import/confluence/spaces", headers=auth_headers)
    assert res.status_code == 409
    assert res.json() == {"detail": CONFLUENCE_409}


def test_pages_ok_passes_params(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/content/100/child/page"] = {
        "results": [PAGE_LIST_ITEM]
    }
    res = client.get(
        "/v1/import/confluence/pages"
        "?site=sft.atlassian.net&space=DIG&parent=100&limit=1&cursor=3",
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert data["items"][0]["id"] == "100"
    assert data["items"][0]["parentId"] == "100"
    assert data["nextCursor"] == "4"  # full page (1 of limit 1) → start+limit
    host, path, params = fake_atlassian.calls[-1]
    assert params["start"] == 3
    assert params["limit"] == 1


def test_pages_requires_site_and_space(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault)
    assert client.get(
        "/v1/import/confluence/pages?space=DIG", headers=auth_headers
    ).status_code == 422
    assert client.get(
        "/v1/import/confluence/pages?site=sft.atlassian.net", headers=auth_headers
    ).status_code == 422
    # unmonitored space → 400 (repo ValueError mapped like notes.py), not 500
    assert client.get(
        "/v1/import/confluence/pages?site=sft.atlassian.net&space=NOPE",
        headers=auth_headers,
    ).status_code == 400


def test_pages_non_numeric_parent_returns_400(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    """Non-numeric parent id is a client error; the route maps ValueError → 400."""
    write_import_routing(tmp_vault)
    res = client.get(
        "/v1/import/confluence/pages"
        "?site=sft.atlassian.net&space=DIG&parent=../secrets",
        headers=auth_headers,
    )
    assert res.status_code == 400
    assert "parent" in res.json()["detail"].lower()


def test_search_ok(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/content/search"] = {
        "results": [PAGE_LIST_ITEM]
    }
    res = client.get("/v1/import/confluence/search?q=arch", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()[0]["title"] == "ASCP architecture"
    host, path, params = fake_atlassian.calls[-1]
    assert 'title ~ "arch"' in params["cql"]


def test_jira_issues_ok(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault)
    fake_atlassian.routes["/rest/api/3/search/jql"] = {"issues": [ISSUE_LIST_ITEM]}
    res = client.get("/v1/import/jira/issues", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()[0]["key"] == "DIGISURE-1"

    res = client.get("/v1/import/jira/issues?q=bff", headers=auth_headers)
    assert res.status_code == 200
    host, path, params = fake_atlassian.calls[-1]
    assert params["jql"].startswith('text ~ "bff"')


def test_jira_issues_409_when_only_confluence_configured(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault, jira=False)
    res = client.get("/v1/import/jira/issues", headers=auth_headers)
    assert res.status_code == 409
    assert res.json() == {"detail": JIRA_409}


def test_post_import_happy_path_writes_note(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault)
    write_live_config(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/content/1234567"] = PAGE_RAW
    fake_atlassian.routes["/rest/api/3/issue/DIGISURE-1234"] = ISSUE_RAW
    res = client.post("/v1/import", headers=auth_headers, json={"items": [
        {"kind": "confluence_page", "site": "sft.atlassian.net", "id": "1234567"},
        {"kind": "jira_issue", "site": "sft.atlassian.net", "key": "DIGISURE-1234"},
    ]})
    assert res.status_code == 200
    results = res.json()["results"]
    assert [r["ok"] for r in results] == [True, True]
    assert results[0]["path"].startswith("20-contexts/sanlam/confluence/")
    assert results[0]["updated"] is False
    assert results[1]["path"].startswith("20-contexts/sanlam/jira/tickets/")
    assert (tmp_vault / results[0]["path"]).exists()
    assert (tmp_vault / results[1]["path"]).exists()


def test_post_import_max_50_items(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault)
    item = {"kind": "jira_issue", "site": "sft.atlassian.net", "key": "X-1"}
    res = client.post("/v1/import", headers=auth_headers,
                      json={"items": [item] * 51})
    assert res.status_code == 422
    res = client.post("/v1/import", headers=auth_headers, json={"items": []})
    assert res.status_code == 422


def test_post_import_409_when_unconfigured(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    res = client.post("/v1/import", headers=auth_headers, json={"items": [
        {"kind": "confluence_page", "site": "sft.atlassian.net", "id": "1"},
    ]})
    assert res.status_code == 409
    assert res.json() == {"detail": CONFLUENCE_409}


def test_post_import_item_missing_identifier_422(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault)
    res = client.post("/v1/import", headers=auth_headers, json={"items": [
        {"kind": "confluence_page", "site": "sft.atlassian.net"},  # no id
    ]})
    assert res.status_code == 422
    res = client.post("/v1/import", headers=auth_headers, json={"items": [
        {"kind": "jira_issue", "site": "sft.atlassian.net"},  # no key
    ]})
    assert res.status_code == 422


def test_post_import_per_item_failure_isolated(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path, fake_atlassian
):
    write_import_routing(tmp_vault)
    write_live_config(tmp_vault)

    def gone(path, params):
        raise RuntimeError("atlassian GET failed (last status=404)")

    fake_atlassian.routes["/wiki/rest/api/content/999"] = gone
    fake_atlassian.routes["/rest/api/3/issue/DIGISURE-1234"] = ISSUE_RAW
    res = client.post("/v1/import", headers=auth_headers, json={"items": [
        {"kind": "confluence_page", "site": "sft.atlassian.net", "id": "999"},
        {"kind": "jira_issue", "site": "sft.atlassian.net", "key": "DIGISURE-1234"},
    ]})
    assert res.status_code == 200
    results = res.json()["results"]
    assert results[0]["ok"] is False
    assert "404" in results[0]["error"]
    assert results[1]["ok"] is True
