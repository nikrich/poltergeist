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


def test_not_scheduled_for_done_or_skipped(monkeypatch):
    seen = _router(monkeypatch, RoutingDecision("work", 0.9, "r", "llm"))
    conv = _first_turn()
    chat_store.move(conv["id"], context="personal", project=None, folder=None)
    assert chat_autofile.maybe_schedule(chat_store.get(conv["id"])) is False
    legacy = _first_turn()
    legacy["auto_filed"] = "skipped"
    assert chat_autofile.maybe_schedule(legacy) is False
    done = _first_turn()
    chat_store.apply_auto_file(done["id"], None, None)
    chat_store.append_user_message(done, "more")
    chat_store.append_assistant_message(done, "more reply", [])
    assert chat_autofile.maybe_schedule(chat_store.get(done["id"])) is False
    assert "event" not in seen


def test_interrupted_first_reply_then_full_reply_files(monkeypatch):
    seen = _router(monkeypatch, RoutingDecision("work", 0.9, "r", "llm", project="atlas"))
    conv = chat_store.create()
    chat_store.append_user_message(conv, "how do we deploy atlas?")
    chat_store.append_assistant_message(conv, "partial garbage", [], interrupted=True)
    assert chat_autofile.maybe_schedule(chat_store.get(conv["id"])) is False
    chat_store.append_user_message(conv, "try again")
    chat_store.append_assistant_message(conv, "atlas deploys via ...", [])
    assert chat_autofile.maybe_schedule(chat_store.get(conv["id"])) is True
    disk = chat_store.get(conv["id"])
    assert (disk["project"], disk["auto_filed"]) == ("atlas", "done")
    assert "partial garbage" not in seen["excerpt"] and "atlas deploys" in seen["excerpt"]
    assert "how do we deploy atlas?" in seen["excerpt"]
    assert seen["event"]["id"] == conv["id"]


def test_pending_chat_with_two_full_replies_is_scheduled(monkeypatch):
    _router(monkeypatch, RoutingDecision("work", 0.9, "r", "llm", project="atlas"))
    conv = _first_turn()  # routing never landed (e.g. restart)
    chat_store.append_user_message(conv, "more")
    chat_store.append_assistant_message(conv, "more reply", [])
    assert chat_autofile.maybe_schedule(chat_store.get(conv["id"])) is True
    assert chat_store.get(conv["id"])["auto_filed"] == "done"


def test_unexpected_failure_in_thread_is_logged(monkeypatch, caplog):
    _router(monkeypatch, RoutingDecision("work", 0.9, "r", "llm"))

    def boom(*a, **k):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(chat_store, "apply_auto_file", boom)
    conv = _first_turn()
    with caplog.at_level("ERROR", logger="ghostbrain.chat.autofile"):
        chat_autofile.run(conv["id"])
    assert any("auto-file thread failed" in r.message and r.exc_info for r in caplog.records)


def test_manual_move_during_routing_wins(monkeypatch):
    conv = _first_turn()

    def slow(event, *, content_excerpt=None, **_):
        chat_store.move(conv["id"], context="personal", project=None, folder=None)
        return RoutingDecision("work", 0.9, "r", "llm", project="atlas")

    monkeypatch.setattr(chat_autofile, "_route", slow)
    chat_autofile.maybe_schedule(conv)
    assert chat_store.get(conv["id"])["context"] == "personal"
