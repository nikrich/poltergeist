# tests/test_doc_library_ai_summary.py
"""Background AI summary (spec §5): explicit budget, 12k cap, skips, failure isolation, races."""
from pathlib import Path

import pytest

from ghostbrain.api.repo.doc_library import ai_summary, index, notes, ops
from tests.doc_library_helpers import lib_vault  # noqa: F401

REAL_ENQUEUE = ai_summary.enqueue  # captured before any fixture patches it


class _Result:
    def __init__(self, text):
        self.text = text


@pytest.fixture
def calls(monkeypatch):
    seen: list[dict] = []

    def fake_run(prompt, **kw):
        seen.append({"prompt": prompt, **kw})
        return _Result("  It defines the v2 payments API.  ")

    monkeypatch.setattr(ai_summary.llm_client, "run", fake_run)
    monkeypatch.setattr(ai_summary, "enqueue", lambda doc_id: False)  # uploads must not start real jobs
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda *a: "body " * 5000)
    return seen


def _upload(name="a.pdf", content=b"%PDF"):
    return ops.upload("work", None, "", name, "", content)


def test_run_now_writes_summary_with_explicit_budget_and_cap(lib_vault: Path, calls):
    s = _upload()
    assert ai_summary.run_now(s["doc_id"]) is True
    front, body = notes.read_note(lib_vault / s["note_path"])
    assert front["summary"] == "It defines the v2 payments API."
    assert front["index_status"] == "ok"
    call = calls[0]
    assert call["budget_usd"] == ai_summary.SUMMARY_BUDGET_USD == 1.00
    assert call["model"] == "fast"
    assert len(call["prompt"]) < ai_summary.MAX_INPUT_CHARS + 2000  # body capped at 12k + instructions
    assert index.summary(index.get(s["doc_id"]))["summary_state"] == "done"


@pytest.mark.parametrize("front,body,expected", [
    ({"kind": "opaque", "index_status": "ok"}, "x", False),
    ({"kind": "pdf", "index_status": "ok"}, "   \n", False),
    ({"kind": "pdf", "index_status": "failed"}, "text", False),
    ({"kind": "pdf", "index_status": "pending"}, "text", False),
    ({"kind": "pdf", "index_status": "ok"}, "text", True),
])
def test_should_summarise(front, body, expected):
    assert ai_summary.should_summarise(front, body) is expected


def test_llm_failure_leaves_no_summary_and_index_status(lib_vault: Path, calls, monkeypatch):
    s = _upload()
    def boom(*a, **k):
        raise RuntimeError("provider not configured")
    monkeypatch.setattr(ai_summary.llm_client, "run", boom)
    assert ai_summary.run_now(s["doc_id"]) is False
    front, _ = notes.read_note(lib_vault / s["note_path"])
    assert "summary" not in front and front["index_status"] == "ok"
    assert not ai_summary.is_summarising(s["doc_id"])
    assert index.summary(index.get(s["doc_id"]))["summary_state"] == "none"


def test_empty_llm_answer_writes_nothing(lib_vault: Path, calls, monkeypatch):
    s = _upload()
    monkeypatch.setattr(ai_summary.llm_client, "run", lambda *a, **k: _Result("   "))
    assert ai_summary.run_now(s["doc_id"]) is False
    assert "summary" not in notes.read_note(lib_vault / s["note_path"])[0]


def test_summary_lands_at_current_location_after_move_during_llm(lib_vault: Path, calls, monkeypatch):
    s = _upload()

    def run_and_move(prompt, **kw):
        ops.move(s["doc_id"], "work", "payments", "moved")
        return _Result("Moved doc summary.")

    monkeypatch.setattr(ai_summary.llm_client, "run", run_and_move)
    assert ai_summary.run_now(s["doc_id"]) is True
    e = index.get(s["doc_id"])
    assert e.project == "payments" and e.front["summary"] == "Moved doc summary."
    assert not (lib_vault / s["note_path"]).exists()  # nothing recreated at the old path


def test_skipped_and_deleted_docs_do_not_call_llm(lib_vault: Path, calls, monkeypatch):
    z = ops.upload("work", None, "", "bundle.zip", "application/zip", b"PK")
    assert ai_summary.run_now(z["doc_id"]) is False
    assert ai_summary.run_now("ffffffffffff") is False  # unknown doc
    assert calls == []


def test_enqueue_dedupes_in_flight(lib_vault: Path, calls, monkeypatch):
    # Restore the real enqueue (fixtures stub it) but never run jobs: fake executor.
    # Don't use monkeypatch.undo() — it would also undo lib_vault's VAULT_PATH patch.
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda *a: "text")
    submitted = []

    class FakeExecutor:
        def submit(self, fn, *args):
            submitted.append(args)

    monkeypatch.setattr(ai_summary, "_executor", FakeExecutor())
    monkeypatch.setattr(ai_summary, "enqueue", REAL_ENQUEUE)
    s = ops.upload("work", None, "", "b.pdf", "", b"%PDF-b")  # upload enqueues once
    try:
        assert REAL_ENQUEUE(s["doc_id"]) is False  # already queued
        assert len(submitted) == 1
        assert ai_summary.is_summarising(s["doc_id"])
        assert index.summary(index.get(s["doc_id"]))["summary_state"] == "pending"
    finally:
        ai_summary._inflight.discard(s["doc_id"])  # the fake executor never runs the job
