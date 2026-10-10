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

    monkeypatch.setattr(ai_summary, "_submit", lambda doc_id: submitted.append(doc_id))
    monkeypatch.setattr(ai_summary, "enqueue", REAL_ENQUEUE)
    s = ops.upload("work", None, "", "b.pdf", "", b"%PDF-b")  # upload enqueues once
    try:
        assert REAL_ENQUEUE(s["doc_id"]) is False  # already queued
        assert len(submitted) == 1
        assert ai_summary.is_summarising(s["doc_id"])
        assert index.summary(index.get(s["doc_id"]))["summary_state"] == "pending"
    finally:
        ai_summary._inflight.discard(s["doc_id"])  # the fake _submit never runs the job


def test_delete_during_llm_does_not_resurrect_note(lib_vault: Path, calls, monkeypatch):
    s = _upload()
    monkeypatch.setattr(ops, "send2trash", lambda p: Path(p).unlink())

    def run_and_delete(prompt, **kw):
        ops.delete(s["doc_id"])
        return _Result("Late summary.")

    monkeypatch.setattr(ai_summary.llm_client, "run", run_and_delete)
    assert ai_summary.run_now(s["doc_id"]) is False
    assert not (lib_vault / s["note_path"]).exists()


def test_body_changed_during_llm_skips_write(lib_vault: Path, calls, monkeypatch):
    s = _upload()

    def run_and_rewrite(prompt, **kw):
        front, _ = notes.read_note(lib_vault / s["note_path"])
        notes.write_atomic(lib_vault / s["note_path"], notes.render(front, "completely different"))
        return _Result("Stale summary.")

    monkeypatch.setattr(ai_summary.llm_client, "run", run_and_rewrite)
    assert ai_summary.run_now(s["doc_id"]) is False
    assert "summary" not in notes.read_note(lib_vault / s["note_path"])[0]


def test_status_changed_during_llm_skips_write(lib_vault: Path, calls, monkeypatch):
    s = _upload()

    def run_and_fail_status(prompt, **kw):
        front, body = notes.read_note(lib_vault / s["note_path"])
        notes.write_atomic(lib_vault / s["note_path"], notes.render({**front, "index_status": "failed"}, body))
        return _Result("Stale summary.")

    monkeypatch.setattr(ai_summary.llm_client, "run", run_and_fail_status)
    assert ai_summary.run_now(s["doc_id"]) is False


def test_worker_thread_is_daemon(lib_vault: Path, calls):
    ai_summary._submit("ffffffffffff")  # unknown doc: the job no-ops
    assert ai_summary._worker is not None and ai_summary._worker.daemon


def test_enqueue_submit_failure_does_not_leak_inflight(lib_vault: Path, calls, monkeypatch):
    s = _upload()

    def boom(doc_id):
        raise RuntimeError("queue broken")

    monkeypatch.setattr(ai_summary, "_submit", boom)
    assert REAL_ENQUEUE(s["doc_id"]) is False
    assert not ai_summary.is_summarising(s["doc_id"])


def test_summary_is_capped_at_word_boundary(lib_vault: Path, calls, monkeypatch):
    s = _upload()
    monkeypatch.setattr(ai_summary.llm_client, "run", lambda *a, **k: _Result("word " * 400))
    assert ai_summary.run_now(s["doc_id"]) is True
    got = notes.read_note(lib_vault / s["note_path"])[0]["summary"]
    assert len(got) <= ai_summary.MAX_SUMMARY_CHARS + 1 and got.endswith("word…")


def _wait_idle(doc_id, timeout=5.0):
    import time

    end = time.time() + timeout
    while ai_summary.is_summarising(doc_id) and time.time() < end:
        time.sleep(0.01)
    assert not ai_summary.is_summarising(doc_id), "worker did not finish"


def test_real_enqueue_worker_writes_summary(lib_vault: Path, calls):
    s = _upload()  # llm_client.run stays mocked (calls fixture) for the whole test
    assert REAL_ENQUEUE(s["doc_id"]) is True
    _wait_idle(s["doc_id"])
    assert notes.read_note(lib_vault / s["note_path"])[0]["summary"] == "It defines the v2 payments API."
    assert len(calls) == 1


def test_real_enqueue_worker_llm_failure_clears_inflight(lib_vault: Path, calls, monkeypatch):
    s = _upload()

    def boom(*a, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(ai_summary.llm_client, "run", boom)
    assert REAL_ENQUEUE(s["doc_id"]) is True
    _wait_idle(s["doc_id"])
    assert "summary" not in notes.read_note(lib_vault / s["note_path"])[0]


@pytest.fixture
def real_enqueue_spy(lib_vault: Path, calls, monkeypatch):
    submitted: list[str] = []
    monkeypatch.setattr(ai_summary, "_submit", lambda doc_id: submitted.append(doc_id))
    monkeypatch.setattr(ai_summary, "enqueue", REAL_ENQUEUE)
    yield submitted
    for d in submitted:
        ai_summary._inflight.discard(d)  # the recording _submit never runs the job


def test_normal_upload_submits_exactly_once(real_enqueue_spy):
    ops.upload("work", None, "", "n.pdf", "", b"%PDF-n")
    assert len(real_enqueue_spy) == 1


def test_duplicate_upload_does_not_resubmit(real_enqueue_spy):
    ops.upload("work", None, "", "n.pdf", "", b"%PDF-n")
    ops.upload("work", None, "", "n2.pdf", "", b"%PDF-n")
    assert len(real_enqueue_spy) == 1


def test_opaque_upload_submits_nothing(real_enqueue_spy):
    ops.upload("work", None, "", "bundle.zip", "application/zip", b"PK")
    assert real_enqueue_spy == []


def test_failed_extraction_submits_nothing(real_enqueue_spy, monkeypatch):
    def boom(*a):
        raise RuntimeError("corrupt")

    monkeypatch.setattr(ops.attachment_extract, "extract_text", boom)
    ops.upload("work", None, "", "bad.pdf", "", b"%PDF-bad")
    assert real_enqueue_spy == []


def test_enqueue_raising_does_not_fail_upload(lib_vault: Path, calls, monkeypatch):
    def boom(doc_id):
        raise RuntimeError("enqueue bug")

    monkeypatch.setattr(ai_summary, "enqueue", boom)
    s = _upload()
    assert s["index_status"] == "ok" and s["duplicate"] is False
    assert ops.reindex(s["doc_id"])["index_status"] == "ok"  # reindex is protected too


def test_reindex_drops_stale_summary_when_body_changes(lib_vault: Path, calls, monkeypatch):
    s = _upload()
    assert ai_summary.run_now(s["doc_id"]) is True
    path = lib_vault / s["note_path"]
    assert "summary" in notes.read_note(path)[0]
    ops.reindex(s["doc_id"])  # same extracted body: summary kept
    assert "summary" in notes.read_note(path)[0]
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda *a: "new content")
    ops.reindex(s["doc_id"])
    assert "summary" not in notes.read_note(path)[0]


def test_reindex_drops_summary_when_status_not_ok(lib_vault: Path, calls, monkeypatch):
    s = _upload()
    assert ai_summary.run_now(s["doc_id"]) is True

    def boom(*a):
        raise RuntimeError("corrupt")

    monkeypatch.setattr(ops.attachment_extract, "extract_text", boom)
    ops.reindex(s["doc_id"])
    front = notes.read_note(lib_vault / s["note_path"])[0]
    assert front["index_status"] == "failed" and "summary" not in front


def test_prompt_label_truncated_only_when_over_cap():
    short = ai_summary._prompt("t", "x" * 10)
    long = ai_summary._prompt("t", "x" * (ai_summary.MAX_INPUT_CHARS + 1))
    assert "Document:" in short and "truncated" not in short
    assert "Document (truncated):" in long
