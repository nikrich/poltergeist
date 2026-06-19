"""Browse half of the import repo: spaces, pages, search, jira issues,
and the 409 (not-configured) detection. AtlassianClient is faked via the
conftest `fake_atlassian` registry."""
from pathlib import Path

import pytest

from ghostbrain.api.tests.conftest import write_import_routing

PAGE_LIST_ITEM = {
    "id": "100",
    "type": "page",
    "title": "ASCP architecture",
    "version": {"number": 4, "when": "2026-06-01T10:00:00.000Z"},
    "children": {"page": {"size": 2}},
}
PAGE_LIST_LEAF = {
    "id": "200",
    "type": "page",
    "title": "Runbooks",
    "version": {"number": 1, "when": "2026-05-20T08:00:00.000Z"},
    "children": {"page": {"size": 0}},
}
# Folders have no version; their "children" carries both page + folder sizes.
FOLDER_ITEM = {
    "id": "900",
    "type": "folder",
    "title": "Onboarding",
    "children": {"page": {"size": 6}, "folder": {"size": 0}},
}
# A leaf page that has child folders but no child pages — must still expand.
PAGE_WITH_ONLY_FOLDER_CHILDREN = {
    "id": "300",
    "type": "page",
    "title": "Strategic Planning",
    "version": {"number": 2, "when": "2026-05-01T08:00:00.000Z"},
    "children": {"page": {"size": 0}, "folder": {"size": 3}},
}
SEARCH_HIT = {
    "id": "300",
    "title": "Quote domain design",
    "space": {"key": "SPE"},
    "version": {"number": 7, "when": "2026-04-01T09:00:00.000Z"},
    "children": {"page": {"size": 0}},
}
ISSUE_LIST_ITEM = {
    "key": "DIGISURE-1",
    "fields": {
        "summary": "Fix the BFF",
        "status": {"name": "In Progress"},
        "project": {"key": "DIGISURE"},
        "updated": "2026-06-08T10:00:00.000+0000",
    },
}


def test_list_spaces_returns_monitored_spaces_with_names(
    tmp_vault: Path, fake_atlassian
):
    from ghostbrain.api.repo.import_atlassian import list_spaces

    write_import_routing(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/space"] = {
        "results": [
            {"key": "DIG", "name": "Digisure"},
            {"key": "SPE", "name": "Short-term"},
        ]
    }
    rows = list_spaces()
    assert rows == [
        {"site": "sft.atlassian.net", "siteSlug": "sft", "key": "DIG",
         "name": "Digisure", "context": "sanlam"},
        {"site": "sft.atlassian.net", "siteSlug": "sft", "key": "SPE",
         "name": "Short-term", "context": "sanlam"},
    ]


def test_list_spaces_falls_back_to_key_when_name_lookup_fails(
    tmp_vault: Path, fake_atlassian
):
    from ghostbrain.api.repo.import_atlassian import list_spaces

    write_import_routing(tmp_vault)

    def boom(path, params):
        raise RuntimeError("confluence is down")

    fake_atlassian.routes["/wiki/rest/api/space"] = boom
    rows = list_spaces()
    assert [r["name"] for r in rows] == ["DIG", "SPE"]


def test_list_spaces_raises_when_unconfigured(tmp_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import (
        CONFLUENCE_NOT_CONFIGURED,
        ImportNotConfiguredError,
        list_spaces,
    )

    # no routing.yaml at all
    with pytest.raises(ImportNotConfiguredError) as exc:
        list_spaces()
    assert str(exc.value) == CONFLUENCE_NOT_CONFIGURED


def test_list_spaces_raises_when_auth_missing(
    tmp_vault: Path, fake_atlassian, monkeypatch: pytest.MonkeyPatch
):
    from ghostbrain.api.repo import import_atlassian as repo
    from ghostbrain.connectors.atlassian._base import AtlassianAuthError

    write_import_routing(tmp_vault)

    def no_auth(host):
        raise AtlassianAuthError("ATLASSIAN_EMAIL not set")

    monkeypatch.setattr(repo, "auth_for_site", no_auth)
    with pytest.raises(repo.ImportNotConfiguredError) as exc:
        repo.list_spaces()
    assert str(exc.value) == repo.CONFLUENCE_NOT_CONFIGURED


def test_list_pages_top_level_uses_root_depth(tmp_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import list_confluence_pages

    write_import_routing(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/space/DIG/content/page"] = {
        "results": [PAGE_LIST_ITEM, PAGE_LIST_LEAF]
    }
    page = list_confluence_pages(site="sft.atlassian.net", space="DIG")
    assert page["items"] == [
        {"site": "sft.atlassian.net", "id": "100", "title": "ASCP architecture",
         "type": "page", "parentId": None, "hasChildren": True,
         "updatedAt": "2026-06-01T10:00:00.000Z", "version": 4, "space": "DIG"},
        {"site": "sft.atlassian.net", "id": "200", "title": "Runbooks",
         "type": "page", "parentId": None, "hasChildren": False,
         "updatedAt": "2026-05-20T08:00:00.000Z", "version": 1, "space": "DIG"},
    ]
    assert page["nextCursor"] is None  # fewer results than the limit
    host, path, params = fake_atlassian.calls[-1]
    assert params["depth"] == "root"
    assert params["start"] == 0
    # Root must request folder children too, so the homepage's expand arrow
    # reflects folders, not just child pages.
    assert "children.page" in params["expand"]
    assert "children.folder" in params["expand"]


def test_list_pages_top_level_root_haschildren_counts_folders(
    tmp_vault: Path, fake_atlassian
):
    """A root page with only folder children must still be expandable."""
    from ghostbrain.api.repo.import_atlassian import list_confluence_pages

    write_import_routing(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/space/DIG/content/page"] = {
        "results": [PAGE_WITH_ONLY_FOLDER_CHILDREN]
    }
    page = list_confluence_pages(site="sft.atlassian.net", space="DIG")
    assert page["items"][0]["hasChildren"] is True
    assert page["items"][0]["type"] == "page"


def test_list_pages_children_merges_folders_first(tmp_vault: Path, fake_atlassian):
    """Expanding a node lists its child folders (expand-only) and child
    pages together, folders first so the tree mirrors Confluence's grouping."""
    from ghostbrain.api.repo.import_atlassian import list_confluence_pages

    write_import_routing(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/content/100/child/folder"] = {
        "results": [FOLDER_ITEM]
    }
    fake_atlassian.routes["/wiki/rest/api/content/100/child/page"] = {
        "results": [PAGE_LIST_LEAF]
    }
    page = list_confluence_pages(
        site="sft.atlassian.net", space="DIG", parent="100"
    )
    assert page["items"] == [
        {"site": "sft.atlassian.net", "id": "900", "title": "Onboarding",
         "type": "folder", "parentId": "100", "hasChildren": True,
         "updatedAt": None, "version": None, "space": "DIG"},
        {"site": "sft.atlassian.net", "id": "200", "title": "Runbooks",
         "type": "page", "parentId": "100", "hasChildren": False,
         "updatedAt": "2026-05-20T08:00:00.000Z", "version": 1, "space": "DIG"},
    ]


def test_list_pages_next_cursor_when_either_list_full(
    tmp_vault: Path, fake_atlassian
):
    """nextCursor advances if EITHER the page or folder page was full —
    otherwise a full folder list with few pages would drop folders."""
    from ghostbrain.api.repo.import_atlassian import list_confluence_pages

    write_import_routing(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/content/100/child/folder"] = {
        "results": [FOLDER_ITEM, FOLDER_ITEM]  # full at limit=2
    }
    fake_atlassian.routes["/wiki/rest/api/content/100/child/page"] = {
        "results": []  # no more pages
    }
    page = list_confluence_pages(
        site="sft.atlassian.net", space="DIG", parent="100", limit=2
    )
    assert page["nextCursor"] == "2"


def test_list_pages_children_with_cursor(tmp_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import list_confluence_pages

    write_import_routing(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/content/100/child/page"] = {
        "results": [PAGE_LIST_ITEM, PAGE_LIST_LEAF]
    }
    fake_atlassian.routes["/wiki/rest/api/content/100/child/folder"] = {
        "results": []
    }
    page = list_confluence_pages(
        site="sft.atlassian.net", space="DIG", parent="100", limit=2, cursor="4"
    )
    assert [i["parentId"] for i in page["items"]] == ["100", "100"]
    assert [i["type"] for i in page["items"]] == ["page", "page"]
    # page list hit the limit → there may be more; nextCursor advances by limit.
    assert page["nextCursor"] == "6"
    page_calls = [c for c in fake_atlassian.calls if c[1].endswith("/child/page")]
    host, path, params = page_calls[-1]
    assert path == "/wiki/rest/api/content/100/child/page"
    assert params["start"] == 4
    assert params["limit"] == 2


def test_list_pages_rejects_unknown_site_or_space(tmp_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import list_confluence_pages

    write_import_routing(tmp_vault)
    with pytest.raises(ValueError):
        list_confluence_pages(site="evil.atlassian.net", space="DIG")
    with pytest.raises(ValueError):
        list_confluence_pages(site="sft.atlassian.net", space="NOTMONITORED")


def test_search_confluence_builds_title_cql_across_spaces(
    tmp_vault: Path, fake_atlassian
):
    from ghostbrain.api.repo.import_atlassian import search_confluence

    write_import_routing(tmp_vault)
    fake_atlassian.routes["/wiki/rest/api/content/search"] = {
        "results": [SEARCH_HIT]
    }
    rows = search_confluence(q='quote "domain"')
    assert rows == [
        {"site": "sft.atlassian.net", "id": "300", "title": "Quote domain design",
         "type": "page", "parentId": None, "hasChildren": False,
         "updatedAt": "2026-04-01T09:00:00.000Z", "version": 7, "space": "SPE"},
    ]
    host, path, params = fake_atlassian.calls[-1]
    cql = params["cql"]
    assert 'type = page' in cql
    assert 'space = "DIG"' in cql and 'space = "SPE"' in cql
    assert 'title ~ "quote \\"domain\\""' in cql


def test_jira_issues_default_my_issues_jql(tmp_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import list_jira_issues
    from ghostbrain.connectors.jira import MY_ISSUES_JQL

    write_import_routing(tmp_vault)
    fake_atlassian.routes["/rest/api/3/search/jql"] = {"issues": [ISSUE_LIST_ITEM]}
    rows = list_jira_issues()
    assert rows == [
        {"site": "sft.atlassian.net", "key": "DIGISURE-1", "summary": "Fix the BFF",
         "status": "In Progress", "project": "DIGISURE",
         "updatedAt": "2026-06-08T10:00:00.000+0000"},
    ]
    host, path, params = fake_atlassian.calls[-1]
    assert params["jql"] == f"{MY_ISSUES_JQL} ORDER BY updated DESC"


def test_jira_issues_text_search(tmp_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import list_jira_issues

    write_import_routing(tmp_vault)
    fake_atlassian.routes["/rest/api/3/search/jql"] = {"issues": [ISSUE_LIST_ITEM]}
    list_jira_issues(q="cashback")
    host, path, params = fake_atlassian.calls[-1]
    assert params["jql"] == 'text ~ "cashback" ORDER BY updated DESC'


def test_jira_issues_raises_when_unconfigured(tmp_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import (
        JIRA_NOT_CONFIGURED,
        ImportNotConfiguredError,
        list_jira_issues,
    )

    write_import_routing(tmp_vault, jira=False)  # confluence only
    with pytest.raises(ImportNotConfiguredError) as exc:
        list_jira_issues()
    assert str(exc.value) == JIRA_NOT_CONFIGURED


def test_list_pages_rejects_non_numeric_parent(tmp_vault, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import list_confluence_pages

    write_import_routing(tmp_vault)
    with pytest.raises(ValueError, match="invalid parent page id"):
        list_confluence_pages("sft.atlassian.net", "DIGI", parent="../secrets")
