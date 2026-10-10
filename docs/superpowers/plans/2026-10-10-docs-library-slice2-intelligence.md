# Docs Library — Slice 2 (Intelligence) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every library doc gets a short AI summary ("✦ what poltergeist knows") generated in the background, retryable from the inspector, plus an "ask about this doc" box that opens a chat grounded on the doc.

**Architecture:** A new backend module `doc_library/ai_summary.py` runs one summary at a time on a single-worker background executor. It calls the configured LLM provider (`ghostbrain.llm.client.run` → `get_provider()`) with an explicit budget and writes `summary:` into the companion note's frontmatter. An in-process "summarising" set drives a new `summary_state` field (`pending | done | none`) in every DocSummary. Uploads, adopts and reindexes enqueue a summary once indexing succeeds, and `POST /v1/library/docs/{id}/summarise` re-runs it. In the renderer, the inspector shows the summary card (text, a "summarising…" shimmer, or a "summarise" button) and polls the tree while anything is pending. "Ask about this doc" creates a conversation and queues the question, with the companion note as an attachment, in the chat store. Then it switches to the Chat screen, which sends the queued question on mount.

**Tech Stack:** Python 3.11 / FastAPI / concurrent.futures. Electron / React 18 / TanStack Query / zustand / Vitest + RTL.

**Spec:** `docs/superpowers/specs/2026-10-09-docs-library-design.md` — this slice = §5 (summary, ask) plus the AI parts of the §6 inspector.

## Global Constraints

- Summary input: the first **12,000 characters** of the companion-note body. Prompt asks for a **2–3 sentence factual summary**.
- **Explicit budget** on every summary call: `SUMMARY_BUDGET_USD = 1.00`. Never rely on the client's `DEFAULT_BUDGET_USD = 0.50`. Tier `fast`, timeout 120 s.
- The result goes into frontmatter key `summary:`. A failure is logged, leaves no summary, and **never changes `index_status`**.
- **Skipped (no LLM call):** `kind: opaque`, empty or whitespace-only bodies, and `index_status` other than `ok`.
- The LLM provider is whatever the user configured (`get_provider()`). No new provider code.
- "Ask about this doc" sends the question with the **companion note's vault-relative path** as an attachment (existing `gb:chat:send` `attachmentPaths`), then switches to the Chat screen.
- UI copy is lowercase in titles and labels (`✦ what poltergeist knows`, `summarising…`, `summarise`, `ask about this doc…`).
- Python tests: temp vault via `VAULT_PATH` and sandboxed `GHOSTBRAIN_STATE_DIR` (use the existing `lib_vault` fixture). LLM calls are always mocked; tests never run the background executor for real (use `ai_summary.run_now`).
- New test files must be added to the backend test list in `.github/workflows/ci.yml`.
- Desktop: `npm run typecheck` (tsc -b), `npm run lint` (`--max-warnings 0`), and vitest output must be pristine. Node 25 shadows jsdom's `localStorage`, so stub it with `vi.stubGlobal` where needed. CI runs Node 20.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
- Never use real context names in docs or examples (`tests/test_no_hardcoded_contexts.py` guards `docs/`). Use `work` / `personal`.

## Review Focus

1. **A doc is moved or renamed while its summary is being generated.** Expect: the summary lands in the note at its current location, and nothing is written back to the old path. Pinned in Task 1.
2. **The same doc is summarised twice concurrently**, e.g. by a double-click on "summarise" or a reindex during an upload's summary. Expect: at most one job per doc in flight; the second request is a no-op. Pinned in Task 1.
3. **The LLM provider isn't configured or is unreachable.** Expect: no crash and no stuck "summarising…". The state returns to `none` and the inspector offers "summarise" again. Pinned in Task 1 and Task 3.
4. **A huge doc** (a 300-page PDF). Expect: only the first 12,000 characters are sent, and the budget stays explicit. Pinned in Task 1.
5. **"Ask" while a chat turn is already streaming in another conversation.** Expect: the question goes to the NEW conversation and is not dropped; the queued ask is consumed exactly once. Pinned in Task 4.

---

## File structure

**Backend**
- Create `ghostbrain/api/repo/doc_library/ai_summary.py`. It holds the job state, `run_now`, `enqueue`, and the frontmatter write.
- Modify `ghostbrain/api/repo/doc_library/index.py`. `summary()` gains the `summary` and `summary_state` keys.
- Modify `ghostbrain/api/repo/doc_library/ops.py`. Successful upload, adopt and reindex enqueue a summary.
- Modify `ghostbrain/api/models/library.py`. `DocSummary` gains `summary: str | None` and `summary_state: str`.
- Modify `ghostbrain/api/routes/library.py`. Add `POST /docs/{doc_id}/summarise`.
- Create tests: `tests/test_doc_library_ai_summary.py`; extend `tests/test_library_routes.py`.
- Modify `.github/workflows/ci.yml` (the new test file).

**Desktop**
- Modify `desktop/src/shared/api-types.ts`. `DocSummary` gains `summary` and `summary_state`.
- Modify `desktop/src/renderer/lib/api/hooks.ts`. Add `useSummariseDoc`, and make `useLibraryTree` poll while any doc is pending.
- Modify `desktop/src/renderer/components/docs/DocInspector.tsx`. Add the summary card and the ask box.
- Modify `desktop/src/renderer/stores/chat.ts`. Add `pendingAsk`, `queueAsk` and `takeAsk`.
- Modify `desktop/src/renderer/screens/chat.tsx`. Consume `pendingAsk` once the conversation is active.
- Modify `desktop/src/renderer/screens/docs.tsx`. Wire the summarise and ask handlers.
- Tests: extend `DocInspector.test.tsx`, `DocsScreen.test.tsx` and `chat-store.test.ts`. Add `ChatScreen` pending-ask coverage to `ChatScreen.test.tsx`.

---

### Task 1: Background summary job

**Files:**
- Create: `ghostbrain/api/repo/doc_library/ai_summary.py`
- Modify: `ghostbrain/api/repo/doc_library/index.py` (`summary()` around line 220)
- Test: `tests/test_doc_library_ai_summary.py`

**Interfaces:**
- Consumes:
  - `index.get(doc_id) -> DocEntry` (fields: doc_id, note, original, front, body, context, project, folder)
  - `index.invalidate()`
  - `notes.render(front, body)`
  - `notes.write_atomic(path, text)` (it already notifies the link index)
  - `ghostbrain.llm.client.run(prompt, *, model, budget_usd, timeout_s, system_prompt) -> LLMResult` (`.text`)
- Produces:
  - `ai_summary.SUMMARY_BUDGET_USD = 1.00`
  - `ai_summary.MAX_INPUT_CHARS = 12_000`
  - `ai_summary.is_summarising(doc_id: str) -> bool`
  - `ai_summary.should_summarise(front: dict, body: str) -> bool`
  - `ai_summary.run_now(doc_id: str) -> bool`: runs synchronously. Returns True if a summary was written. Never raises.
  - `ai_summary.enqueue(doc_id: str) -> bool`: returns False if the doc is already queued or running, or should be skipped.
  - `index.summary(e)` gains `"summary": str | None` and `"summary_state": "pending" | "done" | "none"`.

- [ ] **Step 1: Write the failing tests**

```python
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
```

(The last test exercises Task 2's upload wiring. It is expected to fail on `len(submitted) == 1` until Task 2 lands; the Step 4 command for this task deselects it with `-k "not enqueue_dedupes"`, and Task 2 runs it.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --extra api pytest tests/test_doc_library_ai_summary.py -q`
Expected: FAIL with `ImportError: cannot import name 'ai_summary'`

- [ ] **Step 3: Implement `ai_summary.py`**

```python
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
```

- [ ] **Step 4: Add `summary` and `summary_state` to `index.summary()`**

In `ghostbrain/api/repo/doc_library/index.py`, inside `summary(e)`, add these two keys to the returned dict. Use a function-level import to avoid an import cycle, since `ai_summary` imports `index`:

```python
    from ghostbrain.api.repo.doc_library import ai_summary  # noqa: PLC0415

    raw = e.front.get("summary")
    text = str(raw).strip() if isinstance(raw, str) and raw.strip() else None
    state = "pending" if ai_summary.is_summarising(e.doc_id) else ("done" if text else "none")
```

…and include `"summary": text, "summary_state": state` in the dict.

Run: `uv run --extra dev --extra api pytest tests/test_doc_library_ai_summary.py -q -k "not enqueue_dedupes" && uv run --extra dev --extra api pytest tests/test_doc_library_*.py -q`
Expected: PASS (all existing library tests stay green).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/doc_library/ai_summary.py ghostbrain/api/repo/doc_library/index.py tests/test_doc_library_ai_summary.py
git commit -m "feat(library): background AI summary job with explicit budget and race-safe write

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Trigger summaries + API

**Files:**
- Modify: `ghostbrain/api/repo/doc_library/ops.py` (`upload`, `adopt`, `reindex`)
- Modify: `ghostbrain/api/models/library.py` (`DocSummary`)
- Modify: `ghostbrain/api/routes/library.py` (new route)
- Modify: `.github/workflows/ci.yml` (add `tests/test_doc_library_ai_summary.py`; `test_doc_library_*.py` is already globbed, so check whether the glob already covers it and only add it if not)
- Test: `tests/test_doc_library_ai_summary.py` (the `enqueue_dedupes` test) and `tests/test_library_routes.py`

**Interfaces:**
- Consumes: `ai_summary.enqueue`, `ai_summary.is_summarising`.
- Produces:
  - `POST /v1/library/docs/{doc_id}/summarise` returns `{"queued": bool}`. It is 404 for an unknown doc, and returns `queued: false` when the doc is skipped or already running.
  - The `DocSummary` API model gains `summary: str | None = None` and `summary_state: Literal["pending","done","none"] = "none"`.
  - Upload, adopt and reindex call `ai_summary.enqueue(doc_id)` after indexing finishes with `index_status: ok`.

- [ ] **Step 1: Write the failing route test**

Append to `tests/test_library_routes.py`:

```python
def test_summarise_route(client, monkeypatch):
    from ghostbrain.api.repo.doc_library import ai_summary

    queued = []
    monkeypatch.setattr(ai_summary, "enqueue", lambda doc_id: queued.append(doc_id) or True)
    doc = _up(client).json()
    assert "summary" in doc and doc["summary_state"] in ("none", "pending")
    r = client.post(f"/v1/library/docs/{doc['doc_id']}/summarise", headers=H)
    assert r.status_code == 200 and r.json() == {"queued": True}
    assert queued[-1] == doc["doc_id"]
    assert client.post("/v1/library/docs/ffffffffffff/summarise", headers=H).status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run --extra dev --extra api pytest tests/test_library_routes.py -q -k summarise && uv run --extra dev --extra api pytest tests/test_doc_library_ai_summary.py -q -k enqueue_dedupes`
Expected: both FAIL. The route gives a 404 or 405. Without upload wiring, `submitted` is empty.

- [ ] **Step 3: Implement**

- In `ops.py`, add `from ghostbrain.api.repo.doc_library import ai_summary` at module top. If that creates an import cycle, use a function-level import, because `ai_summary` imports `index` and `notes`, not `ops`. Then:
  - In `upload`: after `_finish_index(doc_id)` returns its summary dict `s`, add `if s.get("index_status") == "ok": ai_summary.enqueue(doc_id)` before returning, then recompute `s = index.summary(index.get(doc_id))` so the response shows `summary_state: "pending"`. Keep the `"duplicate": False` key in the returned dict.
  - In `adopt`: the same after its `_finish_index`.
  - In `reindex`: after writing the note, `if status == "ok": ai_summary.enqueue(doc_id)`.
- In `ghostbrain/api/models/library.py`, add to `DocSummary`:

```python
    summary: str | None = None
    summary_state: Literal["pending", "done", "none"] = "none"
```

- In `ghostbrain/api/routes/library.py`:

```python
@router.post("/docs/{doc_id}/summarise")
def summarise_doc(doc_id: str) -> dict:
    _run(index.get, doc_id)  # 404 for unknown docs
    return {"queued": ai_summary.enqueue(doc_id)}
```

  Add `ai_summary` to the `from ghostbrain.api.repo.doc_library import ...` line.
- Every existing library test that uploads must not start a real background job. In `tests/doc_library_helpers.py`'s `lib_vault` fixture, add `monkeypatch.setattr("ghostbrain.api.repo.doc_library.ai_summary.enqueue", lambda doc_id: False)`. The `enqueue_dedupes` test sets it back to `REAL_ENQUEUE` (captured at import) and uses a fake executor.

- [ ] **Step 4: Run the tests**

Run: `uv run --extra dev --extra api pytest tests/test_doc_library_*.py tests/test_library_routes.py tests/test_file_kinds.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/doc_library/ops.py ghostbrain/api/models/library.py ghostbrain/api/routes/library.py tests/doc_library_helpers.py tests/test_library_routes.py tests/test_doc_library_ai_summary.py .github/workflows/ci.yml
git commit -m "feat(library): enqueue summaries after indexing; POST /docs/{id}/summarise

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Inspector "✦ what poltergeist knows" card

**Files:**
- Modify: `desktop/src/shared/api-types.ts` (`DocSummary`)
- Modify: `desktop/src/renderer/lib/api/hooks.ts` (`useSummariseDoc`, tree polling)
- Modify: `desktop/src/renderer/components/docs/DocInspector.tsx`
- Modify: `desktop/src/renderer/screens/docs.tsx` (pass `onSummarise`)
- Modify: `desktop/src/renderer/__tests__/fixtures/library.ts` (the `doc()` default gains `summary: null, summary_state: 'none'`)
- Test: `desktop/src/renderer/__tests__/DocInspector.test.tsx`

**Interfaces:**
- Consumes: the Task 2 API.
- Produces:
  - `DocSummary.summary: string | null`
  - `DocSummary.summary_state: 'pending' | 'done' | 'none'`
  - `useSummariseDoc()`: a mutation taking `docId`. It POSTs `/v1/library/docs/${docId}/summarise` and invalidates `['library']`.
  - `useLibraryTree()` refetches every 3000 ms while any doc in the tree has `summary_state === 'pending'` or `index_status === 'pending'`, and otherwise does not poll.
  - `DocInspector` gains the prop `onSummarise: () => void`.

- [ ] **Step 1: Write the failing tests**

Add to `DocInspector.test.tsx`. Keep the existing tests, and pass `onSummarise={vi.fn()}` in them.

```tsx
describe('DocInspector summary card', () => {
  const base = { scopeName: 'Payments', onRename: vi.fn(), onReindex: vi.fn() };

  it('shows the summary when done', () => {
    render(<DocInspector {...base} onSummarise={vi.fn()} doc={doc({ summary: 'Defines the v2 API.', summary_state: 'done' })} />);
    expect(screen.getByText('✦ what poltergeist knows')).toBeTruthy();
    expect(screen.getByText('Defines the v2 API.')).toBeTruthy();
  });

  it('shows summarising… while pending', () => {
    render(<DocInspector {...base} onSummarise={vi.fn()} doc={doc({ summary_state: 'pending' })} />);
    expect(screen.getByText('summarising…')).toBeTruthy();
  });

  it('offers summarise when there is none, and not for opaque or failed docs', () => {
    const onSummarise = vi.fn();
    const { rerender } = render(<DocInspector {...base} onSummarise={onSummarise} doc={doc({ summary_state: 'none' })} />);
    fireEvent.click(screen.getByRole('button', { name: 'summarise' }));
    expect(onSummarise).toHaveBeenCalled();
    rerender(<DocInspector {...base} onSummarise={onSummarise} doc={doc({ kind: 'opaque', original: 'a.zip', summary_state: 'none' })} />);
    expect(screen.queryByText('✦ what poltergeist knows')).toBeNull();
    rerender(<DocInspector {...base} onSummarise={onSummarise} doc={doc({ index_status: 'failed', summary_state: 'none' })} />);
    expect(screen.queryByRole('button', { name: 'summarise' })).toBeNull();
  });
});
```

Add a hooks test, `desktop/src/renderer/__tests__/library-hooks.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../lib/api/client', () => ({ get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn() }));

import * as client from '../lib/api/client';
import { useLibraryTree } from '../lib/api/hooks';
import { doc, libraryFixture } from './fixtures/library';

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe('useLibraryTree polling', () => {
  it('polls while a summary is pending and stops when done', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const pending = libraryFixture();
    pending.scopes[1]!.folders[1]!.docs = [doc({ summary_state: 'pending' })];
    const done = libraryFixture();
    vi.mocked(client.get).mockResolvedValueOnce(pending as never).mockResolvedValue(done as never);
    renderHook(() => useLibraryTree(), { wrapper });
    await waitFor(() => expect(client.get).toHaveBeenCalledTimes(1));
    await vi.advanceTimersByTimeAsync(3100);
    await waitFor(() => expect(client.get).toHaveBeenCalledTimes(2));
    await vi.advanceTimersByTimeAsync(6200);
    expect(client.get).toHaveBeenCalledTimes(2);
    vi.useRealTimers();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd desktop && npx vitest run src/renderer/__tests__/DocInspector.test.tsx src/renderer/__tests__/library-hooks.test.tsx`
Expected: FAIL. The card is missing and the tree doesn't poll.

- [ ] **Step 3: Implement**

- `api-types.ts`: add `summary: string | null; summary_state: 'pending' | 'done' | 'none';` to `DocSummary`. Update the fixture `doc()` defaults.
- `hooks.ts`:

```ts
function anyPending(tree: LibraryTree | undefined): boolean {
  if (!tree) return false;
  const walk = (n: { docs: DocSummary[]; folders: DocFolderNode[] }): boolean =>
    n.docs.some((d) => d.summary_state === 'pending' || d.index_status === 'pending') || n.folders.some(walk);
  return tree.scopes.some(walk);
}

export function useLibraryTree() {
  return useQuery({
    queryKey: ['library', 'tree'],
    queryFn: () => get<LibraryTree>('/v1/library/tree'),
    staleTime: 5_000,
    refetchInterval: (q) => (anyPending(q.state.data as LibraryTree | undefined) ? 3_000 : false),
  });
}

export function useSummariseDoc() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => post<{ queued: boolean }>(`/v1/library/docs/${docId}/summarise`),
    onSuccess: () => invalidateLibrary(qc),
  });
}
```

  This replaces the existing `useLibraryTree` body. Keep its key and staleTime.
- `DocInspector.tsx`: add the `onSummarise` prop. Below the metadata `<dl>` and above the failed-index box, render the card. Skip it when `doc.kind === 'opaque'`.

```tsx
      {doc.kind !== 'opaque' && (
        <div className="rounded-[10px] border border-[rgba(197,255,61,.18)] bg-gradient-to-b from-[rgba(197,255,61,.06)] to-transparent p-3 leading-normal text-ink-1">
          <span className="mb-1.5 block font-mono text-10 uppercase tracking-[0.12em] text-neon-ink">✦ what poltergeist knows</span>
          {doc.summary_state === 'pending' ? (
            <span className="animate-pulse text-ink-3">summarising…</span>
          ) : doc.summary ? (
            <p>{doc.summary}</p>
          ) : doc.index_status === 'ok' ? (
            <button type="button" onClick={onSummarise} className="font-mono text-11 text-neon-ink hover:underline">
              summarise
            </button>
          ) : (
            <span className="text-ink-3">needs indexing first</span>
          )}
        </div>
      )}
```

- `docs.tsx`: `const summarise = useSummariseDoc();` and pass `onSummarise={() => run(summarise.mutateAsync(selectedDoc.doc_id))}` to `DocInspector`.

- [ ] **Step 4: Run the tests**

Run: `cd desktop && npx vitest run && npm run typecheck && npm run lint`
Expected: PASS. Output pristine.

- [ ] **Step 5: Commit**

```bash
git add desktop/src
git commit -m "feat(docs): 'what poltergeist knows' summary card with retry and live polling

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Ask about this doc

**Files:**
- Modify: `desktop/src/renderer/stores/chat.ts`
- Modify: `desktop/src/renderer/screens/chat.tsx` (consume the pending ask)
- Modify: `desktop/src/renderer/components/docs/DocInspector.tsx` (ask box)
- Modify: `desktop/src/renderer/screens/docs.tsx` (handler: create conversation → queue → navigate)
- Test: `desktop/src/renderer/__tests__/chat-store.test.ts`, `ChatScreen.test.tsx`, `DocInspector.test.tsx`, `DocsScreen.test.tsx`

**Interfaces:**
- Consumes:
  - `useCreateConversation()`: a mutation POSTing `/v1/chat`, returning `Conversation` with `id`.
  - `useChat` (`setActive`, `beginStream`).
  - `useNavigation().setActive('chat')`.
  - `ChatAttachment = { path, title, kind }` from `shared/api-types`.
- Produces:
  - In `useChat`: `pendingAsk: { convId: string; text: string; attachments: ChatAttachment[] } | null`, `queueAsk(a)`, `takeAsk(convId): PendingAsk | null` (returns and clears only if `convId` matches).
  - `DocInspector` gains the prop `onAsk: (question: string) => void`.

- [ ] **Step 1: Write the failing tests**

`chat-store.test.ts` (append):

```ts
describe('pending ask', () => {
  it('is taken exactly once, only for its conversation', () => {
    const att = { path: '20-contexts/work/docs/a-aaaaaa.md', title: 'A', kind: 'pdf' };
    useChat.getState().queueAsk({ convId: 'c1', text: 'what is this?', attachments: [att] });
    expect(useChat.getState().takeAsk('c2')).toBeNull();
    expect(useChat.getState().takeAsk('c1')).toEqual({ convId: 'c1', text: 'what is this?', attachments: [att] });
    expect(useChat.getState().takeAsk('c1')).toBeNull();
  });
});
```

`ChatScreen.test.tsx` (new test, reusing that file's existing render/mocking helpers): set `useChat.setState({ activeId: 'c1', pendingAsk: { convId: 'c1', text: 'q', attachments: [att] } })`, render `ChatScreen`, and assert `window.gb.chat.send` was called once with `('c1', 'q', [att.path])`. Re-render and assert it is still called only once.

`DocInspector.test.tsx`: typing `what changed?` into the placeholder `ask about this doc…` and pressing Enter calls `onAsk('what changed?')` and clears the input. Enter on an empty input does nothing.

`DocsScreen.test.tsx`: after opening a doc, ask `summarise risks` in the inspector. Assert that `client.post` was called with `'/v1/chat'`. Assert that `useChat.getState().pendingAsk` has `text: 'summarise risks'` and `attachments[0].path === <the doc's note_path>`. Assert that `useNavigation.getState().active === 'chat'`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd desktop && npx vitest run src/renderer/__tests__/chat-store.test.ts src/renderer/__tests__/ChatScreen.test.tsx src/renderer/__tests__/DocInspector.test.tsx src/renderer/__tests__/DocsScreen.test.tsx`
Expected: FAIL. `queueAsk` is not a function, the ask box is missing, and so on.

- [ ] **Step 3: Implement**

- `stores/chat.ts`: add to the state interface and the store:

```ts
export interface PendingAsk { convId: string; text: string; attachments: ChatAttachment[] }
// state:
  pendingAsk: PendingAsk | null;
  queueAsk: (a: PendingAsk) => void;
  takeAsk: (convId: string) => PendingAsk | null;
// store:
  pendingAsk: null,
  queueAsk: (a) => set({ pendingAsk: a }),
  takeAsk: (convId) => {
    const a = useChat.getState().pendingAsk;
    if (!a || a.convId !== convId) return null;
    set({ pendingAsk: null });
    return a;
  },
```

  (`takeAsk` is synchronous with `set`, so a second call in the same tick returns `null`.)
- `screens/chat.tsx`: after `sendMessage` is defined, add:

```tsx
  // "ask about this doc" (docs screen) queues a question for a fresh
  // conversation; send it once that conversation is active.
  useEffect(() => {
    if (!activeId) return;
    const ask = useChat.getState().takeAsk(activeId);
    if (ask) sendMessage(ask.text, [], ask.attachments);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeId]);
```

- `DocInspector.tsx`: add the `onAsk` prop and, as the last child of the `<aside>` (pushed to the bottom with `mt-auto`):

```tsx
      <form
        className="mt-auto flex items-center gap-2 rounded-[9px] border border-hairline-2 bg-paper px-2.5 py-2"
        onSubmit={(e) => {
          e.preventDefault();
          const input = e.currentTarget.elements.namedItem('ask') as HTMLInputElement;
          const q = input.value.trim();
          if (!q) return;
          onAsk(q);
          input.value = '';
        }}
      >
        <input name="ask" placeholder="ask about this doc…" className="min-w-0 flex-1 bg-transparent text-12 text-ink-0 outline-none placeholder:text-ink-3" />
        <button type="submit" aria-label="ask" className="grid h-[22px] w-[22px] place-items-center rounded-md bg-neon font-bold text-[#0E0F12]">↑</button>
      </form>
```

- `docs.tsx`: wire the handler.

```tsx
  const createConversation = useCreateConversation();
  const askAbout = async (question: string) => {
    if (!selectedDoc) return;
    try {
      const conv = await createConversation.mutateAsync();
      useChat.getState().queueAsk({
        convId: conv.id,
        text: question,
        attachments: [{ path: selectedDoc.note_path, title: selectedDoc.title, kind: selectedDoc.kind }],
      });
      useChat.getState().setActive(conv.id);
      useNavigation.getState().setActive('chat');
    } catch (e) {
      toast.error(errMsg(e));
    }
  };
```

  Pass `onAsk={(q) => void askAbout(q)}` to `DocInspector`.

- [ ] **Step 4: Run the tests**

Run: `cd desktop && npx vitest run && npm run typecheck && npm run lint`
Expected: PASS. Output pristine.

- [ ] **Step 5: Commit**

```bash
git add desktop/src
git commit -m "feat(docs): ask about this doc opens a grounded chat

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Verification

- [ ] **Step 1:** Run all of these, with real output tails in the report:
  - `uv run --extra dev --extra api pytest tests/test_doc_library_*.py tests/test_library_routes.py tests/test_file_kinds.py -q`
  - The full Python suite, ignoring wasapi. Its failure set must match `main`'s.
  - `cd desktop && npx vitest run && npm run typecheck && npm run lint && npm run build`
  - `npx -y node@20 node_modules/vitest/vitest.mjs run`, three times, all green.
- [ ] **Step 2: Sandbox dev check (controller, with the user).**
  - Launch with `npx electron-vite dev -- --user-data-dir=<scratch>` against a seeded scratch vault.
  - Upload a real PDF. Watch "summarising…" turn into a summary within about 30 s; this uses the real configured provider.
  - Click "summarise" on an older doc that has no summary.
  - Ask a question, and confirm the chat opens with the doc chip attached and answers from it.

## Self-review notes

- **Spec coverage:**
  - §5 summary (budget, 12k, skips, failure isolation): Task 1.
  - Trigger after upload, adopt and reindex: Task 2.
  - The "what poltergeist knows" card, shimmer and retry: Task 3.
  - Ask about this doc: Task 4.
  - Indexing: unchanged (spec says no indexer changes).
- **Deviation:** the spec says "summarising…" shows as a shimmer. The plan uses `animate-pulse` text, which is the same intent.
- **Review Focus coverage:**
  - Item 1: move during the LLM call (Task 1 test).
  - Item 2: in-flight dedupe (Task 1 test).
  - Item 3: provider failure gives `none` plus the summarise button (Task 1 and Task 3 tests).
  - Item 4: the 12k cap (Task 1 test).
  - Item 5: queued ask taken exactly once, only for its conversation (Task 4 tests).
