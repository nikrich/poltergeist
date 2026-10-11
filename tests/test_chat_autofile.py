import pytest

from ghostbrain.api.repo import chat_autofile, chat_store
from ghostbrain.worker.router import RoutingDecision


@pytest.fixture(autouse=True)
def chats(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_CHATS_DIR", str(tmp_path / "chats"))
    monkeypatch.setattr(chat_autofile, "_spawn", lambda fn, *a: fn(*a))
    monkeypatch.setattr(chat_autofile, "_reject_below", lambda: 0.5)


def _first_turn():
    conv = chat_store.create()
    chat_store.append_user_message(conv, "how do we deploy atlas?")
    chat_store.append_assistant_message(conv, "atlas deploys via ...", [])
    return conv


def _router(monkeypatch, decision=None, exc=None):
    seen = {}

    def fake(event, *, content_excerpt=None, **_):
        seen["event"], seen["excerpt"] = event, content_excerpt
        if exc:
            raise exc
        return decision

    monkeypatch.setattr(chat_autofile, "_route", fake)
    return seen


def test_files_after_first_reply(monkeypatch):
    seen = _router(monkeypatch, RoutingDecision("work", 0.9, "r", "llm", project="atlas"))
    conv = _first_turn()
    assert chat_autofile.maybe_schedule(conv) is True
    disk = chat_store.get(conv["id"])
    assert (disk["context"], disk["project"], disk["auto_filed"]) == ("work", "atlas", "done")
    assert seen["event"]["source"] == "chat"
    assert "how do we deploy atlas?" in seen["excerpt"] and "atlas deploys" in seen["excerpt"]


def test_excerpt_is_capped(monkeypatch):
    seen = _router(monkeypatch, RoutingDecision("work", 0.9, "r", "llm"))
    conv = chat_store.create()
    chat_store.append_user_message(conv, "x" * 10_000)
    chat_store.append_assistant_message(conv, "y" * 10_000, [])
    chat_autofile.maybe_schedule(conv)
    assert len(seen["excerpt"]) <= chat_autofile.EXCERPT_CAP


@pytest.mark.parametrize("decision", [
    RoutingDecision("needs_review", 0.9, "r", "llm"),
    RoutingDecision("work", 0.3, "r", "llm"),
    RoutingDecision("needs_review", 0.0, "err", "fallback"),
])
def test_unsure_leaves_unfiled_but_done(monkeypatch, decision):
    _router(monkeypatch, decision)
    conv = _first_turn()
    chat_autofile.maybe_schedule(conv)
    disk = chat_store.get(conv["id"])
    assert disk["context"] is None and disk["auto_filed"] == "done"


def test_router_exception_leaves_unfiled_but_done(monkeypatch):
    _router(monkeypatch, exc=RuntimeError("boom"))
    conv = _first_turn()
    chat_autofile.maybe_schedule(conv)
    disk = chat_store.get(conv["id"])
    assert disk["context"] is None and disk["auto_filed"] == "done"


def test_not_scheduled_for_skipped_or_later_turns(monkeypatch):
    seen = _router(monkeypatch, RoutingDecision("work", 0.9, "r", "llm"))
    conv = _first_turn()
    chat_store.move(conv["id"], context="personal", project=None, folder=None)
    assert chat_autofile.maybe_schedule(chat_store.get(conv["id"])) is False
    legacy = _first_turn()
    legacy["auto_filed"] = "skipped"
    assert chat_autofile.maybe_schedule(legacy) is False
    two = _first_turn()
    chat_store.append_user_message(two, "more")
    chat_store.append_assistant_message(two, "more reply", [])
    assert chat_autofile.maybe_schedule(two) is False
    assert "event" not in seen


def test_manual_move_during_routing_wins(monkeypatch):
    conv = _first_turn()

    def slow(event, *, content_excerpt=None, **_):
        chat_store.move(conv["id"], context="personal", project=None, folder=None)
        return RoutingDecision("work", 0.9, "r", "llm", project="atlas")

    monkeypatch.setattr(chat_autofile, "_route", slow)
    chat_autofile.maybe_schedule(conv)
    assert chat_store.get(conv["id"])["context"] == "personal"
