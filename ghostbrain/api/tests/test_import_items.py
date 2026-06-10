"""import_items(): fetch + convert + persist (connector-identical) + inline
routing + audit + per-item error isolation. AtlassianClient is faked via the
conftest `fake_atlassian` registry; routing is path-based so no LLM runs."""
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from ghostbrain.api.tests.conftest import write_import_routing, write_live_config

PAGE_RAW = {
    "id": "1234567",
    "title": "ASCP architecture overview",
    "space": {"key": "DIG"},
    "version": {
        "number": 5,
        "when": "2026-05-07T09:30:00.000Z",
        "by": {"accountId": "u1", "displayName": "Jannik"},
    },
    "body": {
        "storage": {
            "value": "<p>This is the <strong>ASCP</strong> overview.</p>",
        },
    },
    "_links": {
        "base": "https://sft.atlassian.net/wiki",
        "webui": "/spaces/DIG/pages/1234567/Overview",
    },
}

ISSUE_RAW = {
    "key": "DIGISURE-1234",
    "id": "10001",
    "fields": {
        "summary": "Add cashback to quote domain",
        "status": {"name": "In Progress",
                   "statusCategory": {"key": "indeterminate"}},
        "priority": {"name": "Medium"},
        "issuetype": {"name": "Story"},
        "assignee": {"accountId": "abc", "displayName": "Jannik"},
        "reporter": {"accountId": "def", "displayName": "Reporter"},
        "labels": ["capstone"],
        "project": {"key": "DIGISURE"},
        "created": "2026-05-01T08:00:00.000+0000",
        "updated": "2026-05-07T10:00:00.000+0000",
        "description": {
            "type": "doc",
            "content": [{
                "type": "paragraph",
                "content": [{"type": "text", "text": "Add a cashback field..."}],
            }],
        },
    },
}

PAGE_ITEM = {"kind": "confluence_page", "site": "sft.atlassian.net", "id": "1234567"}
ISSUE_ITEM = {"kind": "jira_issue", "site": "sft.atlassian.net", "key": "DIGISURE-1234"}


@pytest.fixture
def configured_vault(tmp_vault: Path) -> Path:
    write_import_routing(tmp_vault)
    write_live_config(tmp_vault)
    return tmp_vault


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    end = text.find("\n---", 4)
    return yaml.safe_load(text[4:end])


def _audit_lines(vault: Path) -> list[dict]:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    f = vault / "90-meta" / "audit" / f"{day}.jsonl"
    if not f.exists():
        return []
    return [json.loads(line) for line in f.read_text().splitlines() if line.strip()]


def test_import_confluence_page_writes_routed_note_and_audit(
    configured_vault: Path, fake_atlassian
):
    from ghostbrain.api.repo.import_atlassian import import_items

    fake_atlassian.routes["/wiki/rest/api/content/1234567"] = PAGE_RAW
    results = import_items([PAGE_ITEM])

    assert len(results) == 1
    r = results[0]
    assert r["kind"] == "confluence_page"
    assert r["id"] == "1234567"
    assert r["ok"] is True
    assert r["context"] == "sanlam"
    assert r["updated"] is False
    assert r["path"].startswith("20-contexts/sanlam/confluence/")

    # fetched with the connector's exact expand set
    host, path, params = fake_atlassian.calls[-1]
    assert params == {"expand": "body.storage,version,space,history"}

    note = configured_vault / r["path"]
    fm = _frontmatter(note)
    assert fm["id"] == "confluence:sft:1234567"
    assert fm["source"] == "confluence"
    assert fm["space"] == "DIG"
    assert fm["context"] == "sanlam"
    assert fm["routingMethod"] == "path"
    assert fm["sourceUrl"].endswith("/spaces/DIG/pages/1234567/Overview")
    assert "**ASCP**" in note.read_text()

    # inbox copy exists too (write_note always writes it)
    inbox = configured_vault / "00-inbox" / "raw" / "confluence"
    assert len(list(inbox.glob("*.md"))) == 1

    audits = [a for a in _audit_lines(configured_vault)
              if a["event_type"] == "import_completed"]
    assert len(audits) == 1
    assert audits[0]["event_id"] == "confluence:sft:1234567"
    assert audits[0]["source"] == "confluence"
    assert audits[0]["ok"] is True
    assert audits[0]["context"] == "sanlam"


def test_import_jira_issue_writes_routed_note(configured_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import import_items

    fake_atlassian.routes["/rest/api/3/issue/DIGISURE-1234"] = ISSUE_RAW
    results = import_items([ISSUE_ITEM])

    r = results[0]
    assert r["ok"] is True
    assert r["key"] == "DIGISURE-1234"
    assert r["path"].startswith("20-contexts/sanlam/jira/tickets/")
    fm = _frontmatter(configured_vault / r["path"])
    assert fm["id"] == "jira:sft:DIGISURE-1234"
    assert fm["key"] == "DIGISURE-1234"
    assert fm["status"] == "In Progress"
    # fetched with the connector's full field list (body fidelity)
    host, path, params = fake_atlassian.calls[-1]
    from ghostbrain.connectors.jira import JQL_FIELDS
    assert params == {"fields": JQL_FIELDS}


def test_reimport_unchanged_page_overwrites_same_path_updated_true(
    configured_vault: Path, fake_atlassian
):
    from ghostbrain.api.repo.import_atlassian import import_items

    fake_atlassian.routes["/wiki/rest/api/content/1234567"] = PAGE_RAW
    first = import_items([PAGE_ITEM])[0]
    second = import_items([PAGE_ITEM])[0]

    assert first["updated"] is False
    assert second["updated"] is True
    assert second["path"] == first["path"]
    ctx_dir = configured_vault / "20-contexts" / "sanlam" / "confluence"
    assert len(list(ctx_dir.glob("*.md"))) == 1
    inbox = configured_vault / "00-inbox" / "raw" / "confluence"
    assert len(list(inbox.glob("*.md"))) == 1


def test_reimport_changed_page_removes_stale_note(
    configured_vault: Path, fake_atlassian
):
    from ghostbrain.api.repo.import_atlassian import import_items

    fake_atlassian.routes["/wiki/rest/api/content/1234567"] = PAGE_RAW
    first = import_items([PAGE_ITEM])[0]

    # The page gets edited: new version timestamp + new title → the
    # connector filename changes, so the old note would be a stale duplicate.
    changed = {
        **PAGE_RAW,
        "title": "ASCP architecture overview v2",
        "version": {**PAGE_RAW["version"],
                    "number": 6, "when": "2026-06-09T12:00:00.000Z"},
    }
    fake_atlassian.routes["/wiki/rest/api/content/1234567"] = changed
    second = import_items([PAGE_ITEM])[0]

    assert second["updated"] is True
    assert second["path"] != first["path"]
    ctx_dir = configured_vault / "20-contexts" / "sanlam" / "confluence"
    assert len(list(ctx_dir.glob("*.md"))) == 1  # stale copy removed
    assert not (configured_vault / first["path"]).exists()
    inbox = configured_vault / "00-inbox" / "raw" / "confluence"
    assert len(list(inbox.glob("*.md"))) == 1


def test_failed_item_is_isolated_and_audited(configured_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import import_items

    def not_found(path, params):
        raise RuntimeError("atlassian GET failed (last status=404)")

    fake_atlassian.routes["/wiki/rest/api/content/999"] = not_found
    fake_atlassian.routes["/rest/api/3/issue/DIGISURE-1234"] = ISSUE_RAW

    results = import_items([
        {"kind": "confluence_page", "site": "sft.atlassian.net", "id": "999"},
        ISSUE_ITEM,
    ])
    assert results[0]["ok"] is False
    assert "404" in results[0]["error"]
    assert results[1]["ok"] is True  # the failure never aborts the batch

    audits = [a for a in _audit_lines(configured_vault)
              if a["event_type"] == "import_completed"]
    assert [a["ok"] for a in audits] == [False, True]


def test_import_items_validates_config_upfront(tmp_vault: Path, fake_atlassian):
    from ghostbrain.api.repo.import_atlassian import (
        ImportNotConfiguredError,
        import_items,
    )

    # no routing.yaml → 409-shaped error BEFORE any item is attempted
    with pytest.raises(ImportNotConfiguredError):
        import_items([PAGE_ITEM])
    assert fake_atlassian.calls == []


def test_import_output_identical_to_scheduled_sync(
    configured_vault: Path, fake_atlassian, monkeypatch: pytest.MonkeyPatch
):
    """The byte-compat guarantee: an imported note equals the note the worker
    writes for the same connector event, modulo the ingestedAt timestamp."""
    from datetime import datetime as dt, timezone as tz
    from ghostbrain.api.repo.import_atlassian import import_items
    from ghostbrain.connectors.confluence import ConfluenceConnector
    from ghostbrain.worker.pipeline import process_event

    # 1) Scheduled-sync path: connector fetch (mocked HTTP) → worker pipeline.
    monkeypatch.setattr(
        "ghostbrain.connectors.confluence.AtlassianClient.get",
        lambda self, path, params=None, **kw: {"results": [PAGE_RAW]},
    )
    connector = ConfluenceConnector(
        config={"sites": ["sft.atlassian.net"], "spaces": {"DIG": "sanlam"}},
        queue_dir=configured_vault / "q",
        state_dir=configured_vault / "s",
    )
    events = connector.fetch(dt(2026, 5, 6, tzinfo=tz.utc))
    assert len(events) == 1
    summary = process_event(events[0])
    sync_path = Path(summary["context_path"])
    sync_text = sync_path.read_text(encoding="utf-8")

    # wipe the synced files so the import starts from a clean vault
    Path(summary["inbox_path"]).unlink()
    sync_path.unlink()

    # 2) Import path.
    fake_atlassian.routes["/wiki/rest/api/content/1234567"] = PAGE_RAW
    result = import_items([PAGE_ITEM])[0]
    import_path = configured_vault / result["path"]

    assert import_path.name == sync_path.name  # same deterministic filename

    def normalize(text: str) -> str:
        return re.sub(r"^ingestedAt: .*$", "ingestedAt: X", text, flags=re.M)

    assert normalize(import_path.read_text(encoding="utf-8")) == normalize(sync_text)


def test_reimport_one_page_never_touches_another_pages_note(
    configured_vault: Path, fake_atlassian
):
    """Dedup matches the full frontmatter id — page B must survive a re-import
    of page A even though both share the degenerate filename suffix."""
    from ghostbrain.api.repo.import_atlassian import import_items

    page_b_raw = {
        **PAGE_RAW,
        "id": "7654321",
        "title": "Claims API notes",
        "_links": {
            "base": "https://sft.atlassian.net/wiki",
            "webui": "/spaces/DIG/pages/7654321/Claims",
        },
    }
    page_b_item = {"kind": "confluence_page", "site": "sft.atlassian.net", "id": "7654321"}

    fake_atlassian.routes["/wiki/rest/api/content/1234567"] = PAGE_RAW
    fake_atlassian.routes["/wiki/rest/api/content/7654321"] = page_b_raw
    a1 = import_items([PAGE_ITEM])[0]
    b1 = import_items([page_b_item])[0]
    assert a1["ok"] and b1["ok"]

    # Re-import page A with changed content (new filename → dedup path runs).
    changed_a = {
        **PAGE_RAW,
        "title": "ASCP architecture overview v3",
        "version": {**PAGE_RAW["version"],
                    "number": 7, "when": "2026-06-10T08:00:00.000Z"},
    }
    fake_atlassian.routes["/wiki/rest/api/content/1234567"] = changed_a
    a2 = import_items([PAGE_ITEM])[0]
    assert a2["updated"] is True

    # Page B's note is untouched.
    assert (configured_vault / b1["path"]).exists()
    ctx_dir = configured_vault / "20-contexts" / "sanlam" / "confluence"
    titles = sorted(p.name for p in ctx_dir.glob("*.md"))
    assert len(titles) == 2  # exactly one note per page, no cross-deletion
