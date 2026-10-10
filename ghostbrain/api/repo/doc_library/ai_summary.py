# ghostbrain/api/repo/doc_library/ai_summary.py
"""Background AI summaries for library docs (spec §5).

One job at a time on a single worker. A summary is written into the companion
note's frontmatter as ``summary:``. Failures are logged and leave no summary;
``index_status`` is never touched.
"""
from __future__ import annotations

import logging
import threading
from concurrent.futures import ThreadPoolExecutor

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

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="doc-summary")
_lock = threading.Lock()
_inflight: set[str] = set()


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
    return f"Title: {title}\n\nDocument (truncated):\n{body[:MAX_INPUT_CHARS]}"


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
    text = " ".join((result.text or "").split())
    if not text:
        return False
    try:
        current = index.get(doc_id)  # re-read: the doc may have moved or changed meanwhile
    except LibraryError:
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
    _executor.submit(_run_queued, doc_id)
    return True
