"""send_message orchestration: persistence + resume retry, with a fake agent."""
from __future__ import annotations

from pathlib import Path

import pytest

from ghostbrain.api.repo import chat as repo_chat
from ghostbrain.api.repo import chat_store
from ghostbrain.llm.agent import ResumeFailed


@pytest.fixture
def chats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    d = tmp_path / "chats"
    monkeypatch.setenv("GHOSTBRAIN_CHATS_DIR", str(d))
    return d


def happy_turn(prompt, *, session_id=None, **kw):
    yield {"type": "session", "session_id": "sess-1"}
    yield {"type": "delta", "text": "hel"}
    yield {"type": "tool", "name": "search", "summary": "searched vault: x"}
    yield {"type": "delta", "text": "lo"}
    yield {"type": "done", "text": "hello", "session_id": "sess-1"}


def test_send_message_streams_and_persists(chats, monkeypatch):
    monkeypatch.setattr(repo_chat.agent, "run_chat_turn", happy_turn)
    conv = chat_store.create()
    events = list(repo_chat.send_message(conv["id"], "hi there"))
    assert [e["type"] for e in events] == ["session", "delta", "tool", "delta", "done"]
    saved = chat_store.get(conv["id"])
    assert saved["claude_session_id"] == "sess-1"
    assert saved["title"] == "hi there"
    assert saved["messages"][0] == {"role": "user", "text": "hi there"}
    a = saved["messages"][1]
    assert a["role"] == "assistant"
    assert a["text"] == "hello"
    assert a["tools"] == [{"name": "search", "summary": "searched vault: x"}]


def test_missing_conversation_yields_error(chats):
    events = list(repo_chat.send_message("nope", "hi"))
    assert events == [{"type": "error", "message": "conversation not found"}]


def test_error_turn_persists_partial_as_interrupted(chats, monkeypatch):
    def bad_turn(prompt, *, session_id=None, **kw):
        yield {"type": "delta", "text": "par"}
        yield {"type": "error", "message": "boom", "interrupted": True}

    monkeypatch.setattr(repo_chat.agent, "run_chat_turn", bad_turn)
    conv = chat_store.create()
    events = list(repo_chat.send_message(conv["id"], "q"))
    assert events[-1]["type"] == "error"
    saved = chat_store.get(conv["id"])
    assert saved["messages"][1]["text"] == "par"
    assert saved["messages"][1]["interrupted"] is True


def test_error_turn_with_no_partial_skips_assistant_message(chats, monkeypatch):
    def bad_turn(prompt, *, session_id=None, **kw):
        yield {"type": "error", "message": "boom"}

    monkeypatch.setattr(repo_chat.agent, "run_chat_turn", bad_turn)
    conv = chat_store.create()
    list(repo_chat.send_message(conv["id"], "q"))
    saved = chat_store.get(conv["id"])
    assert len(saved["messages"]) == 1  # just the user message


def test_busy_guard_rejects_concurrent_turn_then_releases(chats, monkeypatch):
    monkeypatch.setattr(repo_chat.agent, "run_chat_turn", happy_turn)
    conv = chat_store.create()

    # Start a turn and pull ONE event — the generator is now mid-stream and
    # holds the busy guard for this conversation.
    first = repo_chat.send_message(conv["id"], "slow question")
    assert next(first)["type"] == "session"

    # A second turn on the same conversation is rejected outright.
    events = list(repo_chat.send_message(conv["id"], "again"))
    assert events == [
        {
            "type": "error",
            "message": "a turn is already in progress for this conversation",
        }
    ]

    # Exhaust the first turn — the guard is released on completion.
    rest = list(first)
    assert rest[-1]["type"] == "done"

    # A third turn now proceeds normally.
    third = list(repo_chat.send_message(conv["id"], "third question"))
    assert [e["type"] for e in third] == ["session", "delta", "tool", "delta", "done"]


def test_suspended_busy_generator_does_not_block_other_conversations(
    chats, monkeypatch
):
    """Regression: the busy-path yield must not happen under the global lock.

    A generator suspends at yield without exiting a with-block, so a consumer
    that pulls the busy error and never resumes/closes the generator would
    otherwise keep the lock held — deadlocking every other conversation.
    """
    import threading

    monkeypatch.setattr(repo_chat.agent, "run_chat_turn", happy_turn)
    conv_a = chat_store.create()
    # create() is idempotent while an empty conversation exists — give conv_a
    # a message so conv_b is genuinely a second conversation.
    chat_store.append_user_message(chat_store.get(conv_a["id"]), "seed")
    conv_b = chat_store.create()

    # Hold the busy guard for conv_a mid-stream.
    first = repo_chat.send_message(conv_a["id"], "slow question")
    assert next(first)["type"] == "session"

    # Second turn on conv_a: pull ONLY the busy error, do NOT close/exhaust.
    busy_gen = repo_chat.send_message(conv_a["id"], "again")
    assert next(busy_gen)["type"] == "error"

    # A DIFFERENT conversation must still stream normally. Run it in a worker
    # thread with a timeout so a regression deadlocks the thread, not pytest.
    result: list[dict] = []
    t = threading.Thread(
        target=lambda: result.extend(repo_chat.send_message(conv_b["id"], "hi"))
    )
    t.start()
    t.join(timeout=2)
    assert not t.is_alive(), "send_message on another conversation deadlocked"
    assert [e["type"] for e in result] == ["session", "delta", "tool", "delta", "done"]

    # Cleanup: finish/close the outstanding generators.
    list(first)
    busy_gen.close()


def test_resume_failure_retries_without_session_with_history(chats, monkeypatch):
    calls = []

    def turn(prompt, *, session_id=None, **kw):
        calls.append({"prompt": prompt, "session_id": session_id})
        if session_id is not None:
            raise ResumeFailed("stale")
            yield  # pragma: no cover — makes this a generator
        yield {"type": "session", "session_id": "sess-2"}
        yield {"type": "done", "text": "recovered", "session_id": "sess-2"}

    monkeypatch.setattr(repo_chat.agent, "run_chat_turn", turn)
    conv = chat_store.create()
    chat_store.append_user_message(conv, "first q")
    chat_store.append_assistant_message(conv, "first a", [])
    chat_store.set_session_id(conv, "stale-sess")

    events = list(repo_chat.send_message(conv["id"], "second q"))
    assert events[-1]["type"] == "done"
    assert len(calls) == 2
    assert calls[0]["session_id"] == "stale-sess"
    assert calls[1]["session_id"] is None
    # the retry prompt carries recent history
    assert "first q" in calls[1]["prompt"]
    assert "first a" in calls[1]["prompt"]
    assert "second q" in calls[1]["prompt"]
    saved = chat_store.get(conv["id"])
    assert saved["claude_session_id"] == "sess-2"
    assert saved["messages"][-1]["text"] == "recovered"


def test_build_attachment_prompt_references_paths():
    from ghostbrain.api.repo.chat import build_attachment_prompt

    prompt = build_attachment_prompt(
        "summarize these",
        ["20-contexts/chat-attachments/a.md", "20-contexts/chat-attachments/b.md"],
    )
    assert "[[20-contexts/chat-attachments/a.md]]" in prompt
    assert "[[20-contexts/chat-attachments/b.md]]" in prompt
    assert "poltergeist_get_note" in prompt
    assert prompt.endswith("summarize these")


def test_build_attachment_prompt_no_paths_returns_text_unchanged():
    from ghostbrain.api.repo.chat import build_attachment_prompt

    assert build_attachment_prompt("hi", []) == "hi"
    assert build_attachment_prompt("hi", None) == "hi"
