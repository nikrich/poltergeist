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
    b = chat_store.create()
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
