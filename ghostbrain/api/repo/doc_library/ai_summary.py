# ghostbrain/api/repo/doc_library/ai_summary.py
"""Background AI summaries for library docs (spec §5).

One job at a time on a single worker. A summary is written into the companion
note's frontmatter as ``summary:``. Failures are logged and leave no summary;
``index_status`` is never touched.
"""
from __future__ import annotations

import logging
import queue
import threading

from ghostbrain.api.repo.doc_library import index, notes
from ghostbrain.api.repo.doc_library.errors import LibraryError
from ghostbrain.llm import client as llm_client

log = logging.getLogger("ghostbrain.doc_library.summary")

SUMMARY_BUDGET_USD = 1.00  # explicit: never the client's $0.50 default
MAX_INPUT_CHARS = 12_000
SUMMARY_TIER = "fast"
SUMMARY_TIMEOUT_S = 120

SYSTEM_PROMPT = (
    "You summarise documents for a personal knowledge base. Reply with a plain "
    "2-3 sentence factual summary of what the document is and its key points. "
    "No preamble, no markdown, no speculation."
)

MAX_SUMMARY_CHARS = 800

_lock = threading.Lock()
_inflight: set[str] = set()
_queue: "queue.Queue[str]" = queue.Queue()
_worker: threading.Thread | None = None


def _worker_loop() -> None:
    while True:
        _run_queued(_queue.get())


def _submit(doc_id: str) -> None:
    """Put a job on the queue, lazily starting the single daemon worker."""
    global _worker
    with _lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_worker_loop, name="doc-summary", daemon=True)
            _worker.start()
    _queue.put(doc_id)


def _cap(text: str) -> str:
    if len(text) <= MAX_SUMMARY_CHARS:
        return text
    cut = text[:MAX_SUMMARY_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:.")
    return (cut or text[:MAX_SUMMARY_CHARS]) + "…"


def is_summarising(doc_id: str) -> bool:
    with _lock:
        return doc_id in _inflight


def should_summarise(front: dict, body: str) -> bool:
    if str(front.get("kind") or "") == "opaque":
        return False
    if str(front.get("index_status") or "ok") != "ok":
        return False
    return bool(body.strip())


def _prompt(title: str, body: str) -> str:
    label = "Document (truncated)" if len(body) > MAX_INPUT_CHARS else "Document"
    return f"Title: {title}\n\n{label}:\n{body[:MAX_INPUT_CHARS]}"


def _generate(doc_id: str) -> bool:
    try:
        e = index.get(doc_id)
    except LibraryError:
        return False
    if not should_summarise(e.front, e.body):
        return False
    try:
        result = llm_client.run(
            _prompt(str(e.front.get("title") or e.original.stem), e.body),
            model=SUMMARY_TIER,
            system_prompt=SYSTEM_PROMPT,
            budget_usd=SUMMARY_BUDGET_USD,
            timeout_s=SUMMARY_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001 — a summary is best-effort
        log.warning("summary failed for %s: %s", doc_id, exc)
        return False
    text = _cap(" ".join((result.text or "").split()))
    if not text:
        return False
    index.invalidate()  # the cache may predate a move/delete/reindex during the LLM call
    try:
        current = index.get(doc_id)
    except LibraryError:
        return False
    if not current.note.exists():  # deleted meanwhile: never resurrect the note
        return False
    if not should_summarise(current.front, current.body):
        return False
    if current.body[:MAX_INPUT_CHARS] != e.body[:MAX_INPUT_CHARS]:  # content changed under us
        return False
    notes.write_atomic(current.note, notes.render({**current.front, "summary": text}, current.body))
    index.invalidate()
    return True


def run_now(doc_id: str) -> bool:
    """Summarise synchronously. Never raises. Returns True if a summary was written."""
    with _lock:
        if doc_id in _inflight:
            return False
        _inflight.add(doc_id)
    try:
        return _generate(doc_id)
    except Exception:  # noqa: BLE001
        log.exception("summary crashed for %s", doc_id)
        return False
    finally:
        with _lock:
            _inflight.discard(doc_id)


def _run_queued(doc_id: str) -> None:
    try:
        _generate(doc_id)
    except Exception:  # noqa: BLE001
        log.exception("summary crashed for %s", doc_id)
    finally:
        with _lock:
            _inflight.discard(doc_id)


def enqueue(doc_id: str) -> bool:
    """Queue a background summary. False if already queued/running or not summarisable."""
    try:
        e = index.get(doc_id)
    except LibraryError:
        return False
    if not should_summarise(e.front, e.body):
        return False
    with _lock:
        if doc_id in _inflight:
            return False
        _inflight.add(doc_id)
    try:
        _submit(doc_id)
    except Exception:  # noqa: BLE001
        log.exception("could not queue summary for %s", doc_id)
        with _lock:
            _inflight.discard(doc_id)
        return False
    return True
