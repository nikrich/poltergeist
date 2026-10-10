"""A5: run_assist targets a jot or any vault note; turn keys; draft retrieval."""
from __future__ import annotations

from unittest.mock import patch

from ghostbrain.api.repo import docs_assist, notes_manual
from ghostbrain.api.tests.conftest import write_note

PLAN = "20-contexts/work/plan.md"


def _capture():
    captured: dict = {}

    def fake_turn(prompt, **kw):
        captured.update(kw, prompt=prompt)
        yield {"type": "delta", "text": "ok"}
        yield {"type": "done", "text": "ok"}

    return captured, fake_turn


def test_a_path_target_reads_the_vault_note_and_uses_the_stream_key(tmp_vault):
    write_note(tmp_vault, PLAN, "---\ntitle: Plan\n---\n# Plan\n\nship the beta\n")
    captured, fake = _capture()
    with patch.object(docs_assist.agent, "run_chat_turn", fake):
        events = list(docs_assist.run_assist(
            path=PLAN, stream_key="inline-1", instruction=None,
            selection="ship the beta", mode="polish",
        ))
    assert [e["type"] for e in events] == ["delta", "done"]
    assert "ship the beta" in captured["prompt"]
    assert captured["turn_key"] == "docs:inline-1"
    assert captured["system_prompt"] == docs_assist.DOCS_SYSTEM_PROMPT
    assert captured["allowed_tools"] == docs_assist.DOCS_ALLOWED_TOOLS


def test_missing_and_unsafe_paths_are_error_events(tmp_vault):
    kw = dict(instruction=None, selection=None, mode="polish")
    assert list(docs_assist.run_assist(path="20-contexts/work/nope.md", **kw)) == [
        {"type": "error", "message": "note not found"}
    ]
    assert list(docs_assist.run_assist(path="../outside.md", **kw)) == [
        {"type": "error", "message": "invalid note path"}
    ]


def test_the_turn_key_defaults_to_the_jot_id_then_the_path(tmp_vault):
    rec = notes_manual.write_inbox_jot("# Doc\n\nhello")
    captured, fake = _capture()
    with patch.object(docs_assist.agent, "run_chat_turn", fake):
        list(docs_assist.run_assist(rec["id"], instruction=None, selection=None, mode="polish"))
    assert captured["turn_key"] == f"docs:{rec['id']}"
    write_note(tmp_vault, PLAN, "# Plan\n")
    with patch.object(docs_assist.agent, "run_chat_turn", fake):
        list(docs_assist.run_assist(path=PLAN, instruction=None, selection=None, mode="polish"))
    assert captured["turn_key"] == f"docs:path:{PLAN}"


def test_continue_passes_before_and_target_fields_to_the_prompt(tmp_vault):
    write_note(tmp_vault, PLAN, "# Plan\n\nwe will")
    captured, fake = _capture()
    with patch.object(docs_assist.agent, "run_chat_turn", fake):
        list(docs_assist.run_assist(
            path=PLAN, instruction=None, selection=None, mode="continue",
            before="# Plan\n\nwe will", placement="cursor",
        ))
    assert "TEXT BEFORE THE CURSOR:\n# Plan\n\nwe will" in captured["prompt"]


def test_draft_gathers_vault_context_and_announces_it(tmp_vault, monkeypatch):
    write_note(tmp_vault, PLAN, "# Plan\n")
    monkeypatch.setattr(
        docs_assist.docs_context, "gather",
        lambda q, current_path: f"CTX for {q} near {current_path}",
    )
    captured, fake = _capture()
    with patch.object(docs_assist.agent, "run_chat_turn", fake):
        events = list(docs_assist.run_assist(
            path=PLAN, instruction="risks", selection=None, mode="draft",
            placement="cursor", before="# Plan",
        ))
    assert events[0] == {"type": "tool", "name": "vault_context", "summary": "reading related notes"}
    assert f"CTX for risks near {PLAN}" in captured["prompt"]


def test_other_modes_never_search(tmp_vault, monkeypatch):
    write_note(tmp_vault, PLAN, "# Plan\n\ntext")
    calls: list = []
    monkeypatch.setattr(docs_assist.docs_context, "gather", lambda *a, **k: calls.append(1) or "")
    _, fake = _capture()
    with patch.object(docs_assist.agent, "run_chat_turn", fake):
        for mode in ("polish", "expand", "summarize", "continue"):
            list(docs_assist.run_assist(path=PLAN, instruction=None, selection="text", mode=mode))
    assert calls == []


def test_cancel_uses_the_stream_key(monkeypatch):
    seen = []
    monkeypatch.setattr(docs_assist.agent, "cancel_turn", lambda key: seen.append(key) or True)
    assert docs_assist.cancel("inline-9") is True
    assert seen == ["docs:inline-9"]


def test_a_windows_jot_path_reaches_gather_as_posix(tmp_vault, monkeypatch):
    monkeypatch.setattr(
        docs_assist.notes_manual, "read_jot",
        lambda jot_id: {"body": "# Doc\n", "path": "00-inbox\\manual\\doc.md"},
    )
    seen: list = []
    monkeypatch.setattr(
        docs_assist.docs_context, "gather",
        lambda q, current_path: seen.append(current_path) or "",
    )
    _, fake = _capture()
    with patch.object(docs_assist.agent, "run_chat_turn", fake):
        list(docs_assist.run_assist("j1", instruction="risks", selection=None, mode="draft"))
    assert seen == ["00-inbox/manual/doc.md"]
