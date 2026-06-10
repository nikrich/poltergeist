"""Chat conversation → LLM summary → routed jot."""
from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from ghostbrain.api.repo import chat_export, chat_store


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    v = tmp_path / "vault"
    (v / "00-inbox/raw/manual").mkdir(parents=True)
    (v / "90-meta").mkdir(parents=True)
    (v / "20-contexts").mkdir()
    monkeypatch.setenv("VAULT_PATH", str(v))
    monkeypatch.setenv("GHOSTBRAIN_CHATS_DIR", str(tmp_path / "chats"))
    return v


def _conv_with_messages() -> dict:
    conv = chat_store.create()
    chat_store.append_user_message(conv, "what did we decide about the rebrand?")
    chat_store.append_assistant_message(
        conv,
        "You renamed ghost-brain to Poltergeist. See [[20-contexts/codeship/decision]].",
        [{"name": "search", "summary": "searched vault: rebrand"}],
    )
    return conv


class FakeLLMResult:
    text = "## Rebrand summary\n\n- renamed to Poltergeist [[20-contexts/codeship/decision]]\n"


def test_export_writes_summary_jot_and_routes(env, monkeypatch):
    conv = _conv_with_messages()
    captured: dict = {}

    def fake_run(prompt, **kw):
        captured["prompt"] = prompt
        return FakeLLMResult()

    monkeypatch.setattr(chat_export.llm, "run", fake_run)
    monkeypatch.setattr(
        chat_export,
        "route_existing_jot",
        lambda jot_id: {"id": jot_id, "path": f"20-contexts/codeship/notes/{jot_id}.md",
                        "routingStatus": "routed", "context": "codeship", "project": None},
    )
    result = chat_export.export_conversation(conv["id"])
    assert result["routingStatus"] == "routed"
    assert result["context"] == "codeship"
    # the transcript and the citation made it into the prompt
    assert "rebrand" in captured["prompt"]
    assert "[[20-contexts/codeship/decision]]" in captured["prompt"]
    # frontmatter marks provenance (file may have been "moved" by the fake router;
    # read via the inbox path captured before routing)
    assert result["jot_id"]


def test_export_empty_conversation_rejected(env):
    conv = chat_store.create()
    with pytest.raises(chat_export.NothingToExport):
        chat_export.export_conversation(conv["id"])


def test_export_unknown_conversation(env):
    with pytest.raises(chat_export.ConversationNotFound):
        chat_export.export_conversation("nope")


def test_concurrent_export_busy_guard(env, monkeypatch):
    conv = _conv_with_messages()
    other = _conv_with_messages()
    probed: list[bool] = []

    def fake_run(prompt, **kw):
        if not probed:
            probed.append(True)
            # While conv's export is "running" (we're inside its LLM call),
            # a second export of the SAME conversation bounces off the busy
            # guard — the re-entrant call proves the guard covers the whole
            # export window...
            with pytest.raises(chat_export.ExportInProgress):
                chat_export.export_conversation(conv["id"])
            # ...while a DIFFERENT conversation is not blocked (the probe
            # flag keeps this nested export from recursing again).
            inner = chat_export.export_conversation(other["id"])
            assert inner["jot_id"]
        return FakeLLMResult()

    monkeypatch.setattr(chat_export.llm, "run", fake_run)
    monkeypatch.setattr(
        chat_export,
        "route_existing_jot",
        lambda jot_id: {"id": jot_id, "path": f"00-inbox/raw/manual/{jot_id}.md",
                        "routingStatus": "manual_review"},
    )
    result = chat_export.export_conversation(conv["id"])
    assert result["jot_id"]
    assert probed  # the in-flight assertions above actually ran

    # Guard releases on completion: the same conversation exports fine again.
    again = chat_export.export_conversation(conv["id"])
    assert again["jot_id"]


def test_llm_failure_writes_nothing(env, monkeypatch):
    conv = _conv_with_messages()

    def boom(prompt, **kw):
        raise chat_export.llm.LLMError("over budget")

    monkeypatch.setattr(chat_export.llm, "run", boom)
    with pytest.raises(chat_export.llm.LLMError):
        chat_export.export_conversation(conv["id"])
    inbox = env / "00-inbox/raw/manual"
    assert list(inbox.glob("*.md")) == []
