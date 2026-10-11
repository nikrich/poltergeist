"""Chat conversation storage: JSON file per conversation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ghostbrain.api.repo import chat_store


@pytest.fixture
def chats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "chats"
    monkeypatch.setenv("GHOSTBRAIN_CHATS_DIR", str(d))
    return d


def test_create_writes_file_with_defaults(chats: Path):
    conv = chat_store.create()
    assert conv["title"] == "new chat"
    assert conv["messages"] == []
    assert conv["claude_session_id"] is None
    on_disk = json.loads((chats / f"{conv['id']}.json").read_text())
    assert on_disk == conv


def test_get_missing_returns_none(chats: Path):
    assert chat_store.get("nope") is None


def test_list_skips_corrupt_and_sorts_newest_first(chats: Path):
    a = chat_store.create()
    chat_store.append_user_message(chat_store.get(a["id"]), "first message")
    b = chat_store.create()  # a has messages now, so this is a fresh conversation
    chat_store.append_user_message(chat_store.get(b["id"]), "later message")
    chats.joinpath("garbage.json").write_text("{not json")
    items = chat_store.list_all()
    assert [c["id"] for c in items] == [b["id"], a["id"]]
    assert items[0]["message_count"] == 1
    assert "messages" not in items[0]


def test_first_user_message_derives_title(chats: Path):
    conv = chat_store.create()
    long_text = "what did we   decide about " + "x" * 100
    chat_store.append_user_message(conv, long_text)
    again = chat_store.get(conv["id"])
    assert again["title"].startswith("what did we decide about")
    assert len(again["title"]) <= 60
    # second message must NOT re-derive the title
    chat_store.append_user_message(again, "another question entirely")
    assert chat_store.get(conv["id"])["title"].startswith("what did we decide")


def test_rename_trims_and_caps(chats: Path):
    conv = chat_store.create()
    chat_store.rename(conv["id"], "  My Chat  ")
    assert chat_store.get(conv["id"])["title"] == "My Chat"
    assert chat_store.rename("missing", "x") is None


def test_delete(chats: Path):
    conv = chat_store.create()
    assert chat_store.delete(conv["id"]) is True
    assert chat_store.get(conv["id"]) is None
    assert chat_store.delete(conv["id"]) is False


def test_append_assistant_message_with_tools_and_session(chats: Path):
    conv = chat_store.create()
    chat_store.append_user_message(conv, "q")
    chat_store.set_session_id(conv, "sess-1")
    chat_store.append_assistant_message(
        conv, "answer", [{"name": "search", "summary": "searched vault: q"}]
    )
    got = chat_store.get(conv["id"])
    assert got["claude_session_id"] == "sess-1"
    assert got["messages"][1] == {
        "role": "assistant",
        "text": "answer",
        "tools": [{"name": "search", "summary": "searched vault: q"}],
        "interrupted": False,
    }


def test_interrupted_flag_persists(chats: Path):
    conv = chat_store.create()
    chat_store.append_assistant_message(conv, "partial", [], interrupted=True)
    assert chat_store.get(conv["id"])["messages"][0]["interrupted"] is True


def test_append_user_message_stores_attachments(chats):
    conv = chat_store.create()
    atts = [{"path": "20-contexts/chat-attachments/a.md", "title": "a.md", "kind": "text"}]
    chat_store.append_user_message(conv, "see attached", attachments=atts)
    reloaded = chat_store.get(conv["id"])
    msg = reloaded["messages"][-1]
    assert msg["attachments"] == atts


def test_append_user_message_omits_empty_attachments(chats):
    conv = chat_store.create()
    chat_store.append_user_message(conv, "plain")
    assert "attachments" not in chat_store.get(conv["id"])["messages"][-1]


def test_create_reuses_existing_empty_conversation(chats: Path):
    # Rapid multi-clicks on "new chat" fire several POSTs before the button
    # disables — create() must be idempotent while an empty conversation exists.
    a = chat_store.create()
    b = chat_store.create()
    c = chat_store.create()
    assert a["id"] == b["id"] == c["id"]
    assert len(list(chats.glob("*.json"))) == 1


def test_create_makes_fresh_conversation_once_previous_has_messages(chats: Path):
    a = chat_store.create()
    chat_store.append_user_message(chat_store.get(a["id"]), "hello")
    b = chat_store.create()
    assert b["id"] != a["id"]
    assert len(list(chats.glob("*.json"))) == 2


def test_project_field_round_trips(chats: Path):
    conv = chat_store.create()
    assert conv["project"] is None
    moved = chat_store.move(conv["id"], context="personal", project="site", folder=None)
    assert (moved["context"], moved["project"]) == ("personal", "site")
    got = chat_store.get(conv["id"])
    assert (got["context"], got["project"]) == ("personal", "site")


def test_update_title_keeps_location(chats: Path):
    conv = chat_store.create()
    chat_store.move(conv["id"], context="personal", project="site", folder=None)
    chat_store.update(conv["id"], title="renamed")
    got = chat_store.get(conv["id"])
    assert got["title"] == "renamed"
    assert (got["context"], got["project"]) == ("personal", "site")


def test_update_missing_conversation_returns_none(chats: Path):
    assert chat_store.update("nope", title="x") is None


def test_list_summaries_carry_project(chats: Path):
    conv = chat_store.create()
    chat_store.move(conv["id"], context="work", project="api", folder=None)
    s = chat_store.list_all()[0]
    assert (s["context"], s["project"]) == ("work", "api")


def test_legacy_file_without_project_reads_null(chats: Path):
    conv = chat_store.create()
    raw = json.loads((chats / f"{conv['id']}.json").read_text())
    del raw["project"]
    (chats / f"{conv['id']}.json").write_text(json.dumps(raw))
    assert chat_store.get(conv["id"]).get("project") is None
    assert chat_store.list_all()[0]["project"] is None


def _raw_write(chats_dir, conv):
    chats_dir.mkdir(parents=True, exist_ok=True)
    (chats_dir / f"{conv['id']}.json").write_text(json.dumps(conv))


def _legacy(conv_id="legacy1", project="work/atlas"):
    return {
        "id": conv_id, "title": "old", "created_at": 1.0, "updated_at": 2.0,
        "claude_session_id": None, "project": project, "messages": [],
    }


def test_legacy_project_is_split_on_read(chats):
    _raw_write(chats, _legacy())
    conv = chat_store.get("legacy1")
    assert (conv["context"], conv["project"], conv["folder"]) == ("work", "atlas", None)
    assert conv["auto_filed"] == "skipped"


def test_legacy_unfiled_reads_clean(chats):
    _raw_write(chats, _legacy(project=None))
    conv = chat_store.get("legacy1")
    assert conv["context"] is None and conv["project"] is None and conv["folder"] is None


def test_legacy_project_without_slash_is_dropped(chats):
    _raw_write(chats, _legacy(project="nonsense"))
    conv = chat_store.get("legacy1")
    assert conv["context"] is None and conv["project"] is None


def test_list_all_includes_location(chats):
    _raw_write(chats, _legacy())
    [s] = chat_store.list_all()
    assert s["context"] == "work" and s["project"] == "atlas"
    assert s["folder"] is None and s["auto_filed"] == "skipped"


def test_create_starts_pending_and_unfiled(chats):
    conv = chat_store.create()
    assert conv["auto_filed"] == "pending"
    assert conv["context"] is None and conv["project"] is None and conv["folder"] is None


def test_move_sets_location_and_done(chats):
    conv = chat_store.create()
    before = conv["updated_at"]
    moved = chat_store.move(conv["id"], context="work", project="atlas", folder="q4")
    assert (moved["context"], moved["project"], moved["folder"]) == ("work", "atlas", "q4")
    assert moved["auto_filed"] == "done"
    assert chat_store.get(conv["id"])["updated_at"] == before


def test_move_context_none_clears_everything(chats):
    conv = chat_store.create()
    chat_store.move(conv["id"], context="work", project="atlas", folder="q4")
    moved = chat_store.move(conv["id"], context=None, project="ignored", folder="ignored")
    assert moved["context"] is None and moved["project"] is None and moved["folder"] is None


def test_move_missing_returns_none(chats):
    assert chat_store.move("nope", context=None, project=None, folder=None) is None


def test_apply_auto_file_only_when_pending(chats):
    conv = chat_store.create()
    filed = chat_store.apply_auto_file(conv["id"], "work", "atlas")
    assert filed["context"] == "work" and filed["auto_filed"] == "done"
    assert chat_store.apply_auto_file(conv["id"], "personal", None) is None
    assert chat_store.get(conv["id"])["context"] == "work"


def test_apply_auto_file_none_marks_done_unfiled(chats):
    conv = chat_store.create()
    out = chat_store.apply_auto_file(conv["id"], None, None)
    assert out["context"] is None and out["auto_filed"] == "done"


def test_apply_auto_file_loses_to_manual_move(chats):
    conv = chat_store.create()
    chat_store.move(conv["id"], context="personal", project=None, folder=None)
    assert chat_store.apply_auto_file(conv["id"], "work", "atlas") is None
    assert chat_store.get(conv["id"])["context"] == "personal"


def test_turn_write_preserves_location_moved_on_disk(chats):
    conv = chat_store.create()
    stale = chat_store.get(conv["id"])          # what the stream handler holds
    chat_store.move(conv["id"], context="work", project="atlas", folder="q4")
    chat_store.append_user_message(stale, "hello")
    chat_store.append_assistant_message(stale, "hi", [])
    chat_store.set_session_id(stale, "sess-1", "claude")
    disk = chat_store.get(conv["id"])
    assert (disk["context"], disk["project"], disk["folder"]) == ("work", "atlas", "q4")
    assert disk["auto_filed"] == "done"
    assert [m["text"] for m in disk["messages"]] == ["hello", "hi"]
    assert stale["context"] == "work"            # caller's dict is refreshed too


def test_rewrite_all_writes_only_changed(chats):
    a = chat_store.create()
    chat_store.append_user_message(a, "x")       # so create() doesn't reuse it
    b = chat_store.create()

    def fn(conv):
        if conv["id"] == a["id"]:
            conv["folder"] = "z"
            conv["context"] = "work"
            return True
        return False

    assert chat_store.rewrite_all(fn) == 1
    assert chat_store.get(a["id"])["folder"] == "z"
    assert chat_store.get(b["id"])["folder"] is None


def test_update_title_only(chats):
    conv = chat_store.create()
    out = chat_store.update(conv["id"], title="renamed")
    assert out["title"] == "renamed"


def test_reserved_registry_file_is_not_a_chat(chats):
    chats.mkdir(parents=True, exist_ok=True)
    reg = chats / "folders.json"
    reg.write_text('{"folders": []}')
    assert chat_store.get("folders") is None
    assert chat_store.delete("folders") is False
    assert reg.exists()
