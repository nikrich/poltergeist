# Chat File Attachments — Slice 2 (PDF / Word docs) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend chat attachments to accept **PDF and Word (.docx)** files: extract their text server-side and store it as an indexed vault note, reusing the entire Slice 1 pipeline (persistence, prompt grounding, chips).

**Architecture:** Add a pure-Python extraction step (`pypdf` for PDF, `python-docx` for .docx) in a new `attachment_extract` module. `save_attachment` classifies each file (text / pdf / docx), applies the right size cap, extracts text for docs, and writes the same note shape as Slice 1 with `kind` set accordingly. The renderer accepts the two new types and applies a larger size cap for binary docs. Everything downstream (upload endpoint, message persistence, prompt augmentation, chips) is unchanged.

**Tech Stack:** Python 3 / FastAPI / pydantic / pypdf / python-docx / pytest; TypeScript / React / Vitest.

## Global Constraints

- Attachment notes still live under `20-contexts/chat-attachments/`; note shape and frontmatter are identical to Slice 1 except `kind` becomes `"pdf"` or `"docx"` for docs.
- Extraction is **pure-Python only** (`pypdf`, `python-docx`) — NO binary/system deps (keeps the cpu-only Linux CI build safe). Both must be declared in `pyproject.toml` `dependencies` (the frozen PyInstaller bundle only ships declared deps).
- Grounding stays reference-by-path: docs become a text note the agent reads via `poltergeist_get_note`. No inlining.
- Size caps: text files `MAX_TEXT_BYTES = 1_000_000` (unchanged); PDF/docx `MAX_DOC_BYTES = 20_000_000`.
- Content-addressed dedup hashes the RAW uploaded bytes (not the extracted text), same as Slice 1.
- A doc that yields no extractable text (scanned/image-only PDF, empty docx) is rejected with a clear error, not stored as an empty note.
- Run Python tests from the worktree root with `/Users/jannik/.agentflow/.venv/bin/pytest <paths> -v`. Desktop: `npx vitest run <filter>` and `npm run typecheck` from `desktop/`.

---

### Task 1: Declare deps + `attachment_extract` module

**Files:**
- Modify: `pyproject.toml` (add `pypdf`, `python-docx` to `dependencies`)
- Create: `ghostbrain/api/repo/attachment_extract.py`
- Test: `ghostbrain/api/tests/test_attachment_extract.py`

**Interfaces:**
- Consumes: `pypdf.PdfReader`, `docx.Document`.
- Produces:
  - `DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"`
  - `classify(filename: str, mime: str) -> str | None` → `"pdf"`, `"docx"`, or `None` (unknown to this module — text is handled elsewhere).
  - `extract_text(filename: str, mime: str, content: bytes) -> str` → extracted plain text; raises `ExtractionError` on corrupt/encrypted/empty.
  - `class ExtractionError(RuntimeError)`.

- [ ] **Step 1: Write the failing tests**

Create `ghostbrain/api/tests/test_attachment_extract.py`:

```python
import io

import pytest

from ghostbrain.api.repo import attachment_extract as ex


# A minimal single-page PDF drawing "Hello PDF world" via a BT/Tj text object.
# pypdf logs a recoverable "incorrect startxref" warning and still extracts —
# that warning is expected and harmless.
MINIMAL_PDF = b"""%PDF-1.4
1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj
2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj
3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>endobj
4 0 obj<</Length 58>>stream
BT /F1 24 Tf 72 700 Td (Hello PDF world) Tj ET
endstream endobj
5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj
xref
0 6
0000000000 65535 f 
0000000009 00000 n 
0000000052 00000 n 
0000000101 00000 n 
0000000209 00000 n 
0000000317 00000 n 
trailer<</Size 6/Root 1 0 R>>
startxref
388
%%EOF"""


def _docx_bytes(*paragraphs: str) -> bytes:
    from docx import Document

    d = Document()
    for p in paragraphs:
        d.add_paragraph(p)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def test_classify():
    assert ex.classify("a.pdf", "application/pdf") == "pdf"
    assert ex.classify("a.PDF", "") == "pdf"
    assert ex.classify("a.docx", ex.DOCX_MIME) == "docx"
    assert ex.classify("a.docx", "") == "docx"
    assert ex.classify("a.txt", "text/plain") is None


def test_extract_pdf_text():
    out = ex.extract_text("a.pdf", "application/pdf", MINIMAL_PDF)
    assert "Hello PDF world" in out


def test_extract_docx_text():
    data = _docx_bytes("Hello DOCX world", "second line")
    out = ex.extract_text("a.docx", ex.DOCX_MIME, data)
    assert "Hello DOCX world" in out
    assert "second line" in out


def test_extract_corrupt_pdf_raises():
    with pytest.raises(ex.ExtractionError):
        ex.extract_text("a.pdf", "application/pdf", b"not a pdf at all")


def test_extract_empty_docx_raises():
    with pytest.raises(ex.ExtractionError):
        ex.extract_text("a.docx", ex.DOCX_MIME, _docx_bytes("", "   "))


def test_extract_unknown_kind_raises():
    with pytest.raises(ex.ExtractionError):
        ex.extract_text("a.txt", "text/plain", b"hi")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/jannik/.agentflow/.venv/bin/pytest ghostbrain/api/tests/test_attachment_extract.py -v`
Expected: FAIL — `ModuleNotFoundError: ghostbrain.api.repo.attachment_extract`.

- [ ] **Step 3: Add the dependencies**

In `pyproject.toml`, add to the `dependencies = [` list (near `markdown>=3.6`):

```toml
    "pypdf>=4.0",
    "python-docx>=1.1",
```

Then install into the venv so tests can import them:

Run: `/Users/jannik/.agentflow/.venv/bin/pip install "pypdf>=4.0" "python-docx>=1.1"`
Expected: both installed (python-docx may already be present).

- [ ] **Step 4: Implement the extractor**

Create `ghostbrain/api/repo/attachment_extract.py`:

```python
"""Extract plain text from binary document attachments (PDF, .docx).

Pure-Python only (pypdf, python-docx) so the cpu-only Linux CI bundle stays
lean. Text attachments are handled directly in chat_attachments; this module
only knows about the binary document kinds.
"""
from __future__ import annotations

import io
from pathlib import Path

DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class ExtractionError(RuntimeError):
    """The document couldn't be read, or held no extractable text."""


def classify(filename: str, mime: str) -> str | None:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf" or mime == "application/pdf":
        return "pdf"
    if ext == ".docx" or mime == DOCX_MIME:
        return "docx"
    return None


def extract_text(filename: str, mime: str, content: bytes) -> str:
    kind = classify(filename, mime)
    if kind == "pdf":
        text = _extract_pdf(content)
    elif kind == "docx":
        text = _extract_docx(content)
    else:
        raise ExtractionError(f"not an extractable document: {filename} ({mime})")
    if not text.strip():
        raise ExtractionError(
            f"no extractable text in {filename} (scanned or image-only?)"
        )
    return text


def _extract_pdf(content: bytes) -> str:
    from pypdf import PdfReader
    from pypdf.errors import PdfError

    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted:
            # An empty-password decrypt succeeds for many "encrypted" PDFs.
            try:
                reader.decrypt("")
            except Exception as e:  # noqa: BLE001
                raise ExtractionError("PDF is password-protected") from e
        pages = [(page.extract_text() or "") for page in reader.pages]
    except ExtractionError:
        raise
    except (PdfError, OSError, ValueError, Exception) as e:  # noqa: BLE001
        raise ExtractionError(f"could not read PDF: {e}") from e
    return "\n\n".join(p for p in pages if p.strip())


def _extract_docx(content: bytes) -> str:
    import docx
    from docx.opc.exceptions import PackageNotFoundError

    try:
        document = docx.Document(io.BytesIO(content))
    except (PackageNotFoundError, KeyError, ValueError, OSError) as e:
        raise ExtractionError(f"could not read .docx: {e}") from e
    return "\n".join(p.text for p in document.paragraphs if p.text.strip())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `/Users/jannik/.agentflow/.venv/bin/pytest ghostbrain/api/tests/test_attachment_extract.py -v`
Expected: PASS (6 tests). (A `pypdf` "incorrect startxref" warning on the minimal-PDF test is expected and does not fail the test.)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml ghostbrain/api/repo/attachment_extract.py ghostbrain/api/tests/test_attachment_extract.py
git commit -m "feat(chat): extract text from PDF/docx attachments"
```

---

### Task 2: Wire extraction into `save_attachment`

**Files:**
- Modify: `ghostbrain/api/repo/chat_attachments.py`
- Test: `ghostbrain/api/tests/test_chat_attachments.py` (append)

**Interfaces:**
- Consumes: `attachment_extract.classify`, `attachment_extract.extract_text`, `attachment_extract.ExtractionError`, `attachment_extract.DOCX_MIME` (Task 1).
- Produces: `save_attachment` now accepts pdf/docx too; the returned dict and stored frontmatter carry `kind` ∈ {`text`,`pdf`,`docx`}. New constant `MAX_DOC_BYTES = 20_000_000`.

- [ ] **Step 1: Write the failing tests**

Append to `ghostbrain/api/tests/test_chat_attachments.py` (reuse `tmp_vault`; add the `MINIMAL_PDF` bytes literal and a small docx helper — copy the `MINIMAL_PDF` constant and `_docx_bytes` helper from `test_attachment_extract.py`, or import them):

```python
def test_saves_pdf_note_with_extracted_text(tmp_vault):
    result = repo.save_attachment("c", "report.pdf", "application/pdf", MINIMAL_PDF)
    assert result["kind"] == "pdf"
    assert result["title"] == "report.pdf"
    body = (tmp_vault / result["path"]).read_text(encoding="utf-8")
    assert "kind: pdf" in body
    assert "Hello PDF world" in body


def test_saves_docx_note_with_extracted_text(tmp_vault):
    data = _docx_bytes("Hello DOCX world")
    result = repo.save_attachment("c", "notes.docx", repo_ex_DOCX_MIME, data)
    assert result["kind"] == "docx"
    assert "Hello DOCX world" in (tmp_vault / result["path"]).read_text(encoding="utf-8")


def test_pdf_over_doc_cap_rejected(tmp_vault):
    big = MINIMAL_PDF + b"%" + b"a" * (repo.MAX_DOC_BYTES)
    with pytest.raises(repo.AttachmentTooLarge):
        repo.save_attachment("c", "big.pdf", "application/pdf", big)


def test_scanned_pdf_no_text_rejected(tmp_vault):
    # A structurally-valid PDF with no text content → UnsupportedAttachment.
    with pytest.raises(repo.UnsupportedAttachment):
        repo.save_attachment("c", "scan.pdf", "application/pdf", b"%PDF-1.4\n%%EOF")


def test_pdf_reuse_preserves_kind(tmp_vault):
    a = repo.save_attachment("c", "r.pdf", "application/pdf", MINIMAL_PDF)
    b = repo.save_attachment("c", "r.pdf", "application/pdf", MINIMAL_PDF)
    assert a["path"] == b["path"]
    assert b["kind"] == "pdf"
```

Add near the top of the test file:

```python
from ghostbrain.api.repo.attachment_extract import DOCX_MIME as repo_ex_DOCX_MIME
```

(and the `MINIMAL_PDF` constant + `_docx_bytes` helper, copied from `test_attachment_extract.py`.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/jannik/.agentflow/.venv/bin/pytest ghostbrain/api/tests/test_chat_attachments.py -v -k "pdf or docx"`
Expected: FAIL — pdf/docx currently hit `UnsupportedAttachment` (not text), so `save_attachment` raises before writing.

- [ ] **Step 3: Refactor `save_attachment` to dispatch by kind**

In `ghostbrain/api/repo/chat_attachments.py`:

Add the import and constant near the top:

```python
from ghostbrain.api.repo import attachment_extract

MAX_DOC_BYTES = 20_000_000
```

Replace the body of `save_attachment` (from the type check through the `body` computation) with a kind-dispatching version. The full function:

```python
def save_attachment(conv_id: str, filename: str, mime: str, content: bytes) -> dict:
    kind = _classify(filename, mime)
    if kind is None:
        raise UnsupportedAttachment(f"unsupported attachment type: {filename} ({mime})")

    cap = MAX_TEXT_BYTES if kind == "text" else MAX_DOC_BYTES
    if len(content) > cap:
        raise AttachmentTooLarge(f"{filename} exceeds {cap} bytes")

    if kind == "text":
        try:
            body = _text_body(filename, content)
        except UnicodeDecodeError as e:
            raise UnsupportedAttachment(f"{filename} is not valid UTF-8 text") from e
    else:
        try:
            body = attachment_extract.extract_text(filename, mime, content)
        except attachment_extract.ExtractionError as e:
            raise UnsupportedAttachment(str(e)) from e

    note_id = hashlib.sha256(content).hexdigest()[:12]
    target_dir = vault_path() / ATTACHMENTS_DIR_REL
    target_dir.mkdir(parents=True, exist_ok=True)

    for existing in sorted(target_dir.glob("*.md")):
        if _frontmatter_id(existing) == note_id:
            return _result(
                existing,
                title=_frontmatter_title(existing) or filename,
                kind=_frontmatter_kind(existing) or kind,
            )

    front = {
        "id": note_id,
        "source": "chat-attachment",
        "title": filename,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "conversation_id": conv_id,
        "original_filename": filename,
        "kind": kind,
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    note_path = target_dir / f"{stamp}-{_slug(filename)}.md"
    note_path.write_text(_render(front, body), encoding="utf-8")
    return _result(note_path, title=filename, kind=kind)
```

Add the classifier and text-body helpers, and replace `_is_text` (now unused) with `_classify`:

```python
def _classify(filename: str, mime: str) -> str | None:
    ext = Path(filename).suffix.lower()
    if ext in TEXT_EXTENSIONS or mime.startswith("text/"):
        return "text"
    return attachment_extract.classify(filename, mime)  # "pdf" | "docx" | None


def _text_body(filename: str, content: bytes) -> str:
    text = content.decode("utf-8")  # may raise UnicodeDecodeError (caught by caller)
    ext = Path(filename).suffix.lower()
    lang = _LANG_BY_EXT.get(ext, "")
    if ext in (".md", ".markdown"):
        return text
    return f"```{lang}\n{text}\n```" if lang else text
```

Update `_result` to take explicit `title`/`kind`, and add `_frontmatter_kind`:

```python
def _result(note_path: Path, *, title: str, kind: str) -> dict:
    rel = note_path.resolve().relative_to(vault_path().resolve())
    return {"path": str(rel), "title": title, "kind": kind}


def _frontmatter_kind(path: Path) -> str | None:
    fm = _frontmatter(path)
    return fm.get("kind") if fm else None
```

Delete the now-unused `_is_text` function. (Its logic moved into `_classify`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/jannik/.agentflow/.venv/bin/pytest ghostbrain/api/tests/test_chat_attachments.py -v`
Expected: PASS (all Slice 1 text tests + the 5 new pdf/docx tests). The Slice 1 text tests still exercise the `kind == "text"` path unchanged.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/chat_attachments.py ghostbrain/api/tests/test_chat_attachments.py
git commit -m "feat(chat): store PDF/docx attachments as extracted-text notes"
```

---

### Task 3: Renderer accepts PDF/docx with a larger cap

**Files:**
- Modify: `desktop/src/renderer/lib/chat-attachments.ts`
- Modify: `desktop/src/renderer/screens/chat.tsx` (composer size-check uses per-file cap)
- Test: `desktop/src/renderer/__tests__/chat-attachments.test.ts` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `ACCEPTED_EXTENSIONS` includes `pdf`,`docx`; `isAccepted` accepts their MIME types; `MAX_DOC_BYTES = 20_000_000`; `maxBytesFor(file: File): number`. The composer rejects a file over `maxBytesFor(file)` (not the flat `MAX_FILE_BYTES`).

- [ ] **Step 1: Write the failing test**

Append to `desktop/src/renderer/__tests__/chat-attachments.test.ts`:

```typescript
import { maxBytesFor, MAX_DOC_BYTES, MAX_FILE_BYTES } from '../lib/chat-attachments';

describe('pdf/docx acceptance + caps', () => {
  it('accepts .pdf and .docx by extension and mime', () => {
    expect(isAccepted(new File(['x'], 'a.pdf', { type: 'application/pdf' }))).toBe(true);
    expect(
      isAccepted(new File(['x'], 'a.docx', {
        type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      })),
    ).toBe(true);
  });

  it('gives docs a larger byte cap than text', () => {
    expect(maxBytesFor(new File(['x'], 'a.pdf'))).toBe(MAX_DOC_BYTES);
    expect(maxBytesFor(new File(['x'], 'a.txt'))).toBe(MAX_FILE_BYTES);
    expect(MAX_DOC_BYTES).toBeGreaterThan(MAX_FILE_BYTES);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `desktop/`): `npx vitest run chat-attachments`
Expected: FAIL — `maxBytesFor` / `MAX_DOC_BYTES` not exported.

- [ ] **Step 3: Extend the helper**

In `desktop/src/renderer/lib/chat-attachments.ts`:

Add the docx MIME constant and the doc extensions/cap, extend `ACCEPTED_EXTENSIONS` and `isAccepted`, and add `maxBytesFor`:

```typescript
export const MAX_DOC_BYTES = 20_000_000;
const DOCX_MIME =
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document';
const DOC_EXTENSIONS = ['pdf', 'docx'];
```

Add `'pdf', 'docx'` to the end of the `ACCEPTED_EXTENSIONS` array. Replace `isAccepted` and add `maxBytesFor`:

```typescript
export function isAccepted(file: File): boolean {
  const ext = file.name.split('.').pop()?.toLowerCase() ?? '';
  return (
    ACCEPTED_EXTENSIONS.includes(ext) ||
    file.type.startsWith('text/') ||
    file.type === 'application/pdf' ||
    file.type === DOCX_MIME
  );
}

function extOf(file: File): string {
  return file.name.split('.').pop()?.toLowerCase() ?? '';
}

export function maxBytesFor(file: File): number {
  return DOC_EXTENSIONS.includes(extOf(file)) ? MAX_DOC_BYTES : MAX_FILE_BYTES;
}
```

- [ ] **Step 4: Composer uses the per-file cap**

In `desktop/src/renderer/screens/chat.tsx`, update the import from `../lib/chat-attachments` to include `maxBytesFor` (alongside `uploadAttachments`, `isAccepted`, `MAX_FILE_BYTES`, `MAX_FILES`). In `Composer`'s `addFiles`, replace the size check:

```typescript
      const cap = maxBytesFor(f);
      if (f.size > cap) {
        toast.error(`${f.name}: too large (max ${Math.round(cap / 1_000_000)} MB)`);
        continue;
      }
```

(Replace the existing `if (f.size > MAX_FILE_BYTES) { ... }` block. `MAX_FILE_BYTES` may remain imported if still referenced elsewhere; if it becomes unused, drop it from the import to keep typecheck clean under `noUnusedLocals`.)

- [ ] **Step 5: Run tests + typecheck**

Run (from `desktop/`): `npx vitest run chat-attachments` then `npm run typecheck`.
Expected: PASS; typecheck exit 0.

- [ ] **Step 6: Commit**

```bash
git add desktop/src/renderer/lib/chat-attachments.ts desktop/src/renderer/screens/chat.tsx desktop/src/renderer/__tests__/chat-attachments.test.ts
git commit -m "feat(chat): accept PDF/docx attachments in the composer"
```

---

## Final verification

- [ ] Full Python attachment + chat suites: `/Users/jannik/.agentflow/.venv/bin/pytest ghostbrain/api/tests/test_attachment_extract.py ghostbrain/api/tests/test_chat_attachments.py ghostbrain/api/tests/test_chat.py tests/test_chat_store.py tests/test_chat_repo.py -q` — expect green.
- [ ] Full desktop suite + typecheck: from `desktop/`, `npx vitest run` then `npm run typecheck` — expect green.
- [ ] Manual smoke: drop a real PDF and a .docx onto the composer, send, confirm the turn references `[[20-contexts/chat-attachments/…]]`, the notes exist on disk with `kind: pdf`/`kind: docx` and the extracted text as body.

## Out of scope (future slices)

- Images (Slice 3): store binary + OCR/caption — the MCP-only agent has no vision input.
- PowerPoint/Excel and other office formats.
- Storing the original binary alongside the extracted-text note (grounding only needs the text).
- Per-page or table-structure-aware PDF extraction (flat text is enough for grounding).
