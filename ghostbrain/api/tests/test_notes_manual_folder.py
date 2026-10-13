from datetime import UTC, datetime

import frontmatter

from ghostbrain.api.repo import notes_manual as nm


def _routed(vault, ctx="work", folder=None):
    (vault / "00-inbox" / "raw" / "manual").mkdir(parents=True, exist_ok=True)
    rec = nm.write_inbox_jot("hello there", captured_at=datetime(2026, 5, 14, 9, tzinfo=UTC))
    nm.move_jot(rec["id"], to_context=ctx, confidence=1.0, method="user", reasoning="t", folder=folder)
    return rec["id"]


def _fm(vault, jot_id):
    return frontmatter.load(vault / nm.read_jot(jot_id)["path"])


def test_move_jot_writes_folder(tmp_vault):
    jid = _routed(tmp_vault, folder="q4/plans")
    assert _fm(tmp_vault, jid)["folder"] == "q4/plans"
    assert nm.list_jots()["items"][0]["folder"] == "q4/plans"


def test_same_location_folder_change_writes_without_moving(tmp_vault):
    jid = _routed(tmp_vault)
    before = nm.read_jot(jid)["path"]
    res = nm.move_jot(jid, to_context="work", confidence=1.0, method="user", reasoning="t", folder="ideas")
    assert res["path"] == before
    assert _fm(tmp_vault, jid)["folder"] == "ideas"


def test_route_same_location_clears_folder(tmp_vault):
    jid = _routed(tmp_vault, folder="ideas")
    nm.move_jot(jid, to_context="work", confidence=0.9, method="llm", reasoning="router")
    assert "folder" not in _fm(tmp_vault, jid).metadata


def test_route_other_context_clears_folder(tmp_vault):
    jid = _routed(tmp_vault, folder="ideas")
    nm.move_jot(jid, to_context="personal", confidence=0.9, method="llm", reasoning="router")
    fm = _fm(tmp_vault, jid)
    assert fm["context"] == "personal" and "folder" not in fm.metadata


def test_mark_manual_review_clears_folder(tmp_vault):
    jid = _routed(tmp_vault, folder="ideas")
    nm.mark_manual_review(jid, reasoning="unsure")
    assert "folder" not in _fm(tmp_vault, jid).metadata


def test_list_rows_default_folder_none(tmp_vault):
    _routed(tmp_vault)
    assert nm.list_jots()["items"][0]["folder"] is None


def test_empty_folder_string_is_root_and_does_not_write(tmp_vault):
    jid = _routed(tmp_vault)
    res = nm.move_jot(jid, to_context="work", confidence=1.0, method="user", reasoning="t", folder="")
    assert "etag" not in res
