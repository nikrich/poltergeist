# Docs Library — Slice 1 (Library core) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Users can upload files into per-project (and per-context "unfiled") folder trees, browse them in a new Docs screen (tree · reader · inspector, with a list/grid switch), view PDFs/images/Office/text in-app, and move docs and folders around, including across projects. Every doc's text is indexed as an ordinary vault note.

**Architecture:** The vault is the catalog. Each upload writes the original file plus a companion `.md` note (YAML frontmatter + extracted text) into `20-contexts/{ctx}[/projects/{slug}]/docs/<folders>/`. A Python package `ghostbrain/api/repo/doc_library/` owns scopes, the path guard, an mtime-cached in-memory index, doc ops and folder ops. `/v1/library` exposes them. The Electron main process serves raw originals over a guarded `gbdoc://` protocol. The renderer adds a `docs` screen built from focused components under `components/docs/`.

**Tech Stack:** Python 3.11 / FastAPI / PyYAML / pypdf / send2trash (new); Electron 32 / React 18 / TanStack Query / zustand / Tailwind v4 / pdfjs-dist 4.10.38 (new) / Vitest + RTL.

**Spec:** `docs/superpowers/specs/2026-10-09-docs-library-design.md` (this slice = "Library core": spec §1–4, §6 minus AI parts of the inspector, §7).

**Worktree:** a git worktree off `origin/main`, branch `feat/docs-library`. **Every command runs from that directory.** Prefix shell commands with `cd <worktree> &&` and check `git rev-parse --abbrev-ref HEAD` prints `feat/docs-library` before committing (subagents' git otherwise hits the main checkout).

## Global Constraints

- Size limits: **20 MB** documents/images/opaque, **1 MB** text (same as chat attachments).
- Docs roots are exactly `20-contexts/{ctx}/docs` and `20-contexts/{ctx}/projects/{slug}/docs`. Nothing outside a docs root is ever read or written by the library.
- Companion note filename: `<make_slug(title)>-<doc_id[:6]>.md`. `doc_id` = 12 random hex chars and never changes. `sha256` is only used for duplicate detection within one scope.
- Frontmatter key `source: doc-library` marks a companion note. Field names exactly as in spec §1.
- Deletes go to the OS trash (`send2trash`), never a permanent unlink of user files.
- API prefix `/v1/library` (`/v1/docs` is taken).
- UI copy is lowercase in titles/labels, matching existing screens (`docs`, `upload`, `needs attention`).
- Python tests: pytest with a temporary vault via `VAULT_PATH` **and** a sandboxed `GHOSTBRAIN_STATE_DIR` (local pytest otherwise clobbers `~/.ghostbrain/state`).
- Desktop typecheck is `npm run typecheck` (`tsc -b`). `tsc --noEmit` is a no-op in this repo.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Filenames with spaces, unicode, leading dots, or path separators** (`../x.pdf`, `résumé.docx`, `.env`). Expect: stored under a sanitised basename inside the target folder, never outside it. Pinned in Task 4.
2. **The same file uploaded twice into the same folder, and into a different project.** Expect: the same scope returns the existing doc (`duplicate: true`). A different scope creates a separate doc with its own `doc_id` and note basename. Pinned in Task 4.
3. **A folder moved into another project.** Expect: every companion note inside gets its `context`/`project` re-stamped, so the tree and search show it under the new project. Pinned in Task 7.
4. **Files dropped into a docs folder via Finder/Obsidian (no companion note).** Expect: they appear under "needs attention" as unclaimed and can be adopted. They must not crash the tree or be listed as docs. Pinned in Task 5 and Task 8.
5. **An archived project as a target.** Expect: upload/move/folder ops into it get a 409, while its existing docs still show in the tree (dimmed). Pinned in Task 4 and Task 6.

---

## File structure

**Backend (new)**
- `ghostbrain/api/repo/file_kinds.py`: kind classification, size caps, text body. Shared with chat attachments.
- `ghostbrain/api/repo/doc_library/__init__.py`: package marker.
- `ghostbrain/api/repo/doc_library/errors.py`: error classes, each carrying an HTTP status.
- `ghostbrain/api/repo/doc_library/scope.py`: docs roots, path guard, scope enumeration.
- `ghostbrain/api/repo/doc_library/notes.py`: companion-note format, naming, atomic write, unique filenames.
- `ghostbrain/api/repo/doc_library/index.py`: mtime-cached scan → doc entries, orphans, attention, tree, summaries.
- `ghostbrain/api/repo/doc_library/ops.py`: upload, move, rename, delete, reindex, adopt, remove-orphan.
- `ghostbrain/api/repo/doc_library/folders.py`: create, move/rename, delete-empty.
- `ghostbrain/api/repo/doc_library/search.py`: fuzzy title/path search.
- `ghostbrain/api/models/library.py`, `ghostbrain/api/routes/library.py`.
- Tests: `tests/doc_library_helpers.py` (fixture), `tests/test_file_kinds.py`, `tests/test_doc_library_scope.py`, `tests/test_doc_library_upload.py`, `tests/test_doc_library_index.py`, `tests/test_doc_library_ops.py`, `tests/test_doc_library_folders.py`, `tests/test_doc_library_attention.py`, `tests/test_doc_library_search.py`, `tests/test_library_routes.py`.

**Backend (modified)**
- `ghostbrain/api/repo/chat_attachments.py`: delegates classification/text body to `file_kinds`.
- `ghostbrain/api/main.py`: registers the library router.
- `pyproject.toml`: adds `send2trash>=1.8`.

**Desktop (new)**
- `desktop/src/main/doc-protocol.ts`: `gbdoc://` handler + path guard. Test: `desktop/src/main/__tests__/doc-protocol.test.ts`.
- `desktop/src/renderer/stores/docs.ts`: selection, per-folder view mode, upload ghosts.
- `desktop/src/renderer/components/docs/kinds.ts`: kind chip metadata, `docUrl`, `folderKey`, size formatting.
- `desktop/src/renderer/components/docs/KindChip.tsx`
- `desktop/src/renderer/components/docs/tree-model.ts`: pure tree helpers + drag payloads.
- `desktop/src/renderer/components/docs/DocTree.tsx`
- `desktop/src/renderer/components/docs/upload.ts`: File → base64, client-side cap.
- `desktop/src/renderer/components/docs/pdf.ts`: the only module that imports `pdfjs-dist`.
- `desktop/src/renderer/components/docs/Thumb.tsx`
- `desktop/src/renderer/components/docs/FolderView.tsx`
- `desktop/src/renderer/components/docs/PdfViewer.tsx`
- `desktop/src/renderer/components/docs/DocReader.tsx`
- `desktop/src/renderer/components/docs/DocInspector.tsx`
- `desktop/src/renderer/components/docs/AttentionPanel.tsx`
- `desktop/src/renderer/components/docs/QuickOpen.tsx`
- `desktop/src/renderer/screens/docs.tsx`
- Tests under `desktop/src/renderer/__tests__/`: `docs-tree-model.test.ts`, `DocTree.test.tsx`, `docs-store.test.ts`, `FolderView.test.tsx`, `DocReader.test.tsx`, `DocInspector.test.tsx`, `DocsScreen.test.tsx`.

**Desktop (modified)**
- `desktop/src/main/assets.ts`: adds `gbdoc` to the privileged-scheme registration.
- `desktop/src/main/index.ts`: registers the doc protocol + `gb:shell:showItemInFolder`.
- `desktop/src/preload/index.ts`, `desktop/src/shared/types.ts`, `desktop/src/renderer/test/setup.ts`: `shell.showItemInFolder`.
- `desktop/src/renderer/index.html`: CSP allows `gbdoc:` in `img-src` and `connect-src`.
- `desktop/src/shared/api-types.ts`: library types.
- `desktop/src/renderer/lib/api/hooks.ts`: library hooks.
- `desktop/src/renderer/stores/navigation.ts`, `components/Sidebar.tsx`, `App.tsx`: `docs` screen.
- `desktop/package.json`: `pdfjs-dist@4.10.38`.

---

### Task 1: Shared file kinds

**Files:**
- Create: `ghostbrain/api/repo/file_kinds.py`
- Modify: `ghostbrain/api/repo/chat_attachments.py` (lines 21–75: constants, `_LANG_BY_EXT`, `TEXT_EXTENSIONS`, `_classify`, `_text_body`)
- Test: `tests/test_file_kinds.py`

**Interfaces:**
- Produces: `file_kinds.classify(filename: str, mime: str) -> str | None` (`"text" | "image" | "pdf" | "docx" | "xlsx" | None`), `file_kinds.cap_for(kind: str) -> int` (`"opaque"` → 20 MB), `file_kinds.text_body(filename: str, content: bytes) -> str` (raises `UnicodeDecodeError`), constants `MAX_TEXT_BYTES`, `MAX_DOC_BYTES`, `MAX_IMAGE_BYTES`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_file_kinds.py
"""Shared file-kind classification used by chat attachments and the docs library."""
import pytest

from ghostbrain.api.repo import file_kinds


@pytest.mark.parametrize(
    "name,mime,kind",
    [
        ("a.md", "", "text"),
        ("a.py", "", "text"),
        ("notes", "text/plain", "text"),
        ("a.png", "", "image"),
        ("a", "image/jpeg", "image"),
        ("a.pdf", "", "pdf"),
        ("a.docx", "", "docx"),
        ("a.xlsx", "", "xlsx"),
        ("a.zip", "application/zip", None),
    ],
)
def test_classify(name, mime, kind):
    assert file_kinds.classify(name, mime) == kind


def test_caps():
    assert file_kinds.cap_for("text") == 1_000_000
    assert file_kinds.cap_for("image") == 20_000_000
    assert file_kinds.cap_for("pdf") == 20_000_000
    assert file_kinds.cap_for("opaque") == 20_000_000


def test_text_body_fences_code_and_passes_markdown():
    assert file_kinds.text_body("a.md", b"# hi") == "# hi"
    assert file_kinds.text_body("a.py", b"x = 1") == "```py\nx = 1\n```"
    with pytest.raises(UnicodeDecodeError):
        file_kinds.text_body("a.txt", b"\xff\xfe\x00")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev --extra api pytest tests/test_file_kinds.py -q`
Expected: FAIL with `ImportError: cannot import name 'file_kinds'`

- [ ] **Step 3: Write the module**

```python
# ghostbrain/api/repo/file_kinds.py
"""File-kind classification + size caps shared by chat attachments and the docs library."""
from __future__ import annotations

from pathlib import Path

from ghostbrain.api.repo import attachment_caption, attachment_extract

MAX_TEXT_BYTES = 1_000_000
MAX_DOC_BYTES = 20_000_000
MAX_IMAGE_BYTES = 20_000_000

# Extension → fenced-code language. Markdown extensions map to "" (inline as-is).
LANG_BY_EXT = {
    ".md": "", ".markdown": "",
    ".txt": "", ".text": "", ".log": "",
    ".py": "py", ".js": "js", ".ts": "ts", ".tsx": "tsx", ".jsx": "jsx",
    ".go": "go", ".rs": "rs", ".java": "java", ".c": "c", ".h": "c",
    ".cpp": "cpp", ".sh": "sh", ".rb": "rb", ".sql": "sql", ".html": "html",
    ".css": "css", ".xml": "xml", ".toml": "toml", ".ini": "ini",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml", ".csv": "", ".tsv": "",
}
TEXT_EXTENSIONS = set(LANG_BY_EXT)


def classify(filename: str, mime: str) -> str | None:
    ext = Path(filename).suffix.lower()
    if ext in TEXT_EXTENSIONS or mime.startswith("text/"):
        return "text"
    if attachment_caption.is_image(filename, mime):
        return "image"
    return attachment_extract.classify(filename, mime)  # "pdf" | "docx" | "xlsx" | None


def cap_for(kind: str) -> int:
    if kind == "text":
        return MAX_TEXT_BYTES
    if kind == "image":
        return MAX_IMAGE_BYTES
    return MAX_DOC_BYTES


def text_body(filename: str, content: bytes) -> str:
    text = content.decode("utf-8")  # may raise UnicodeDecodeError (caller decides)
    ext = Path(filename).suffix.lower()
    lang = LANG_BY_EXT.get(ext, "")
    if ext in (".md", ".markdown"):
        return text
    return f"```{lang}\n{text}\n```" if lang else text
```

- [ ] **Step 4: Point chat attachments at it**

In `ghostbrain/api/repo/chat_attachments.py`:
- Replace the `MAX_*` constants, `_LANG_BY_EXT` and `TEXT_EXTENSIONS` definitions (lines 21–34) with:

```python
from ghostbrain.api.repo import file_kinds

MAX_TEXT_BYTES = file_kinds.MAX_TEXT_BYTES
MAX_DOC_BYTES = file_kinds.MAX_DOC_BYTES
MAX_IMAGE_BYTES = file_kinds.MAX_IMAGE_BYTES
TEXT_EXTENSIONS = file_kinds.TEXT_EXTENSIONS
```

- Replace the body of `_classify` with `return file_kinds.classify(filename, mime)`.
- Replace the body of `_text_body` with `return file_kinds.text_body(filename, content)`.
- Leave `_cap_for` in place, still reading this module's own `MAX_*` names.
- Remove any import that's now unused (`ruff check ghostbrain/api/repo/chat_attachments.py` tells you).

- [ ] **Step 5: Run the new and existing tests**

Run: `uv run --extra dev --extra api pytest tests/test_file_kinds.py ghostbrain/api/tests/test_chat_attachments.py -q && uv run --extra dev ruff check ghostbrain/api/repo/file_kinds.py ghostbrain/api/repo/chat_attachments.py`
Expected: all PASS, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/api/repo/file_kinds.py ghostbrain/api/repo/chat_attachments.py tests/test_file_kinds.py
git commit -m "refactor(attachments): extract shared file_kinds module for the docs library

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Library errors, scopes and the path guard

**Files:**
- Create: `ghostbrain/api/repo/doc_library/__init__.py` (empty docstring only), `ghostbrain/api/repo/doc_library/errors.py`, `ghostbrain/api/repo/doc_library/scope.py`, `tests/doc_library_helpers.py`
- Test: `tests/test_doc_library_scope.py`

**Interfaces:**
- Produces:
  - `errors.LibraryError` (has `.status: int`), plus subclasses `InvalidPath` (400), `InvalidRequest` (400), `NotFound` (404), `Conflict` (409), `TooLarge` (413).
  - `scope.DOCS_DIR = "docs"`
  - `scope.scope_root(context: str, project: str | None, *, for_write: bool = False) -> Path`
  - `scope.clean_rel(rel: str) -> str` (normalised `a/b`, `""` = root)
  - `scope.resolve_in(root: Path, rel: str) -> Path`
  - `scope.rel_folder(root: Path, folder: Path) -> str`
  - `scope.all_scopes() -> list[tuple[str, str | None, Path]]` (contexts first, then projects including archived ones)
  - Test fixture `lib_vault` in `tests/doc_library_helpers.py`: contexts `work`, `personal`; projects `work/payments`, `work/claims`; caption stubbed to `"a diagram"`; returns the vault `Path`.

- [ ] **Step 1: Write the fixture and the failing test**

```python
# tests/doc_library_helpers.py
"""Shared fixture for docs-library tests: a temp vault with two contexts and two projects."""
from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def lib_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    v = tmp_path / "vault"
    (v / "90-meta").mkdir(parents=True)
    (v / "20-contexts").mkdir()
    (v / "90-meta" / "routing.yaml").write_text("contexts:\n  - work\n  - personal\n", encoding="utf-8")
    monkeypatch.setenv("VAULT_PATH", str(v))
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(tmp_path / "state"))
    from ghostbrain.api.repo import projects

    projects.create_project("work", "Payments")
    projects.create_project("work", "Claims")
    monkeypatch.setattr(
        "ghostbrain.api.repo.attachment_caption.caption_image", lambda path: "a diagram"
    )
    try:
        from ghostbrain.api.repo.doc_library import index

        index.invalidate()
    except ImportError:  # index arrives in Task 3
        pass
    return v
```

```python
# tests/test_doc_library_scope.py
"""Docs roots + path guard (spec §1, §7)."""
from pathlib import Path

import pytest

from ghostbrain.api.repo import projects
from ghostbrain.api.repo.doc_library import scope
from ghostbrain.api.repo.doc_library.errors import Conflict, InvalidPath, NotFound
from tests.doc_library_helpers import lib_vault  # noqa: F401


def test_scope_roots(lib_vault: Path):
    assert scope.scope_root("work", None) == lib_vault / "20-contexts/work/docs"
    assert scope.scope_root("work", "payments") == lib_vault / "20-contexts/work/projects/payments/docs"


def test_scope_root_rejects_unknown_and_archived(lib_vault: Path):
    with pytest.raises(NotFound):
        scope.scope_root("nope", None)
    with pytest.raises(NotFound):
        scope.scope_root("work", "ghost")
    projects.update_project("work", "claims", archived=True)
    assert scope.scope_root("work", "claims").name == "docs"  # read is fine
    with pytest.raises(Conflict):
        scope.scope_root("work", "claims", for_write=True)


@pytest.mark.parametrize("rel,clean", [("", ""), ("a", "a"), ("a//b/", "a/b"), ("./a/./b", "a/b"), ("a\\b", "a/b")])
def test_clean_rel(rel, clean):
    assert scope.clean_rel(rel) == clean


@pytest.mark.parametrize("rel", ["../x", "a/../../x", "/etc", "C:/x", ".hidden", "a/.git"])
def test_clean_rel_rejects(rel):
    with pytest.raises(InvalidPath):
        scope.clean_rel(rel)


def test_resolve_in_blocks_symlink_escape(lib_vault: Path, tmp_path: Path):
    root = scope.scope_root("work", None)
    root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "link").symlink_to(outside)
    with pytest.raises(InvalidPath):
        scope.resolve_in(root, "link")
    assert scope.resolve_in(root, "specs/v2") == root / "specs/v2"


def test_all_scopes_includes_archived(lib_vault: Path):
    projects.update_project("work", "claims", archived=True)
    keys = [(c, p) for c, p, _ in scope.all_scopes()]
    assert keys == [("work", None), ("personal", None), ("work", "payments"), ("work", "claims")]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev --extra api pytest tests/test_doc_library_scope.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.api.repo.doc_library'`

- [ ] **Step 3: Implement**

```python
# ghostbrain/api/repo/doc_library/__init__.py
"""Docs library: uploaded originals + companion notes under project/context docs roots."""
```

```python
# ghostbrain/api/repo/doc_library/errors.py
"""Library errors. Each carries its HTTP status so the routes map them 1:1."""


class LibraryError(Exception):
    status = 400


class InvalidPath(LibraryError):
    status = 400


class InvalidRequest(LibraryError):
    status = 400


class NotFound(LibraryError):
    status = 404


class Conflict(LibraryError):
    status = 409


class TooLarge(LibraryError):
    status = 413
```

```python
# ghostbrain/api/repo/doc_library/scope.py
"""Docs roots (where each scope's tree lives) and the path guard (spec §1, §7)."""
from __future__ import annotations

import re
from pathlib import Path

from ghostbrain import routing_config
from ghostbrain.api.repo import projects
from ghostbrain.api.repo.doc_library.errors import Conflict, InvalidPath, NotFound
from ghostbrain.paths import vault_path

DOCS_DIR = "docs"
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def scope_root(context: str, project: str | None, *, for_write: bool = False) -> Path:
    if context not in routing_config.contexts():
        raise NotFound(f"unknown context: {context}")
    base = vault_path() / "20-contexts" / context
    if not project:
        return base / DOCS_DIR
    p = projects.get_project(context, project)
    if p is None:
        raise NotFound(f"unknown project: {context}/{project}")
    if for_write and p.get("archived"):
        raise Conflict(f"project is archived: {context}/{project}")
    return base / "projects" / project / DOCS_DIR


def clean_rel(rel: str) -> str:
    raw = (rel or "").replace("\\", "/")
    if raw.startswith("/") or _DRIVE_RE.match(raw):
        raise InvalidPath(f"absolute path not allowed: {rel}")
    parts = [p for p in raw.split("/") if p not in ("", ".")]
    for p in parts:
        if p.startswith("."):  # covers ".." and hidden dirs (.keep, .git, tmp files)
            raise InvalidPath(f"invalid path segment: {p!r}")
    return "/".join(parts)


def resolve_in(root: Path, rel: str) -> Path:
    cleaned = clean_rel(rel)
    target = root / cleaned if cleaned else root
    root_r = root.resolve()
    target_r = target.resolve()
    if target_r != root_r and root_r not in target_r.parents:
        raise InvalidPath(f"path escapes docs root: {rel}")
    return target


def rel_folder(root: Path, folder: Path) -> str:
    rel = folder.relative_to(root).as_posix()
    return "" if rel == "." else rel


def all_scopes() -> list[tuple[str, str | None, Path]]:
    base = vault_path() / "20-contexts"
    out: list[tuple[str, str | None, Path]] = [
        (ctx, None, base / ctx / DOCS_DIR) for ctx in routing_config.contexts()
    ]
    out += [
        (p["context"], p["slug"], base / p["context"] / "projects" / p["slug"] / DOCS_DIR)
        for p in projects.list_projects(include_archived=True)
    ]
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run --extra dev --extra api pytest tests/test_doc_library_scope.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/doc_library tests/doc_library_helpers.py tests/test_doc_library_scope.py
git commit -m "feat(library): docs roots, scope validation and path guard

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Companion notes + the doc index

**Files:**
- Create: `ghostbrain/api/repo/doc_library/notes.py`, `ghostbrain/api/repo/doc_library/index.py`
- Test: `tests/test_doc_library_index.py`

**Interfaces:**
- Consumes: `scope.all_scopes`, `scope.rel_folder`, `projects.get_project`, `errors.NotFound`.
- Produces:
  - `notes.SOURCE = "doc-library"`, `notes.KEEP = ".keep"`
  - `notes.new_doc_id() -> str`
  - `notes.note_name(title: str, doc_id: str) -> str`
  - `notes.render(front: dict, body: str) -> str`
  - `notes.read_note(path: Path) -> tuple[dict, str] | None`
  - `notes.write_atomic(path: Path, text: str) -> None`
  - `notes.unique_child(folder: Path, name: str) -> Path`
  - `notes.safe_filename(name: str) -> str`
  - `index.DocEntry` (frozen dataclass: `doc_id, note: Path, original: Path, front: dict, body: str, context: str, project: str | None, folder: str`)
  - `index.invalidate() -> None`
  - `index.all_docs() -> dict[str, DocEntry]`
  - `index.orphans() -> dict[str, Path]` (doc_id → orphan note path)
  - `index.attention() -> list[dict]`
  - `index.get(doc_id: str) -> DocEntry` (raises `NotFound`)
  - `index.summary(e: DocEntry) -> dict` (DocSummary shape below)
  - `index.detail(e: DocEntry) -> dict` (summary + `body`)
  - `index.tree(context: str | None = None, project: str | None = None) -> dict` (`{"scopes": [...], "attention": [...]}`)
- **DocSummary dict keys:** `doc_id, title, kind, mime, size, created, context, project, folder, original, original_path, note_path, index_status, pages, excerpt`. `original_path`/`note_path` are vault-relative POSIX paths, `folder` is relative to the scope root (`""` = root), and `excerpt` is ≤240 chars of the body with whitespace collapsed.
- **Attention item keys:** `kind` (`orphan_note | unclaimed_original | index_failed`), `context, project, folder, name, doc_id` (`None` for unclaimed).
- **Scope dict keys:** `context, project, name` (project name or `"unfiled"`), `archived, folders, docs`. **Folder node keys:** `name, path, folders, docs`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doc_library_index.py
"""Companion-note format + the mtime-cached doc index and tree (spec §1–2)."""
from pathlib import Path

import pytest

from ghostbrain.api.repo.doc_library import index, notes
from ghostbrain.api.repo.doc_library.errors import NotFound
from tests.doc_library_helpers import lib_vault  # noqa: F401


def _seed(folder: Path, original: str, doc_id: str, *, project=None, status="ok", body="hello world"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / original).write_bytes(b"x")
    front = {
        "doc_id": doc_id, "source": notes.SOURCE, "title": Path(original).stem,
        "original": original, "kind": "pdf", "mime": "application/pdf", "size": 1,
        "sha256": "abc", "created": "2026-10-09T10:00:00+00:00", "context": "work",
        "index_status": status,
    }
    if project:
        front["project"] = project
    note = folder / notes.note_name(Path(original).stem, doc_id)
    notes.write_atomic(note, notes.render(front, body))
    return note


def test_note_roundtrip_and_naming(tmp_path: Path):
    assert notes.note_name("Payments API v2", "3f9a1c7b20de") == "payments-api-v2-3f9a1c.md"
    p = tmp_path / "n.md"
    notes.write_atomic(p, notes.render({"source": notes.SOURCE, "created": "2026-10-09T10:00:00+00:00"}, "body"))
    front, body = notes.read_note(p)
    assert front["created"] == "2026-10-09T10:00:00+00:00"  # stays a string
    assert body == "body\n"
    (tmp_path / "other.md").write_text("---\nsource: manual\n---\nx")
    assert notes.read_note(tmp_path / "other.md") is None


def test_unique_child_and_safe_filename(tmp_path: Path):
    (tmp_path / "a.pdf").write_bytes(b"")
    (tmp_path / "a (2).pdf").write_bytes(b"")
    assert notes.unique_child(tmp_path, "a.pdf").name == "a (3).pdf"
    assert notes.safe_filename("../../etc/passwd") == "passwd"
    assert notes.safe_filename(".env") == "env"
    assert notes.safe_filename("  ") == "untitled"
    assert notes.safe_filename("résumé.docx") == "résumé.docx"


def test_index_tree_and_attention(lib_vault: Path):
    proot = lib_vault / "20-contexts/work/projects/payments/docs"
    _seed(proot / "specs", "Payments API v2.pdf", "aaaaaaaaaaaa", project="payments")
    _seed(proot, "broken.pdf", "bbbbbbbbbbbb", project="payments", status="failed")
    orphan = _seed(proot, "gone.pdf", "cccccccccccc", project="payments")
    (proot / "gone.pdf").unlink()
    (proot / "specs" / "dropped-in.png").write_bytes(b"png")
    (proot / "empty").mkdir()
    index.invalidate()

    e = index.get("aaaaaaaaaaaa")
    assert e.folder == "specs" and e.project == "payments"
    s = index.summary(e)
    assert s["original_path"] == "20-contexts/work/projects/payments/docs/specs/Payments API v2.pdf"
    assert s["excerpt"] == "hello world"
    assert index.orphans() == {"cccccccccccc": orphan}
    kinds = sorted((a["kind"], a["name"]) for a in index.attention())
    assert kinds == [
        ("index_failed", "broken.pdf"),
        ("orphan_note", orphan.name),
        ("unclaimed_original", "dropped-in.png"),
    ]

    t = index.tree("work", "payments")
    assert len(t["scopes"]) == 1
    sc = t["scopes"][0]
    assert sc["name"] == "Payments" and sc["archived"] is False
    assert [f["name"] for f in sc["folders"]] == ["empty", "specs"]
    assert [d["doc_id"] for d in sc["docs"]] == ["bbbbbbbbbbbb"]
    assert [d["doc_id"] for d in sc["folders"][1]["docs"]] == ["aaaaaaaaaaaa"]
    assert len(t["attention"]) == 3

    with pytest.raises(NotFound):
        index.get("cccccccccccc")


def test_index_rebuilds_when_dirs_change(lib_vault: Path):
    root = lib_vault / "20-contexts/personal/docs"
    assert index.all_docs() == {}
    _seed(root, "late.pdf", "dddddddddddd")  # no explicit invalidate()
    assert "dddddddddddd" in index.all_docs()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev --extra api pytest tests/test_doc_library_index.py -q`
Expected: FAIL with `ImportError: cannot import name 'index'`

- [ ] **Step 3: Implement `notes.py`**

```python
# ghostbrain/api/repo/doc_library/notes.py
"""Companion-note format: YAML frontmatter + extracted body (spec §1)."""
from __future__ import annotations

import secrets
from pathlib import Path

import yaml

from ghostbrain.api.repo.notes_manual import make_slug

SOURCE = "doc-library"
KEEP = ".keep"


def new_doc_id() -> str:
    return secrets.token_hex(6)


def note_name(title: str, doc_id: str) -> str:
    return f"{make_slug(title)}-{doc_id[:6]}.md"


def render(front: dict, body: str) -> str:
    yaml_block = yaml.safe_dump(front, sort_keys=False, allow_unicode=True).rstrip()
    return f"---\n{yaml_block}\n---\n\n{body.rstrip()}\n"


def read_note(path: Path) -> tuple[dict, str] | None:
    """(frontmatter, body) for a library companion note; None for any other file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    try:
        front = yaml.safe_load(text[4:end])
    except yaml.YAMLError:
        return None
    if not isinstance(front, dict) or front.get("source") != SOURCE:
        return None
    return front, text[end + 4 :].lstrip("\n")


def write_atomic(path: Path, text: str) -> None:
    # Dot-prefixed tmp so a crash mid-write never shows up in tree scans.
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def unique_child(folder: Path, name: str) -> Path:
    candidate = folder / name
    if not candidate.exists():
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 2
    while (folder / f"{stem} ({n}){suffix}").exists():
        n += 1
    return folder / f"{stem} ({n}){suffix}"


def safe_filename(name: str) -> str:
    base = Path(name.replace("\\", "/")).name.strip().lstrip(".")
    return base or "untitled"
```

- [ ] **Step 4: Implement `index.py`**

```python
# ghostbrain/api/repo/doc_library/index.py
"""In-memory doc index, rebuilt when any docs-root directory mtime changes (spec §2)."""
from __future__ import annotations

import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from ghostbrain.api.repo import projects
from ghostbrain.api.repo.doc_library import notes, scope
from ghostbrain.api.repo.doc_library.errors import NotFound
from ghostbrain.paths import vault_path

_EXCERPT_CHARS = 240


@dataclass(frozen=True)
class DocEntry:
    doc_id: str
    note: Path
    original: Path
    front: dict
    body: str
    context: str
    project: str | None
    folder: str


_lock = threading.Lock()
_cache: dict = {"sig": None, "docs": {}, "orphans": {}, "attention": []}


def invalidate() -> None:
    with _lock:
        _cache["sig"] = None


def _walk_dirs(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        yield Path(dirpath), sorted(f for f in filenames if not f.startswith("."))


def _signature() -> tuple:
    sig: list = [str(vault_path())]
    for ctx, proj, root in scope.all_scopes():
        sig.append((ctx, proj))
        if root.is_dir():
            sig.extend((str(d), d.stat().st_mtime_ns) for d, _ in _walk_dirs(root))
    return tuple(sig)


def _scan() -> tuple[dict[str, DocEntry], dict[str, Path], list[dict]]:
    docs: dict[str, DocEntry] = {}
    orphans: dict[str, Path] = {}
    attention: list[dict] = []
    for ctx, proj, root in scope.all_scopes():
        if not root.is_dir():
            continue
        claimed: set[Path] = set()
        others: list[tuple[Path, str]] = []
        for d, files in _walk_dirs(root):
            folder = scope.rel_folder(root, d)
            for name in files:
                p = d / name
                parsed = notes.read_note(p) if name.endswith(".md") else None
                if parsed is None:
                    others.append((p, folder))
                    continue
                front, body = parsed
                doc_id = str(front.get("doc_id") or "")
                if not doc_id:
                    continue
                original = d / str(front.get("original") or "")
                item = {"context": ctx, "project": proj, "folder": folder, "doc_id": doc_id}
                if not front.get("original") or not original.is_file():
                    orphans[doc_id] = p
                    attention.append({"kind": "orphan_note", "name": p.name, **item})
                    continue
                claimed.add(original)
                docs[doc_id] = DocEntry(doc_id, p, original, front, body, ctx, proj, folder)
                if front.get("index_status") == "failed":
                    attention.append({"kind": "index_failed", "name": original.name, **item})
        for p, folder in others:
            if p not in claimed:
                attention.append({
                    "kind": "unclaimed_original", "context": ctx, "project": proj,
                    "folder": folder, "name": p.name, "doc_id": None,
                })
    return docs, orphans, attention


def _state() -> dict:
    with _lock:
        sig = _signature()
        if _cache["sig"] != sig:
            docs, orphans, attention = _scan()
            _cache.update(sig=sig, docs=docs, orphans=orphans, attention=attention)
        return dict(_cache)


def all_docs() -> dict[str, DocEntry]:
    return _state()["docs"]


def orphans() -> dict[str, Path]:
    return _state()["orphans"]


def attention() -> list[dict]:
    return _state()["attention"]


def get(doc_id: str) -> DocEntry:
    e = all_docs().get(doc_id)
    if e is None:
        raise NotFound(f"doc not found: {doc_id}")
    return e


def _vault_rel(p: Path) -> str:
    return p.resolve().relative_to(vault_path().resolve()).as_posix()


def summary(e: DocEntry) -> dict:
    f = e.front
    created = f.get("created", "")
    return {
        "doc_id": e.doc_id,
        "title": str(f.get("title") or e.original.stem),
        "kind": str(f.get("kind") or "opaque"),
        "mime": str(f.get("mime") or ""),
        "size": int(f.get("size") or 0),
        "created": created.isoformat() if hasattr(created, "isoformat") else str(created),
        "context": e.context,
        "project": e.project,
        "folder": e.folder,
        "original": e.original.name,
        "original_path": _vault_rel(e.original),
        "note_path": _vault_rel(e.note),
        "index_status": str(f.get("index_status") or "ok"),
        "pages": f.get("pages"),
        "excerpt": re.sub(r"\s+", " ", e.body).strip()[:_EXCERPT_CHARS],
    }


def detail(e: DocEntry) -> dict:
    return {**summary(e), "body": e.body}


def _folder_node(root: Path, rel: str, name: str, by_folder: dict[str, list[dict]]) -> dict:
    d = root / rel if rel else root
    children = []
    if d.is_dir():
        subdirs = sorted(
            (c for c in d.iterdir() if c.is_dir() and not c.name.startswith(".")),
            key=lambda c: c.name.lower(),
        )
        for c in subdirs:
            crel = f"{rel}/{c.name}" if rel else c.name
            children.append(_folder_node(root, crel, c.name, by_folder))
    docs = sorted(by_folder.get(rel, []), key=lambda s: s["title"].lower())
    return {"name": name, "path": rel, "folders": children, "docs": docs}


def tree(context: str | None = None, project: str | None = None) -> dict:
    state = _state()
    scopes = []
    for ctx, proj, root in scope.all_scopes():
        if context and ctx != context:
            continue
        if project and proj != project:
            continue
        by_folder: dict[str, list[dict]] = {}
        for e in state["docs"].values():
            if e.context == ctx and e.project == proj:
                by_folder.setdefault(e.folder, []).append(summary(e))
        meta = projects.get_project(ctx, proj) if proj else None
        node = _folder_node(root, "", "", by_folder)
        scopes.append({
            "context": ctx,
            "project": proj,
            "name": meta["name"] if meta else "unfiled",
            "archived": bool(meta and meta.get("archived")),
            "folders": node["folders"],
            "docs": node["docs"],
        })
    keep = {(s["context"], s["project"]) for s in scopes}
    items = [a for a in state["attention"] if (a["context"], a["project"]) in keep]
    return {"scopes": scopes, "attention": items}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --extra dev --extra api pytest tests/test_doc_library_index.py tests/test_doc_library_scope.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/api/repo/doc_library/notes.py ghostbrain/api/repo/doc_library/index.py tests/test_doc_library_index.py
git commit -m "feat(library): companion-note format and mtime-cached doc index + tree

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Upload pipeline

**Files:**
- Create: `ghostbrain/api/repo/doc_library/ops.py`
- Modify: `pyproject.toml` (add `"send2trash>=1.8",` after `"openpyxl>=3.1",` in `dependencies`)
- Test: `tests/test_doc_library_upload.py`

**Interfaces:**
- Consumes: Task 1–3 interfaces; `attachment_extract.extract_text(filename, mime, content: bytes | Path) -> str`; `attachment_caption.caption_image(path) -> str`.
- Produces:
  - `ops.upload(context: str, project: str | None, folder: str, filename: str, mime: str, content: bytes) -> dict` (DocSummary + `duplicate: bool`)
  - `ops._index_original(orig: Path, *, context: str, project: str | None, title: str, mime: str, kind: str, digest: str) -> dict` (DocSummary; used by adopt in Task 6)
  - `ops._extract(kind: str, filename: str, mime: str, path: Path) -> tuple[str, str, int | None]`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doc_library_upload.py
"""Upload pipeline (spec §2): original + companion note, dedupe, clashes, failure keeps file."""
import io
from pathlib import Path

import pytest

from ghostbrain.api.repo import projects
from ghostbrain.api.repo.doc_library import index, notes, ops
from ghostbrain.api.repo.doc_library.errors import Conflict, InvalidPath, TooLarge
from tests.doc_library_helpers import lib_vault  # noqa: F401

PROOT = "20-contexts/work/projects/payments/docs"


@pytest.fixture
def fake_extract(monkeypatch):
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda name, mime, src: f"text of {name}")
    monkeypatch.setattr(ops, "_pdf_pages", lambda path: 24)


def test_upload_pdf_writes_original_and_note(lib_vault: Path, fake_extract):
    s = ops.upload("work", "payments", "specs", "Payments API v2.pdf", "application/pdf", b"%PDF-1")
    folder = lib_vault / PROOT / "specs"
    assert (folder / "Payments API v2.pdf").read_bytes() == b"%PDF-1"
    note = folder / notes.note_name("Payments API v2", s["doc_id"])
    front, body = notes.read_note(note)
    assert front["kind"] == "pdf" and front["pages"] == 24 and front["project"] == "payments"
    assert front["index_status"] == "ok" and len(front["doc_id"]) == 12
    assert body.strip() == "text of Payments API v2.pdf"
    assert s["title"] == "Payments API v2" and s["duplicate"] is False and s["folder"] == "specs"


def test_upload_kinds(lib_vault: Path, fake_extract):
    img = ops.upload("work", None, "", "flow.png", "image/png", b"\x89PNG")
    assert notes.read_note(lib_vault / img["note_path"])[1].strip() == "a diagram"
    md = ops.upload("work", None, "", "runbook.md", "", b"# Runbook")
    assert notes.read_note(lib_vault / md["note_path"])[1].strip() == "# Runbook"
    z = ops.upload("work", None, "", "bundle.zip", "application/zip", b"PK")
    assert z["kind"] == "opaque" and z["index_status"] == "ok"
    assert notes.read_note(lib_vault / z["note_path"])[1].strip() == ""


def test_duplicate_same_scope_returns_existing_other_scope_is_new(lib_vault: Path, fake_extract):
    a = ops.upload("work", "payments", "", "a.pdf", "", b"same")
    again = ops.upload("work", "payments", "other", "renamed.pdf", "", b"same")
    assert again["duplicate"] is True and again["doc_id"] == a["doc_id"]
    assert not (lib_vault / PROOT / "other").exists()
    b = ops.upload("work", "claims", "", "a.pdf", "", b"same")
    assert b["duplicate"] is False and b["doc_id"] != a["doc_id"]
    assert Path(b["note_path"]).name != Path(a["note_path"]).name


def test_name_clash_gets_suffix(lib_vault: Path, fake_extract):
    ops.upload("work", None, "", "a.pdf", "", b"one")
    s = ops.upload("work", None, "", "a.pdf", "", b"two")
    assert s["original"] == "a (2).pdf"


def test_hostile_filename_stays_in_folder(lib_vault: Path, fake_extract):
    s = ops.upload("work", None, "x", "../../evil.pdf", "", b"e")
    assert s["original_path"] == "20-contexts/work/docs/x/evil.pdf"
    with pytest.raises(InvalidPath):
        ops.upload("work", None, "../escape", "a.pdf", "", b"e")


def test_extraction_failure_keeps_original(lib_vault: Path, monkeypatch):
    def boom(*a):
        raise RuntimeError("corrupt")
    monkeypatch.setattr(ops.attachment_extract, "extract_text", boom)
    s = ops.upload("work", None, "", "bad.pdf", "", b"%PDF-broken")
    assert s["index_status"] == "failed"
    assert (lib_vault / s["original_path"]).read_bytes() == b"%PDF-broken"


def test_limits_and_archived(lib_vault: Path, fake_extract):
    with pytest.raises(TooLarge):
        ops.upload("work", None, "", "big.txt", "", b"x" * 1_000_001)
    projects.update_project("work", "claims", archived=True)
    with pytest.raises(Conflict):
        ops.upload("work", "claims", "", "a.pdf", "", b"x")
    assert index.all_docs() == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev --extra api pytest tests/test_doc_library_upload.py -q`
Expected: FAIL with `ImportError: cannot import name 'ops'`

- [ ] **Step 3: Add the dependency**

Edit `pyproject.toml` to add `"send2trash>=1.8",` under `dependencies` (after `"openpyxl>=3.1",`), then run `uv lock` if a `uv.lock` exists (`ls uv.lock`) and `uv sync --extra dev --extra api`.

- [ ] **Step 4: Implement `ops.py` (upload part)**

```python
# ghostbrain/api/repo/doc_library/ops.py
"""Doc operations: upload, move, rename, delete, reindex, adopt (spec §2)."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from pathlib import Path

from send2trash import send2trash  # noqa: F401  (used by delete/remove_orphan, Task 6)

from ghostbrain.api.repo import attachment_caption, attachment_extract, file_kinds
from ghostbrain.api.repo.doc_library import index, notes, scope
from ghostbrain.api.repo.doc_library.errors import TooLarge

log = logging.getLogger("ghostbrain.doc_library")

_NO_TEXT_IMAGE = "(image — no readable text extracted)"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _pdf_pages(path: Path) -> int | None:
    try:
        from pypdf import PdfReader  # noqa: PLC0415

        return len(PdfReader(str(path)).pages)
    except Exception:  # noqa: BLE001 — page count is cosmetic
        return None


def _extract(kind: str, filename: str, mime: str, path: Path) -> tuple[str, str, int | None]:
    """(body, index_status, pages). Never raises: any failure → ("", "failed", None)."""
    try:
        if kind == "opaque":
            return "", "ok", None
        if kind == "text":
            return file_kinds.text_body(filename, path.read_bytes()), "ok", None
        if kind == "image":
            return attachment_caption.caption_image(path) or _NO_TEXT_IMAGE, "ok", None
        body = attachment_extract.extract_text(filename, mime, path)
        return body, "ok", _pdf_pages(path) if kind == "pdf" else None
    except Exception as e:  # noqa: BLE001 — a broken file must never lose the original
        log.warning("indexing %s failed: %s", path.name, e)
        return "", "failed", None


def _fresh_id(folder: Path, title: str) -> str:
    known = index.all_docs()
    while True:
        doc_id = notes.new_doc_id()
        if doc_id not in known and not (folder / notes.note_name(title, doc_id)).exists():
            return doc_id


def _index_original(
    orig: Path, *, context: str, project: str | None, title: str, mime: str, kind: str, digest: str
) -> dict:
    doc_id = _fresh_id(orig.parent, title)
    body, status, pages = _extract(kind, orig.name, mime, orig)
    front: dict = {
        "doc_id": doc_id,
        "source": notes.SOURCE,
        "title": title,
        "original": orig.name,
        "kind": kind,
        "mime": mime,
        "size": orig.stat().st_size,
        "sha256": digest,
        "created": _now(),
        "context": context,
    }
    if project:
        front["project"] = project
    if pages:
        front["pages"] = pages
    front["index_status"] = status
    notes.write_atomic(orig.parent / notes.note_name(title, doc_id), notes.render(front, body))
    index.invalidate()
    return index.summary(index.get(doc_id))


def upload(
    context: str, project: str | None, folder: str, filename: str, mime: str, content: bytes
) -> dict:
    name = notes.safe_filename(filename)
    kind = file_kinds.classify(name, mime) or "opaque"
    cap = file_kinds.cap_for(kind)
    if len(content) > cap:
        raise TooLarge(f"{name} is larger than {cap // 1_000_000} MB")
    root = scope.scope_root(context, project, for_write=True)
    target = scope.resolve_in(root, folder)
    digest = hashlib.sha256(content).hexdigest()
    for e in index.all_docs().values():
        if e.context == context and e.project == (project or None) and e.front.get("sha256") == digest:
            return {**index.summary(e), "duplicate": True}
    target.mkdir(parents=True, exist_ok=True)
    orig = notes.unique_child(target, name)
    orig.write_bytes(content)
    s = _index_original(
        orig, context=context, project=project or None, title=Path(name).stem,
        mime=mime, kind=kind, digest=digest,
    )
    return {**s, "duplicate": False}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run --extra dev --extra api pytest tests/test_doc_library_upload.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock ghostbrain/api/repo/doc_library/ops.py tests/test_doc_library_upload.py
git commit -m "feat(library): upload pipeline with dedupe, clash suffixes and failure-safe indexing

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

(If there's no `uv.lock`, drop it from `git add`.)

---

### Task 5: Move, rename, delete, reindex

**Files:**
- Modify: `ghostbrain/api/repo/doc_library/ops.py`
- Test: `tests/test_doc_library_ops.py`

**Interfaces:**
- Produces:
  - `ops.move(doc_id: str, context: str, project: str | None, folder: str) -> dict`
  - `ops.rename(doc_id: str, title: str) -> dict`
  - `ops.delete(doc_id: str) -> None`
  - `ops.reindex(doc_id: str) -> dict`
  - All return a DocSummary.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doc_library_ops.py
"""Move / rename / delete / reindex (spec §2, §7)."""
from pathlib import Path

import pytest

from ghostbrain.api.repo import projects
from ghostbrain.api.repo.doc_library import index, notes, ops
from ghostbrain.api.repo.doc_library.errors import Conflict, InvalidRequest
from tests.doc_library_helpers import lib_vault  # noqa: F401


@pytest.fixture(autouse=True)
def fake_extract(monkeypatch):
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda n, m, s: "body")
    monkeypatch.setattr(ops, "_pdf_pages", lambda p: 3)


def test_move_across_projects_keeps_note_basename(lib_vault: Path):
    s = ops.upload("work", "payments", "specs", "a.pdf", "", b"a")
    note_name = Path(s["note_path"]).name
    m = ops.move(s["doc_id"], "work", "claims", "inbox/2026")
    assert m["project"] == "claims" and m["folder"] == "inbox/2026"
    assert Path(m["note_path"]).name == note_name
    assert not (lib_vault / s["original_path"]).exists()
    assert not (lib_vault / s["note_path"]).exists()
    front, _ = notes.read_note(lib_vault / m["note_path"])
    assert front["project"] == "claims" and front["context"] == "work"
    u = ops.move(s["doc_id"], "personal", None, "")
    assert u["project"] is None
    assert "project" not in notes.read_note(lib_vault / u["note_path"])[0]


def test_move_clash_renames_original(lib_vault: Path):
    ops.upload("work", None, "", "a.pdf", "", b"one")
    s = ops.upload("work", None, "sub", "a.pdf", "", b"two")
    m = ops.move(s["doc_id"], "work", None, "")
    assert m["original"] == "a (2).pdf"


def test_move_rolls_back_when_note_write_fails(lib_vault: Path, monkeypatch):
    s = ops.upload("work", None, "", "a.pdf", "", b"one")
    def boom(path, text):
        raise OSError("disk full")
    monkeypatch.setattr(ops.notes, "write_atomic", boom)
    with pytest.raises(OSError):
        ops.move(s["doc_id"], "work", "payments", "")
    assert (lib_vault / s["original_path"]).read_bytes() == b"one"
    assert (lib_vault / s["note_path"]).exists()
    assert not (lib_vault / "20-contexts/work/projects/payments/docs/a.pdf").exists()


def test_move_into_archived_is_conflict(lib_vault: Path):
    s = ops.upload("work", None, "", "a.pdf", "", b"one")
    projects.update_project("work", "claims", archived=True)
    with pytest.raises(Conflict):
        ops.move(s["doc_id"], "work", "claims", "")


def test_rename_keeps_note_and_extension(lib_vault: Path):
    s = ops.upload("work", None, "", "a.pdf", "", b"one")
    r = ops.rename(s["doc_id"], "Payments API v3")
    assert r["title"] == "Payments API v3" and r["original"] == "Payments API v3.pdf"
    assert r["note_path"] == s["note_path"]
    assert ops.rename(s["doc_id"], "Same.pdf")["original"] == "Same.pdf"
    with pytest.raises(InvalidRequest):
        ops.rename(s["doc_id"], "a/b")


def test_delete_sends_both_files_to_trash(lib_vault: Path, monkeypatch):
    trashed = []
    monkeypatch.setattr(ops, "send2trash", lambda p: (trashed.append(Path(p).name), Path(p).unlink()))
    s = ops.upload("work", None, "", "a.pdf", "", b"one")
    ops.delete(s["doc_id"])
    assert sorted(trashed) == sorted(["a.pdf", Path(s["note_path"]).name])
    assert index.all_docs() == {}


def test_reindex_recovers_failed(lib_vault: Path, monkeypatch):
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda *a: (_ for _ in ()).throw(RuntimeError()))
    s = ops.upload("work", None, "", "a.pdf", "", b"one")
    assert s["index_status"] == "failed"
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda *a: "fixed")
    r = ops.reindex(s["doc_id"])
    assert r["index_status"] == "ok" and r["pages"] == 3
    assert notes.read_note(lib_vault / r["note_path"])[1].strip() == "fixed"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev --extra api pytest tests/test_doc_library_ops.py -q`
Expected: FAIL with `AttributeError: module ... has no attribute 'move'`

- [ ] **Step 3: Implement**

In `ops.py`, change the `send2trash` import line to plain `from send2trash import send2trash`. Add `import shutil` to the stdlib imports, and change the errors import to `from ghostbrain.api.repo.doc_library.errors import Conflict, InvalidRequest, TooLarge`. Then append:

```python
def _with_scope(front: dict, context: str, project: str | None) -> dict:
    out = {k: v for k, v in front.items() if k != "project"}
    out["context"] = context
    if project:
        out["project"] = project
    return out


def move(doc_id: str, context: str, project: str | None, folder: str) -> dict:
    e = index.get(doc_id)
    root = scope.scope_root(context, project, for_write=True)
    dest = scope.resolve_in(root, folder)
    if dest.resolve() == e.note.parent.resolve():
        return index.summary(e)
    dest.mkdir(parents=True, exist_ok=True)
    new_note = dest / e.note.name
    if new_note.exists():
        raise Conflict(f"a note named {e.note.name} already exists there")
    new_orig = notes.unique_child(dest, e.original.name)
    # Original first, then the note; undo the original move if the note step fails.
    shutil.move(str(e.original), str(new_orig))
    try:
        front = _with_scope({**e.front, "original": new_orig.name}, context, project or None)
        notes.write_atomic(new_note, notes.render(front, e.body))
        e.note.unlink()
    except Exception:
        if new_note.exists() and e.note.exists():
            new_note.unlink()
        shutil.move(str(new_orig), str(e.original))
        raise
    finally:
        index.invalidate()
    return index.summary(index.get(doc_id))


def rename(doc_id: str, title: str) -> dict:
    title = title.strip()
    if not title or "/" in title or "\\" in title:
        raise InvalidRequest("title must be non-empty and contain no path separators")
    e = index.get(doc_id)
    ext = e.original.suffix
    if ext and title.lower().endswith(ext.lower()):
        title = title[: -len(ext)].strip() or title
    want = notes.safe_filename(f"{title}{ext}")
    new_orig = e.original
    if want != e.original.name:
        new_orig = notes.unique_child(e.original.parent, want)
        e.original.rename(new_orig)
    try:
        front = {**e.front, "title": title, "original": new_orig.name}
        notes.write_atomic(e.note, notes.render(front, e.body))
    except Exception:
        if new_orig != e.original:
            new_orig.rename(e.original)
        raise
    finally:
        index.invalidate()
    return index.summary(index.get(doc_id))


def delete(doc_id: str) -> None:
    e = index.get(doc_id)
    send2trash(str(e.original))
    send2trash(str(e.note))
    index.invalidate()


def reindex(doc_id: str) -> dict:
    e = index.get(doc_id)
    kind = str(e.front.get("kind") or "opaque")
    body, status, pages = _extract(kind, e.original.name, str(e.front.get("mime") or ""), e.original)
    front = {**e.front, "index_status": status}
    if pages:
        front["pages"] = pages
    notes.write_atomic(e.note, notes.render(front, body))
    index.invalidate()
    return index.summary(index.get(doc_id))
```

- [ ] **Step 4: Run tests**

Run: `uv run --extra dev --extra api pytest tests/test_doc_library_ops.py tests/test_doc_library_upload.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/doc_library/ops.py tests/test_doc_library_ops.py
git commit -m "feat(library): move (with rollback), rename, trash-delete and reindex docs

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Folders, attention repairs, search

**Files:**
- Create: `ghostbrain/api/repo/doc_library/folders.py`, `ghostbrain/api/repo/doc_library/search.py`
- Modify: `ghostbrain/api/repo/doc_library/ops.py` (adds `adopt`, `remove_orphan`)
- Test: `tests/test_doc_library_folders.py`, `tests/test_doc_library_attention.py`, `tests/test_doc_library_search.py`

**Interfaces:**
- Produces:
  - `folders.create(context: str, project: str | None, path: str) -> dict` → `{"context", "project", "path"}`
  - `folders.move(src: tuple[str, str | None, str], dst: tuple[str, str | None, str]) -> dict` (each tuple is `(context, project, path)`)
  - `folders.delete(context: str, project: str | None, path: str) -> None`
  - `ops.adopt(context: str, project: str | None, folder: str, name: str) -> dict`
  - `ops.remove_orphan(doc_id: str) -> None`
  - `search.search(q: str, project: str | None = None, limit: int = 20) -> list[dict]` (`project` is the `"context/slug"` id, ranked first)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_doc_library_folders.py
"""Folder create / move / delete-empty (spec §2)."""
from pathlib import Path

import pytest

from ghostbrain.api.repo import projects
from ghostbrain.api.repo.doc_library import folders, index, notes, ops
from ghostbrain.api.repo.doc_library.errors import Conflict, InvalidPath, InvalidRequest, NotFound
from tests.doc_library_helpers import lib_vault  # noqa: F401

W = "20-contexts/work/docs"


@pytest.fixture(autouse=True)
def fake_extract(monkeypatch):
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda *a: "body")


def test_create_with_keep_and_conflict(lib_vault: Path):
    assert folders.create("work", None, "specs/v2") == {"context": "work", "project": None, "path": "specs/v2"}
    assert (lib_vault / W / "specs/v2/.keep").exists()
    with pytest.raises(Conflict):
        folders.create("work", None, "specs/v2")
    with pytest.raises(InvalidRequest):
        folders.create("work", None, "")
    with pytest.raises(InvalidPath):
        folders.create("work", None, "../x")


def test_rename_within_scope(lib_vault: Path):
    folders.create("work", None, "a")
    folders.move(("work", None, "a"), ("work", None, "b/c"))
    assert (lib_vault / W / "b/c").is_dir() and not (lib_vault / W / "a").exists()


def test_move_across_projects_restamps_notes(lib_vault: Path):
    s = ops.upload("work", "payments", "specs/deep", "a.pdf", "", b"a")
    folders.move(("work", "payments", "specs"), ("work", "claims", "from-payments"))
    e = index.get(s["doc_id"])
    assert e.project == "claims" and e.folder == "from-payments/deep"
    assert notes.read_note(e.note)[0]["project"] == "claims"


def test_move_guards(lib_vault: Path):
    folders.create("work", None, "a/b")
    folders.create("work", None, "x")
    with pytest.raises(InvalidRequest):
        folders.move(("work", None, "a"), ("work", None, "a/b/inside"))
    with pytest.raises(Conflict):
        folders.move(("work", None, "a"), ("work", None, "x"))
    with pytest.raises(NotFound):
        folders.move(("work", None, "nope"), ("work", None, "y"))
    with pytest.raises(InvalidRequest):
        folders.move(("work", None, ""), ("work", None, "y"))
    projects.update_project("work", "claims", archived=True)
    with pytest.raises(Conflict):
        folders.move(("work", None, "x"), ("work", "claims", "x"))


def test_delete_only_empty(lib_vault: Path):
    folders.create("work", None, "empty")
    folders.delete("work", None, "empty")
    assert not (lib_vault / W / "empty").exists()
    ops.upload("work", None, "full", "a.pdf", "", b"a")
    with pytest.raises(Conflict):
        folders.delete("work", None, "full")
    with pytest.raises(NotFound):
        folders.delete("work", None, "ghost")
```

```python
# tests/test_doc_library_attention.py
"""Needs-attention repairs: adopt unclaimed originals, remove orphan notes."""
from pathlib import Path

import pytest

from ghostbrain.api.repo.doc_library import index, ops
from ghostbrain.api.repo.doc_library.errors import Conflict, NotFound
from tests.doc_library_helpers import lib_vault  # noqa: F401


@pytest.fixture(autouse=True)
def fake_extract(monkeypatch):
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda *a: "body")


def test_adopt_unclaimed_original(lib_vault: Path):
    d = lib_vault / "20-contexts/work/docs/inbox"
    d.mkdir(parents=True)
    (d / "Dropped.pdf").write_bytes(b"%PDF")
    index.invalidate()
    assert [a["kind"] for a in index.attention()] == ["unclaimed_original"]
    s = ops.adopt("work", None, "inbox", "Dropped.pdf")
    assert s["title"] == "Dropped" and s["kind"] == "pdf" and s["folder"] == "inbox"
    assert index.attention() == []
    with pytest.raises(Conflict):
        ops.adopt("work", None, "inbox", "Dropped.pdf")
    with pytest.raises(NotFound):
        ops.adopt("work", None, "inbox", "missing.pdf")


def test_remove_orphan(lib_vault: Path, monkeypatch):
    s = ops.upload("work", None, "", "a.pdf", "", b"a")
    (lib_vault / s["original_path"]).unlink()
    index.invalidate()
    assert list(index.orphans()) == [s["doc_id"]]
    trashed = []
    monkeypatch.setattr(ops, "send2trash", lambda p: (trashed.append(p), Path(p).unlink()))
    ops.remove_orphan(s["doc_id"])
    assert index.orphans() == {} and len(trashed) == 1
    with pytest.raises(NotFound):
        ops.remove_orphan(s["doc_id"])
```

```python
# tests/test_doc_library_search.py
"""Fuzzy title/path search, preferred project first."""
from pathlib import Path

import pytest

from ghostbrain.api.repo.doc_library import ops, search
from tests.doc_library_helpers import lib_vault  # noqa: F401


@pytest.fixture(autouse=True)
def seeded(lib_vault: Path, monkeypatch):
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda *a: "body")
    ops.upload("work", "payments", "specs", "Rate card Q4.xlsx", "", b"1")
    ops.upload("work", "claims", "", "Interchange rates 2026.pdf", "", b"2")
    ops.upload("personal", None, "rates", "Mortgage.pdf", "", b"3")
    ops.upload("work", None, "", "Unrelated.pdf", "", b"4")


def test_ranking_and_project_preference():
    titles = [s["title"] for s in search.search("rate")]
    assert titles[:2] == ["Interchange rates 2026", "Rate card Q4"] or titles[:2] == ["Rate card Q4", "Interchange rates 2026"]
    assert "Mortgage" in titles  # path match ("rates/")
    assert "Unrelated" not in titles
    preferred = [s["title"] for s in search.search("rate", project="work/claims")]
    assert preferred[0] == "Interchange rates 2026"


def test_subsequence_and_empty():
    assert [s["title"] for s in search.search("rcq4")] == ["Rate card Q4"]
    assert search.search("   ") == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --extra dev --extra api pytest tests/test_doc_library_folders.py tests/test_doc_library_attention.py tests/test_doc_library_search.py -q`
Expected: FAIL (missing modules/attributes)

- [ ] **Step 3: Implement `folders.py`**

```python
# ghostbrain/api/repo/doc_library/folders.py
"""Folder operations inside docs roots (spec §2). Folders are plain directories."""
from __future__ import annotations

import shutil
from pathlib import Path

from ghostbrain.api.repo.doc_library import index, notes, scope
from ghostbrain.api.repo.doc_library.errors import Conflict, InvalidRequest, NotFound


def _ref(context: str, project: str | None, path: str) -> dict:
    return {"context": context, "project": project or None, "path": path}


def create(context: str, project: str | None, path: str) -> dict:
    root = scope.scope_root(context, project, for_write=True)
    cleaned = scope.clean_rel(path)
    if not cleaned:
        raise InvalidRequest("folder path is required")
    d = scope.resolve_in(root, cleaned)
    if d.exists():
        raise Conflict(f"folder already exists: {cleaned}")
    d.mkdir(parents=True)
    (d / notes.KEEP).touch()  # keeps empty folders alive through sync tools
    index.invalidate()
    return _ref(context, project, cleaned)


def _restamp(folder: Path, context: str, project: str | None) -> None:
    for p in folder.rglob("*.md"):
        parsed = notes.read_note(p)
        if parsed is None:
            continue
        front, body = parsed
        front = {k: v for k, v in front.items() if k != "project"}
        front["context"] = context
        if project:
            front["project"] = project
        notes.write_atomic(p, notes.render(front, body))


def move(src: tuple[str, str | None, str], dst: tuple[str, str | None, str]) -> dict:
    s_ctx, s_proj, s_path = src
    d_ctx, d_proj, d_path = dst
    s_root = scope.scope_root(s_ctx, s_proj, for_write=True)
    d_root = scope.scope_root(d_ctx, d_proj, for_write=True)
    s_clean, d_clean = scope.clean_rel(s_path), scope.clean_rel(d_path)
    if not s_clean or not d_clean:
        raise InvalidRequest("a docs root itself cannot be moved")
    s_dir = scope.resolve_in(s_root, s_clean)
    d_dir = scope.resolve_in(d_root, d_clean)
    if not s_dir.is_dir():
        raise NotFound(f"folder not found: {s_clean}")
    sr, dr = s_dir.resolve(), d_dir.resolve()
    if dr == sr or sr in dr.parents:
        raise InvalidRequest("cannot move a folder into itself")
    if d_dir.exists():
        raise Conflict(f"folder already exists: {d_clean}")
    d_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(s_dir), str(d_dir))
    if (s_ctx, s_proj or None) != (d_ctx, d_proj or None):
        _restamp(d_dir, d_ctx, d_proj or None)
    index.invalidate()
    return _ref(d_ctx, d_proj, d_clean)


def delete(context: str, project: str | None, path: str) -> None:
    root = scope.scope_root(context, project, for_write=True)
    cleaned = scope.clean_rel(path)
    if not cleaned:
        raise InvalidRequest("a docs root itself cannot be deleted")
    d = scope.resolve_in(root, cleaned)
    if not d.is_dir():
        raise NotFound(f"folder not found: {cleaned}")
    if any(c.name != notes.KEEP for c in d.iterdir()):
        raise Conflict(f"folder is not empty: {cleaned}")
    (d / notes.KEEP).unlink(missing_ok=True)
    d.rmdir()
    index.invalidate()
```

- [ ] **Step 4: Add `adopt` and `remove_orphan` to `ops.py`**

Add `import mimetypes` to the stdlib imports and `NotFound` to the errors import, then append:

```python
def adopt(context: str, project: str | None, folder: str, name: str) -> dict:
    root = scope.scope_root(context, project, for_write=True)
    d = scope.resolve_in(root, folder)
    p = d / notes.safe_filename(name)
    if not p.is_file() or p.name.endswith(".md") and notes.read_note(p) is not None:
        raise NotFound(f"file not found: {name}")
    if any(e.original.resolve() == p.resolve() for e in index.all_docs().values()):
        raise Conflict(f"already in the library: {name}")
    mime = mimetypes.guess_type(p.name)[0] or ""
    kind = file_kinds.classify(p.name, mime) or "opaque"
    content = p.read_bytes()
    if len(content) > file_kinds.cap_for(kind):
        raise TooLarge(f"{p.name} is larger than {file_kinds.cap_for(kind) // 1_000_000} MB")
    return _index_original(
        p, context=context, project=project or None, title=p.stem, mime=mime, kind=kind,
        digest=hashlib.sha256(content).hexdigest(),
    )


def remove_orphan(doc_id: str) -> None:
    note = index.orphans().get(doc_id)
    if note is None:
        raise NotFound(f"no orphan note for {doc_id}")
    send2trash(str(note))
    index.invalidate()
```

- [ ] **Step 5: Implement `search.py`**

```python
# ghostbrain/api/repo/doc_library/search.py
"""Fuzzy doc search over title and folder path. Feeds ⌘P and the /docs picker."""
from __future__ import annotations

from ghostbrain.api.repo.doc_library import index


def _subsequence(needle: str, hay: str) -> bool:
    it = iter(hay)
    return all(ch in it for ch in needle)


def search(q: str, project: str | None = None, limit: int = 20) -> list[dict]:
    needle = q.strip().lower()
    if not needle:
        return []
    scored: list[tuple[int, str, dict]] = []
    for e in index.all_docs().values():
        s = index.summary(e)
        title = s["title"].lower()
        path = f"{s['folder']}/{s['original']}".lower()
        if title.startswith(needle):
            score = 4
        elif needle in title:
            score = 3
        elif needle in path:
            score = 2
        elif _subsequence(needle.replace(" ", ""), title.replace(" ", "")):
            score = 1
        else:
            continue
        if project and e.project and f"{e.context}/{e.project}" == project:
            score += 5
        scored.append((-score, title, s))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [s for _, _, s in scored[:limit]]
```

- [ ] **Step 6: Run tests**

Run: `uv run --extra dev --extra api pytest tests/test_doc_library_*.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add ghostbrain/api/repo/doc_library tests/test_doc_library_folders.py tests/test_doc_library_attention.py tests/test_doc_library_search.py
git commit -m "feat(library): folder ops, needs-attention repairs and fuzzy search

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: `/v1/library` routes

**Files:**
- Create: `ghostbrain/api/models/library.py`, `ghostbrain/api/routes/library.py`
- Modify: `ghostbrain/api/main.py` (import `library as library_routes` next to the other route imports; `app.include_router(library_routes.router)` after `projects_routes`)
- Test: `tests/test_library_routes.py`

**Interfaces:**
- Consumes: everything in `doc_library`.
- Produces: the HTTP API that the renderer hooks call (Task 10):

```
GET    /v1/library/tree?context=&project=          → LibraryTree
POST   /v1/library/docs                            UploadDocRequest → DocSummary + duplicate
GET    /v1/library/docs/{doc_id}                   → DocDetail
PATCH  /v1/library/docs/{doc_id}                   {title?} | {context, project?, folder?} → DocSummary
DELETE /v1/library/docs/{doc_id}                   → {"deleted": true}
POST   /v1/library/docs/{doc_id}/reindex           → DocSummary
POST   /v1/library/folders                         {context, project?, path} → FolderRef
PATCH  /v1/library/folders                         {from: FolderRef, to: FolderRef} → FolderRef
DELETE /v1/library/folders?context=&project=&path= → {"deleted": true}
POST   /v1/library/attention/adopt                 {context, project?, folder, name} → DocSummary
POST   /v1/library/attention/remove-orphan         {doc_id} → {"removed": true}
GET    /v1/library/search?q=&project=              → DocSummary[]
```

(Folder delete takes query params because the renderer's `del()` helper sends no body. Spec §3 is updated to match in Step 6.)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_library_routes.py
"""/v1/library routes: status-code mapping + shapes."""
import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app
from ghostbrain.api.repo.doc_library import ops
from tests.doc_library_helpers import lib_vault  # noqa: F401

H = {"Authorization": "Bearer t"}


@pytest.fixture
def client(lib_vault: Path, monkeypatch):
    monkeypatch.setattr(ops.attachment_extract, "extract_text", lambda *a: "body text")
    return TestClient(create_app("t"))


def _up(client, name="a.pdf", content=b"%PDF", **kw):
    body = {"context": "work", "project": "payments", "folder": "specs", "name": name,
            "mime": "", "content_b64": base64.b64encode(content).decode(), **kw}
    return client.post("/v1/library/docs", json=body, headers=H)


def test_upload_tree_detail_search(client):
    r = _up(client)
    assert r.status_code == 200
    doc = r.json()
    assert doc["duplicate"] is False and doc["kind"] == "pdf"
    tree = client.get("/v1/library/tree", headers=H).json()
    payments = next(s for s in tree["scopes"] if s["project"] == "payments")
    assert payments["folders"][0]["docs"][0]["doc_id"] == doc["doc_id"]
    detail = client.get(f"/v1/library/docs/{doc['doc_id']}", headers=H).json()
    assert detail["body"].strip() == "body text"
    hits = client.get("/v1/library/search", params={"q": "a"}, headers=H).json()
    assert [h["doc_id"] for h in hits] == [doc["doc_id"]]


def test_patch_move_and_rename(client):
    doc = _up(client).json()
    r = client.patch(f"/v1/library/docs/{doc['doc_id']}", json={"title": "Spec"}, headers=H)
    assert r.json()["original"] == "Spec.pdf"
    r = client.patch(f"/v1/library/docs/{doc['doc_id']}",
                     json={"context": "work", "project": "claims", "folder": "in"}, headers=H)
    assert r.json()["project"] == "claims"
    assert client.patch(f"/v1/library/docs/{doc['doc_id']}", json={}, headers=H).status_code == 422


def test_folder_routes(client):
    assert client.post("/v1/library/folders", json={"context": "work", "path": "a"}, headers=H).status_code == 200
    r = client.patch("/v1/library/folders",
                     json={"from": {"context": "work", "path": "a"}, "to": {"context": "work", "path": "b"}},
                     headers=H)
    assert r.json() == {"context": "work", "project": None, "path": "b"}
    assert client.delete("/v1/library/folders", params={"context": "work", "path": "b"}, headers=H).json() == {"deleted": True}


def test_error_mapping(client):
    assert _up(client, content=b"x" * 20_000_001).status_code == 413
    assert _up(client, folder="../x").status_code == 400
    assert client.post("/v1/library/docs", json={"context": "work", "folder": "", "name": "a",
                       "content_b64": "!!!"}, headers=H).status_code == 400
    assert client.get("/v1/library/docs/ffffffffffff", headers=H).status_code == 404
    _up(client, name="b.pdf", content=b"b", folder="full")
    assert client.delete("/v1/library/folders",
                         params={"context": "work", "project": "payments", "path": "full"},
                         headers=H).status_code == 409
    assert _up(client, project="ghost").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --extra dev --extra api pytest tests/test_library_routes.py -q`
Expected: FAIL (404s, because the router isn't registered)

- [ ] **Step 3: Implement the models**

```python
# ghostbrain/api/models/library.py
"""Docs library schemas (spec §3)."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DocSummary(BaseModel):
    doc_id: str
    title: str
    kind: str
    mime: str
    size: int
    created: str
    context: str
    project: str | None = None
    folder: str
    original: str
    original_path: str
    note_path: str
    index_status: str
    pages: int | None = None
    excerpt: str = ""


class UploadDocResponse(DocSummary):
    duplicate: bool


class DocDetail(DocSummary):
    body: str


class FolderNode(BaseModel):
    name: str
    path: str
    folders: list["FolderNode"]
    docs: list[DocSummary]


class DocScope(BaseModel):
    context: str
    project: str | None = None
    name: str
    archived: bool
    folders: list[FolderNode]
    docs: list[DocSummary]


class AttentionItem(BaseModel):
    kind: Literal["orphan_note", "unclaimed_original", "index_failed"]
    context: str
    project: str | None = None
    folder: str
    name: str
    doc_id: str | None = None


class LibraryTree(BaseModel):
    scopes: list[DocScope]
    attention: list[AttentionItem]


class UploadDocRequest(BaseModel):
    context: str
    project: str | None = None
    folder: str = ""
    name: str = Field(..., min_length=1, max_length=255)
    mime: str = Field("", max_length=255)
    content_b64: str


class PatchDocRequest(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=200)
    context: str | None = None
    project: str | None = None
    folder: str = ""


class FolderRef(BaseModel):
    context: str
    project: str | None = None
    path: str


class MoveFolderRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    from_: FolderRef = Field(..., alias="from")
    to: FolderRef


class AdoptRequest(BaseModel):
    context: str
    project: str | None = None
    folder: str = ""
    name: str = Field(..., min_length=1, max_length=255)


class RemoveOrphanRequest(BaseModel):
    doc_id: str
```

- [ ] **Step 4: Implement the routes**

```python
# ghostbrain/api/routes/library.py
"""Docs library API (spec §3). Library errors carry their own HTTP status."""
import base64
import binascii

from fastapi import APIRouter, HTTPException, Query

from ghostbrain.api.models.library import (
    AdoptRequest,
    DocDetail,
    DocSummary,
    FolderRef,
    LibraryTree,
    MoveFolderRequest,
    PatchDocRequest,
    RemoveOrphanRequest,
    UploadDocRequest,
    UploadDocResponse,
)
from ghostbrain.api.repo.doc_library import folders, index, ops, search
from ghostbrain.api.repo.doc_library.errors import LibraryError

router = APIRouter(prefix="/v1/library", tags=["library"])


def _run(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except LibraryError as e:
        raise HTTPException(status_code=e.status, detail=str(e)) from e


@router.get("/tree", response_model=LibraryTree)
def get_tree(context: str | None = None, project: str | None = None) -> dict:
    return _run(index.tree, context, project)


@router.post("/docs", response_model=UploadDocResponse)
def upload_doc(payload: UploadDocRequest) -> dict:
    try:
        content = base64.b64decode(payload.content_b64, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail=f"invalid base64: {payload.name}")
    return _run(
        ops.upload, payload.context, payload.project, payload.folder,
        payload.name, payload.mime, content,
    )


@router.get("/docs/{doc_id}", response_model=DocDetail)
def get_doc(doc_id: str) -> dict:
    return _run(lambda: index.detail(index.get(doc_id)))


@router.patch("/docs/{doc_id}", response_model=DocSummary)
def patch_doc(doc_id: str, payload: PatchDocRequest) -> dict:
    if payload.title is None and payload.context is None:
        raise HTTPException(status_code=422, detail="nothing to change: pass title and/or context")
    result: dict = {}
    if payload.title is not None:
        result = _run(ops.rename, doc_id, payload.title)
    if payload.context is not None:
        result = _run(ops.move, doc_id, payload.context, payload.project, payload.folder)
    return result


@router.delete("/docs/{doc_id}")
def delete_doc(doc_id: str) -> dict:
    _run(ops.delete, doc_id)
    return {"deleted": True}


@router.post("/docs/{doc_id}/reindex", response_model=DocSummary)
def reindex_doc(doc_id: str) -> dict:
    return _run(ops.reindex, doc_id)


@router.post("/folders", response_model=FolderRef)
def create_folder(payload: FolderRef) -> dict:
    return _run(folders.create, payload.context, payload.project, payload.path)


@router.patch("/folders", response_model=FolderRef)
def move_folder(payload: MoveFolderRequest) -> dict:
    src, dst = payload.from_, payload.to
    return _run(
        folders.move, (src.context, src.project, src.path), (dst.context, dst.project, dst.path)
    )


@router.delete("/folders")
def delete_folder(context: str, path: str, project: str | None = Query(None)) -> dict:
    _run(folders.delete, context, project, path)
    return {"deleted": True}


@router.post("/attention/adopt", response_model=DocSummary)
def adopt(payload: AdoptRequest) -> dict:
    return _run(ops.adopt, payload.context, payload.project, payload.folder, payload.name)


@router.post("/attention/remove-orphan")
def remove_orphan(payload: RemoveOrphanRequest) -> dict:
    _run(ops.remove_orphan, payload.doc_id)
    return {"removed": True}


@router.get("/search", response_model=list[DocSummary])
def search_docs(q: str = "", project: str | None = None) -> list[dict]:
    return search.search(q, project)
```

Register it in `ghostbrain/api/main.py`: add `from ghostbrain.api.routes import library as library_routes` in alphabetical position among the route imports, and `app.include_router(library_routes.router)` right after `app.include_router(projects_routes.router)`.

- [ ] **Step 5: Run backend tests and lint**

Run: `uv run --extra dev --extra api pytest tests/test_library_routes.py tests/test_doc_library_*.py tests/test_file_kinds.py ghostbrain/api/tests/test_chat_attachments.py -q && uv run --extra dev ruff check ghostbrain/api tests/test_library_routes.py tests/test_doc_library_*.py`
Expected: PASS, ruff clean.

- [ ] **Step 6: Align spec §3 with folder-delete query params**

In `docs/superpowers/specs/2026-10-09-docs-library-design.md`, replace the line `POST|PATCH|DELETE /v1/library/folders ...` block entry `DELETE /v1/library/folders                         {context, project?, path}  (empty only)` with `DELETE /v1/library/folders?context=&project=&path=   (empty only)`.

- [ ] **Step 7: Commit**

```bash
git add ghostbrain/api/models/library.py ghostbrain/api/routes/library.py ghostbrain/api/main.py tests/test_library_routes.py docs/superpowers/specs/2026-10-09-docs-library-design.md
git commit -m "feat(library): /v1/library API

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: `gbdoc://` protocol + reveal-in-folder

**Files:**
- Create: `desktop/src/main/doc-protocol.ts`, `desktop/src/main/__tests__/doc-protocol.test.ts`
- Modify: `desktop/src/main/assets.ts` (`registerGbAssetScheme` array), `desktop/src/main/index.ts` (around lines 200–220 and 254–256), `desktop/src/preload/index.ts` (shell block, line ~13), `desktop/src/shared/types.ts` (`GbBridge.shell`), `desktop/src/renderer/test/setup.ts` (stub `shell`), `desktop/src/renderer/index.html` (CSP)

**Interfaces:**
- Produces:
  - `resolveDocPath(vaultRoot: string, vaultRel: string): string | null`
  - `registerDocProtocol(getVaultRoot: () => string): void`
  - URL shape `gbdoc://doc/<encodeURIComponent per segment of original_path>`
  - `window.gb.shell.showItemInFolder(absPath: string): Promise<{ ok: boolean; error?: string }>`

- [ ] **Step 1: Write the failing test**

```ts
// desktop/src/main/__tests__/doc-protocol.test.ts
import { describe, expect, it, vi } from 'vitest';
import { resolve } from 'node:path';

vi.mock('electron', () => ({ protocol: { handle: vi.fn() }, net: { fetch: vi.fn() } }));

import { resolveDocPath } from '../doc-protocol';

const V = '/tmp/vault';

describe('resolveDocPath', () => {
  it('allows files inside context and project docs roots', () => {
    expect(resolveDocPath(V, '20-contexts/work/docs/a.pdf')).toBe(resolve(V, '20-contexts/work/docs/a.pdf'));
    expect(resolveDocPath(V, '20-contexts/work/projects/pay/docs/specs/a b.pdf')).toBe(
      resolve(V, '20-contexts/work/projects/pay/docs/specs/a b.pdf'),
    );
  });

  it('rejects anything outside a docs root', () => {
    for (const rel of [
      '20-contexts/work/note.md',
      '90-meta/projects.json',
      '20-contexts/work/docs/../secret.md',
      '20-contexts/work/docs/./a.pdf',
      '/etc/passwd',
      '20-contexts/work/projects/pay/other/a.pdf',
      '20-contexts/work/docs',
    ]) {
      expect(resolveDocPath(V, rel)).toBeNull();
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/main/__tests__/doc-protocol.test.ts`
Expected: FAIL (`Cannot find module '../doc-protocol'`)

- [ ] **Step 3: Implement the protocol**

```ts
// desktop/src/main/doc-protocol.ts
import { protocol, net } from 'electron';
import { resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';

// Docs roots only: 20-contexts/{ctx}/docs/… and 20-contexts/{ctx}/projects/{slug}/docs/…
const DOC_REL_RE = /^20-contexts\/[^/]+\/(?:projects\/[^/]+\/)?docs\/.+/;

/** Resolve a vault-relative path served by gbdoc://, or null if it is not inside a docs root. */
export function resolveDocPath(vaultRoot: string, vaultRel: string): string | null {
  const rel = vaultRel.replace(/\\/g, '/');
  if (rel.startsWith('/') || !DOC_REL_RE.test(rel)) return null;
  if (rel.split('/').some((s) => s === '..' || s === '.' || s === '')) return null;
  const root = resolve(vaultRoot);
  const abs = resolve(root, rel);
  if (!abs.startsWith(root + sep)) return null;
  return abs;
}

/** gbdoc://doc/<vault-relative path>. CORS-enabled so pdf.js can fetch it from the renderer origin. */
export function registerDocProtocol(getVaultRoot: () => string): void {
  protocol.handle('gbdoc', async (request) => {
    const vaultRoot = getVaultRoot();
    if (!vaultRoot) return new Response('vault not configured', { status: 404 });
    const rel = decodeURIComponent(new URL(request.url).pathname).replace(/^\/+/, '');
    const abs = resolveDocPath(vaultRoot, rel);
    if (!abs) return new Response('forbidden', { status: 403 });
    try {
      const res = await net.fetch(pathToFileURL(abs).toString());
      const headers = new Headers(res.headers);
      headers.set('Access-Control-Allow-Origin', '*');
      return new Response(res.body, { status: res.status, headers });
    } catch {
      return new Response('not found', { status: 404 });
    }
  });
}
```

- [ ] **Step 4: Register the scheme in the existing privileged-scheme call**

In `desktop/src/main/assets.ts`, extend the array passed to `protocol.registerSchemesAsPrivileged` inside `registerGbAssetScheme()`:

```ts
    {
      scheme: 'gbdoc',
      privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true, corsEnabled: true },
    },
```

(One shared registration call. Don't add a separate `registerSchemesAsPrivileged`.)

- [ ] **Step 5: Wire main + the `showItemInFolder` IPC**

In `desktop/src/main/index.ts`:
- `import { registerDocProtocol } from './doc-protocol';`
- in `app.whenReady().then(...)`, after `registerAssetProtocol(vaultRoot);`, add `registerDocProtocol(vaultRoot);`
- after the `gb:shell:openPath` handler, add:

```ts
ipcMain.handle('gb:shell:showItemInFolder', (_e, p: unknown) => {
  if (typeof p !== 'string' || p === '') {
    return { ok: false, error: 'showItemInFolder: path must be a non-empty string' };
  }
  const vaultPath = settings.getAll().vaultPath;
  const normalized = p.replace(/\\/g, '/');
  const allowed = (vaultPath ?? '').replace(/\\/g, '/');
  if (!allowed || !normalized.startsWith(allowed + '/')) {
    return { ok: false, error: 'showItemInFolder: only paths inside the vault are allowed' };
  }
  shell.showItemInFolder(p);
  return { ok: true };
});
```

In `desktop/src/preload/index.ts` shell block, add `showItemInFolder: (path: string) => ipcRenderer.invoke('gb:shell:showItemInFolder', path),`. In `desktop/src/shared/types.ts` `GbBridge.shell`, add `showItemInFolder(path: string): Promise<{ ok: boolean; error?: string }>;`. In `desktop/src/renderer/test/setup.ts`, add `showItemInFolder: async () => ({ ok: true }),` to the stub's `shell`.

In `desktop/src/renderer/index.html` CSP: `img-src 'self' data: gbasset: gbdoc: plugin:;` and `connect-src 'self' gbdoc: plugin:;`.

- [ ] **Step 6: Run tests + typecheck**

Run: `cd desktop && npx vitest run src/main/__tests__/doc-protocol.test.ts src/main/__tests__/assets.test.ts && npm run typecheck`
Expected: PASS, no type errors.

- [ ] **Step 7: Commit**

```bash
git add desktop/src/main/doc-protocol.ts desktop/src/main/__tests__/doc-protocol.test.ts desktop/src/main/assets.ts desktop/src/main/index.ts desktop/src/preload/index.ts desktop/src/shared/types.ts desktop/src/renderer/test/setup.ts desktop/src/renderer/index.html
git commit -m "feat(desktop): gbdoc:// protocol for library originals + reveal-in-folder IPC

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Types, hooks and the docs store

**Files:**
- Modify: `desktop/src/shared/api-types.ts` (append), `desktop/src/renderer/lib/api/hooks.ts` (append a `// ── Docs library ──` section, extend the `import type` list)
- Create: `desktop/src/renderer/stores/docs.ts`, `desktop/src/renderer/components/docs/kinds.ts`
- Test: `desktop/src/renderer/__tests__/docs-store.test.ts`

**Interfaces:**
- Produces (types):

```ts
export type DocKind = 'pdf' | 'image' | 'docx' | 'xlsx' | 'text' | 'opaque';
export interface DocSummary {
  doc_id: string; title: string; kind: DocKind; mime: string; size: number; created: string;
  context: string; project: string | null; folder: string; original: string;
  original_path: string; note_path: string; index_status: 'ok' | 'failed' | 'pending';
  pages: number | null; excerpt: string;
}
export interface UploadDocResponse extends DocSummary { duplicate: boolean }
export interface DocDetail extends DocSummary { body: string }
export interface DocFolderNode { name: string; path: string; folders: DocFolderNode[]; docs: DocSummary[] }
export interface DocScope { context: string; project: string | null; name: string; archived: boolean; folders: DocFolderNode[]; docs: DocSummary[] }
export interface AttentionItem { kind: 'orphan_note' | 'unclaimed_original' | 'index_failed'; context: string; project: string | null; folder: string; name: string; doc_id: string | null }
export interface LibraryTree { scopes: DocScope[]; attention: AttentionItem[] }
export interface FolderRef { context: string; project: string | null; path: string }
export interface UploadDocRequest { context: string; project: string | null; folder: string; name: string; mime: string; content_b64: string }
```

- Produces (hooks, all mutations invalidate `['library']`): `useLibraryTree()`, `useDocDetail(docId: string | null)`, `useLibrarySearch(q: string, project?: string | null)`, `useUploadDoc()`, `usePatchDoc()` (vars `{ docId, title?, context?, project?, folder? }`), `useDeleteDoc()`, `useReindexDoc()`, `useCreateFolder()`, `useMoveFolder()` (vars `{ from: FolderRef; to: FolderRef }`), `useDeleteFolder()`, `useAdoptOriginal()`, `useRemoveOrphan()`.
- Produces (store `useDocs`):
  - `selection: DocSelection` where `DocSelection = { type: 'folder'; ref: FolderRef } | { type: 'doc'; docId: string } | { type: 'attention' } | null`
  - `select(s: DocSelection)`
  - `viewMode(key: string): 'list' | 'grid'`, `setViewMode(key: string, mode: 'list' | 'grid')` (persisted in localStorage `gb.docs.viewModes`, guarded by try/catch)
  - `uploads: UploadGhost[]` where `UploadGhost = { id: string; name: string; size: number; key: string; status: 'uploading' | 'error'; error?: string }`
  - `addUpload(g: Omit<UploadGhost, 'status'>)`, `failUpload(id: string, error: string)`, `removeUpload(id: string)`
  - `quickOpen: boolean`, `setQuickOpen(b: boolean)`
- Produces (`kinds.ts`): `KIND_META: Record<DocKind, { fg: string; bg: string }>`, `kindLabel(doc: Pick<DocSummary, 'kind' | 'original'>): string`, `docUrl(originalPath: string): string`, `folderKey(ref: FolderRef): string`, `formatSize(bytes: number): string`, `vaultAbs(vaultPath: string, rel: string): string`.

- [ ] **Step 1: Write the failing test**

```ts
// desktop/src/renderer/__tests__/docs-store.test.ts
import { beforeEach, describe, expect, it } from 'vitest';
import { useDocs } from '../stores/docs';
import { docUrl, folderKey, formatSize, kindLabel } from '../components/docs/kinds';

describe('docs store', () => {
  beforeEach(() => {
    localStorage.clear();
    useDocs.setState({ selection: null, uploads: [], quickOpen: false, viewModes: {} });
  });

  it('persists the view mode per folder', () => {
    expect(useDocs.getState().viewMode('work/_/specs')).toBe('list');
    useDocs.getState().setViewMode('work/_/specs', 'grid');
    expect(useDocs.getState().viewMode('work/_/specs')).toBe('grid');
    expect(JSON.parse(localStorage.getItem('gb.docs.viewModes')!)).toEqual({ 'work/_/specs': 'grid' });
  });

  it('tracks upload ghosts', () => {
    const s = useDocs.getState();
    s.addUpload({ id: 'u1', name: 'a.pdf', size: 3, key: 'k' });
    s.failUpload('u1', 'too large');
    expect(useDocs.getState().uploads).toEqual([
      { id: 'u1', name: 'a.pdf', size: 3, key: 'k', status: 'error', error: 'too large' },
    ]);
    useDocs.getState().removeUpload('u1');
    expect(useDocs.getState().uploads).toEqual([]);
  });
});

describe('kinds helpers', () => {
  it('builds keys, urls and labels', () => {
    expect(folderKey({ context: 'work', project: null, path: 'a/b' })).toBe('work/_/a/b');
    expect(docUrl('20-contexts/work/docs/a b.pdf')).toBe('gbdoc://doc/20-contexts/work/docs/a%20b.pdf');
    expect(kindLabel({ kind: 'text', original: 'x.md' })).toBe('MD');
    expect(kindLabel({ kind: 'text', original: 'x.py' })).toBe('PY');
    expect(kindLabel({ kind: 'image', original: 'x.png' })).toBe('IMG');
    expect(formatSize(2_150_331)).toBe('2.2 MB');
    expect(formatSize(900)).toBe('900 B');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/docs-store.test.ts`
Expected: FAIL (modules missing)

- [ ] **Step 3: Implement types, kinds, store and hooks**

Append the types block above to `desktop/src/shared/api-types.ts`.

```ts
// desktop/src/renderer/components/docs/kinds.ts
import type { DocKind, DocSummary, FolderRef } from '../../../shared/api-types';

export const KIND_META: Record<DocKind, { fg: string; bg: string }> = {
  pdf: { fg: 'var(--pill-oxblood-fg)', bg: 'rgba(255,107,90,.14)' },
  image: { fg: 'var(--pill-water-fg)', bg: 'rgba(127,179,213,.14)' },
  docx: { fg: '#A9B6FF', bg: 'rgba(140,160,255,.14)' },
  xlsx: { fg: 'var(--pill-moss-fg)', bg: 'rgba(162,199,149,.14)' },
  text: { fg: 'var(--neon-ink)', bg: 'rgba(197,255,61,.12)' },
  opaque: { fg: 'var(--ink-2)', bg: 'var(--hairline)' },
};

export function kindLabel(doc: Pick<DocSummary, 'kind' | 'original'>): string {
  switch (doc.kind) {
    case 'pdf':
      return 'PDF';
    case 'image':
      return 'IMG';
    case 'docx':
      return 'DOCX';
    case 'xlsx':
      return 'XLSX';
    default: {
      const ext = doc.original.includes('.') ? doc.original.split('.').pop()!.toLowerCase() : '';
      if (ext === 'md' || ext === 'markdown') return 'MD';
      if (doc.kind === 'text') return ext ? ext.slice(0, 4).toUpperCase() : 'TXT';
      return ext ? ext.slice(0, 4).toUpperCase() : 'FILE';
    }
  }
}

export function docUrl(originalPath: string): string {
  return `gbdoc://doc/${originalPath.split('/').map(encodeURIComponent).join('/')}`;
}

export function folderKey(ref: FolderRef): string {
  return `${ref.context}/${ref.project ?? '_'}/${ref.path}`;
}

export function formatSize(bytes: number): string {
  if (bytes < 1000) return `${bytes} B`;
  if (bytes < 1_000_000) return `${(bytes / 1000).toFixed(0)} KB`;
  return `${(bytes / 1_000_000).toFixed(1)} MB`;
}

export function vaultAbs(vaultPath: string, rel: string): string {
  return `${vaultPath.replace(/[\\/]+$/, '')}/${rel}`;
}
```

```ts
// desktop/src/renderer/stores/docs.ts
import { create } from 'zustand';
import type { FolderRef } from '../../shared/api-types';

export type DocSelection =
  | { type: 'folder'; ref: FolderRef }
  | { type: 'doc'; docId: string }
  | { type: 'attention' }
  | null;

export interface UploadGhost {
  id: string;
  name: string;
  size: number;
  key: string;
  status: 'uploading' | 'error';
  error?: string;
}

type ViewMode = 'list' | 'grid';
const VIEW_KEY = 'gb.docs.viewModes';

function loadViewModes(): Record<string, ViewMode> {
  try {
    return JSON.parse(localStorage.getItem(VIEW_KEY) ?? '{}') as Record<string, ViewMode>;
  } catch {
    return {};
  }
}

interface DocsState {
  selection: DocSelection;
  select: (s: DocSelection) => void;
  viewModes: Record<string, ViewMode>;
  viewMode: (key: string) => ViewMode;
  setViewMode: (key: string, mode: ViewMode) => void;
  uploads: UploadGhost[];
  addUpload: (g: Omit<UploadGhost, 'status'>) => void;
  failUpload: (id: string, error: string) => void;
  removeUpload: (id: string) => void;
  quickOpen: boolean;
  setQuickOpen: (b: boolean) => void;
}

export const useDocs = create<DocsState>((set, get) => ({
  selection: null,
  select: (selection) => set({ selection }),
  viewModes: loadViewModes(),
  viewMode: (key) => get().viewModes[key] ?? 'list',
  setViewMode: (key, mode) => {
    const viewModes = { ...get().viewModes, [key]: mode };
    set({ viewModes });
    try {
      localStorage.setItem(VIEW_KEY, JSON.stringify(viewModes));
    } catch {
      // per-viewer convenience only
    }
  },
  uploads: [],
  addUpload: (g) => set({ uploads: [...get().uploads, { ...g, status: 'uploading' }] }),
  failUpload: (id, error) =>
    set({ uploads: get().uploads.map((u) => (u.id === id ? { ...u, status: 'error', error } : u)) }),
  removeUpload: (id) => set({ uploads: get().uploads.filter((u) => u.id !== id) }),
  quickOpen: false,
  setQuickOpen: (quickOpen) => set({ quickOpen }),
}));
```

Append to `desktop/src/renderer/lib/api/hooks.ts` (add the new types to the `import type` list at the top):

```ts
// ── Docs library ─────────────────────────────────────────────────────────────

const invalidateLibrary = (qc: ReturnType<typeof useQueryClient>) =>
  qc.invalidateQueries({ queryKey: ['library'] });

export function useLibraryTree() {
  return useQuery({
    queryKey: ['library', 'tree'],
    queryFn: () => get<LibraryTree>('/v1/library/tree'),
    staleTime: 5_000,
  });
}

export function useDocDetail(docId: string | null) {
  return useQuery({
    queryKey: ['library', 'doc', docId],
    queryFn: () => get<DocDetail>(`/v1/library/docs/${docId}`),
    enabled: !!docId,
  });
}

export function useLibrarySearch(q: string, project?: string | null) {
  const params = new URLSearchParams({ q });
  if (project) params.set('project', project);
  return useQuery({
    queryKey: ['library', 'search', q, project ?? null],
    queryFn: () => get<DocSummary[]>(`/v1/library/search?${params.toString()}`),
    enabled: q.trim().length > 0,
    staleTime: 5_000,
  });
}

export function useUploadDoc() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (req: UploadDocRequest) => post<UploadDocResponse>('/v1/library/docs', req),
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function usePatchDoc() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ docId, ...body }: { docId: string; title?: string; context?: string; project?: string | null; folder?: string }) =>
      patch<DocSummary>(`/v1/library/docs/${docId}`, body),
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function useDeleteDoc() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => del(`/v1/library/docs/${docId}`),
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function useReindexDoc() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => post<DocSummary>(`/v1/library/docs/${docId}/reindex`),
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function useCreateFolder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ref: FolderRef) => post<FolderRef>('/v1/library/folders', ref),
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function useMoveFolder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { from: FolderRef; to: FolderRef }) => patch<FolderRef>('/v1/library/folders', vars),
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function useDeleteFolder() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (ref: FolderRef) => {
      const params = new URLSearchParams({ context: ref.context, path: ref.path });
      if (ref.project) params.set('project', ref.project);
      return del(`/v1/library/folders?${params.toString()}`);
    },
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function useAdoptOriginal() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { context: string; project: string | null; folder: string; name: string }) =>
      post<DocSummary>('/v1/library/attention/adopt', vars),
    onSuccess: () => invalidateLibrary(qc),
  });
}

export function useRemoveOrphan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (docId: string) => post('/v1/library/attention/remove-orphan', { doc_id: docId }),
    onSuccess: () => invalidateLibrary(qc),
  });
}
```

- [ ] **Step 4: Run test + typecheck**

Run: `cd desktop && npx vitest run src/renderer/__tests__/docs-store.test.ts && npm run typecheck`
Expected: PASS, no type errors.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/shared/api-types.ts desktop/src/renderer/lib/api/hooks.ts desktop/src/renderer/stores/docs.ts desktop/src/renderer/components/docs/kinds.ts desktop/src/renderer/__tests__/docs-store.test.ts
git commit -m "feat(docs): library API types, query hooks and docs store

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Tree model + DocTree with drag-and-drop

**Files:**
- Create: `desktop/src/renderer/components/docs/tree-model.ts`, `desktop/src/renderer/components/docs/KindChip.tsx`, `desktop/src/renderer/components/docs/DocTree.tsx`
- Test: `desktop/src/renderer/__tests__/docs-tree-model.test.ts`, `desktop/src/renderer/__tests__/DocTree.test.tsx`

**Interfaces:**
- Consumes: types + `kinds.ts` from Task 9.
- Produces:
  - `tree-model.ts`:
    - `DRAG_MIME = 'application/x-gb-library'`
    - `type DragPayload = { type: 'doc'; docId: string } | { type: 'folder'; ref: FolderRef }`
    - `encodeDrag(p: DragPayload): string`
    - `decodeDrag(raw: string): DragPayload | null`
    - `countDocs(node: { docs: unknown[]; folders: DocFolderNode[] }): number`
    - `findFolder(tree: LibraryTree, ref: FolderRef): DocFolderNode | null` (`path ''` returns a synthetic root node built from the scope)
    - `findDoc(tree: LibraryTree, docId: string): DocSummary | null`
    - `groupByContext(scopes: DocScope[]): Array<{ context: string; scopes: DocScope[] }>` (unfiled scope first within each context)
    - `isInside(child: FolderRef, parent: FolderRef): boolean`
  - `<KindChip doc={...} />`
  - `<DocTree tree selection onSelect onMoveDoc onMoveFolder onUploadFiles onCreateFolder onRenameFolder onDeleteFolder />`:
    - `onSelect(s: DocSelection)`
    - `onMoveDoc(docId: string, to: FolderRef)`
    - `onMoveFolder(from: FolderRef, to: FolderRef)` (the `to` path = target path + `/` + source folder name)
    - `onUploadFiles(files: File[], to: FolderRef)`
    - `onCreateFolder(ref: FolderRef)`
    - `onRenameFolder(from: FolderRef, to: FolderRef)`
    - `onDeleteFolder(ref: FolderRef)`

- [ ] **Step 1: Write the failing tests**

```ts
// desktop/src/renderer/__tests__/docs-tree-model.test.ts
import { describe, expect, it } from 'vitest';
import { countDocs, decodeDrag, encodeDrag, findDoc, findFolder, groupByContext, isInside } from '../components/docs/tree-model';
import { libraryFixture } from './fixtures/library';

describe('tree-model', () => {
  it('round-trips drag payloads and rejects junk', () => {
    const p = { type: 'doc' as const, docId: 'aaaaaaaaaaaa' };
    expect(decodeDrag(encodeDrag(p))).toEqual(p);
    expect(decodeDrag('nope')).toBeNull();
    expect(decodeDrag('{"type":"x"}')).toBeNull();
  });

  it('finds folders and docs, counts recursively', () => {
    const t = libraryFixture();
    const specs = findFolder(t, { context: 'work', project: 'payments', path: 'specs' });
    expect(specs?.docs.map((d) => d.title)).toEqual(['Payments API v2']);
    const root = findFolder(t, { context: 'work', project: 'payments', path: '' });
    expect(root?.folders.map((f) => f.name)).toEqual(['diagrams', 'specs']);
    expect(countDocs(root!)).toBe(3);
    expect(findDoc(t, 'bbbbbbbbbbbb')?.title).toBe('Settlement flow');
  });

  it('groups unfiled first and detects nesting', () => {
    const groups = groupByContext(libraryFixture().scopes);
    expect(groups[0]!.context).toBe('work');
    expect(groups[0]!.scopes.map((s) => s.name)).toEqual(['unfiled', 'Payments']);
    const a = { context: 'w', project: null, path: 'a' };
    expect(isInside({ ...a, path: 'a/b' }, a)).toBe(true);
    expect(isInside({ ...a, path: 'ab' }, a)).toBe(false);
  });
});
```

Create the shared fixture used by every renderer test in this plan:

```ts
// desktop/src/renderer/__tests__/fixtures/library.ts
import type { DocSummary, LibraryTree } from '../../../shared/api-types';

export function doc(over: Partial<DocSummary>): DocSummary {
  return {
    doc_id: 'aaaaaaaaaaaa', title: 'Payments API v2', kind: 'pdf', mime: 'application/pdf',
    size: 2_150_331, created: '2026-10-07T10:00:00+00:00', context: 'work', project: 'payments',
    folder: 'specs', original: 'Payments API v2.pdf',
    original_path: '20-contexts/work/projects/payments/docs/specs/Payments API v2.pdf',
    note_path: '20-contexts/work/projects/payments/docs/specs/payments-api-v2-aaaaaa.md',
    index_status: 'ok', pages: 24, excerpt: 'Idempotency keys required on POST.', ...over,
  };
}

export function libraryFixture(): LibraryTree {
  return {
    scopes: [
      { context: 'work', project: null, name: 'unfiled', archived: false, folders: [], docs: [] },
      {
        context: 'work', project: 'payments', name: 'Payments', archived: false,
        docs: [doc({ doc_id: 'cccccccccccc', title: 'Rate card Q4', kind: 'xlsx', folder: '', original: 'Rate card Q4.xlsx', original_path: '20-contexts/work/projects/payments/docs/Rate card Q4.xlsx' })],
        folders: [
          { name: 'diagrams', path: 'diagrams', folders: [], docs: [doc({ doc_id: 'bbbbbbbbbbbb', title: 'Settlement flow', kind: 'image', folder: 'diagrams', original: 'Settlement flow.png', original_path: '20-contexts/work/projects/payments/docs/diagrams/Settlement flow.png', pages: null })] },
          { name: 'specs', path: 'specs', folders: [], docs: [doc({})] },
        ],
      },
      { context: 'personal', project: null, name: 'unfiled', archived: false, folders: [], docs: [] },
    ],
    attention: [],
  };
}
```

```tsx
// desktop/src/renderer/__tests__/DocTree.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DocTree } from '../components/docs/DocTree';
import { DRAG_MIME, encodeDrag } from '../components/docs/tree-model';
import { libraryFixture } from './fixtures/library';

function dt(data: Record<string, string>, files: File[] = []) {
  return { getData: (k: string) => data[k] ?? '', setData: vi.fn(), types: Object.keys(data).concat(files.length ? ['Files'] : []), files, dropEffect: 'move', effectAllowed: 'all' };
}

function setup(over: Partial<React.ComponentProps<typeof DocTree>> = {}) {
  const props = {
    tree: libraryFixture(), selection: null, onSelect: vi.fn(), onMoveDoc: vi.fn(), onMoveFolder: vi.fn(),
    onUploadFiles: vi.fn(), onCreateFolder: vi.fn(), onRenameFolder: vi.fn(), onDeleteFolder: vi.fn(), ...over,
  };
  render(<DocTree {...props} />);
  return props;
}

describe('DocTree', () => {
  it('renders contexts, projects with counts, folders and kind chips', () => {
    setup();
    expect(screen.getByText('work')).toBeTruthy();
    expect(screen.getByText('Payments')).toBeTruthy();
    expect(screen.getByTestId('count-work/payments/')).toHaveTextContent('3');
    expect(screen.getByText('specs')).toBeTruthy();
    expect(screen.getByText('Payments API v2')).toBeTruthy();
    expect(screen.getAllByText('PDF').length).toBeGreaterThan(0);
  });

  it('selects folders and docs', () => {
    const p = setup();
    fireEvent.click(screen.getByText('specs'));
    expect(p.onSelect).toHaveBeenCalledWith({ type: 'folder', ref: { context: 'work', project: 'payments', path: 'specs' } });
    fireEvent.click(screen.getByText('Payments API v2'));
    expect(p.onSelect).toHaveBeenCalledWith({ type: 'doc', docId: 'aaaaaaaaaaaa' });
  });

  it('moves a dropped doc into the target folder, across projects too', () => {
    const p = setup();
    const target = screen.getByTestId('folder-work/_/');
    fireEvent.dragOver(target, { dataTransfer: dt({ [DRAG_MIME]: '' }) });
    expect(target.className).toContain('outline-dashed');
    fireEvent.drop(target, { dataTransfer: dt({ [DRAG_MIME]: encodeDrag({ type: 'doc', docId: 'aaaaaaaaaaaa' }) }) });
    expect(p.onMoveDoc).toHaveBeenCalledWith('aaaaaaaaaaaa', { context: 'work', project: null, path: '' });
  });

  it('moves a folder under another, refusing to drop into itself', () => {
    const p = setup();
    const specs = { context: 'work', project: 'payments', path: 'specs' };
    fireEvent.drop(screen.getByTestId('folder-work/payments/diagrams'), { dataTransfer: dt({ [DRAG_MIME]: encodeDrag({ type: 'folder', ref: specs }) }) });
    expect(p.onMoveFolder).toHaveBeenCalledWith(specs, { context: 'work', project: 'payments', path: 'diagrams/specs' });
    fireEvent.drop(screen.getByTestId('folder-work/payments/specs'), { dataTransfer: dt({ [DRAG_MIME]: encodeDrag({ type: 'folder', ref: specs }) }) });
    expect(p.onMoveFolder).toHaveBeenCalledTimes(1);
  });

  it('uploads OS files dropped on a folder', () => {
    const p = setup();
    const f = new File(['x'], 'a.pdf');
    fireEvent.drop(screen.getByTestId('folder-work/payments/specs'), { dataTransfer: dt({}, [f]) });
    expect(p.onUploadFiles).toHaveBeenCalledWith([f], { context: 'work', project: 'payments', path: 'specs' });
  });

  it('creates a subfolder inline', () => {
    const p = setup();
    fireEvent.click(screen.getByLabelText('new folder in work/payments/specs'));
    const input = screen.getByPlaceholderText('folder name');
    fireEvent.change(input, { target: { value: 'v2' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(p.onCreateFolder).toHaveBeenCalledWith({ context: 'work', project: 'payments', path: 'specs/v2' });
  });

  it('shows the needs-attention row only when there are items', () => {
    const tree = libraryFixture();
    tree.attention = [{ kind: 'orphan_note', context: 'work', project: null, folder: '', name: 'x.md', doc_id: 'dddddddddddd' }];
    const p = setup({ tree });
    fireEvent.click(screen.getByText('needs attention'));
    expect(p.onSelect).toHaveBeenCalledWith({ type: 'attention' });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd desktop && npx vitest run src/renderer/__tests__/docs-tree-model.test.ts src/renderer/__tests__/DocTree.test.tsx`
Expected: FAIL (modules missing)

- [ ] **Step 3: Implement `tree-model.ts` and `KindChip.tsx`**

```ts
// desktop/src/renderer/components/docs/tree-model.ts
import type { DocFolderNode, DocScope, DocSummary, FolderRef, LibraryTree } from '../../../shared/api-types';

export const DRAG_MIME = 'application/x-gb-library';

export type DragPayload = { type: 'doc'; docId: string } | { type: 'folder'; ref: FolderRef };

export function encodeDrag(p: DragPayload): string {
  return JSON.stringify(p);
}

export function decodeDrag(raw: string): DragPayload | null {
  try {
    const p = JSON.parse(raw) as DragPayload;
    if (p?.type === 'doc' && typeof p.docId === 'string') return p;
    if (p?.type === 'folder' && typeof p.ref?.context === 'string' && typeof p.ref.path === 'string') return p;
  } catch {
    // not ours
  }
  return null;
}

export function countDocs(node: { docs: unknown[]; folders: DocFolderNode[] }): number {
  return node.docs.length + node.folders.reduce((n, f) => n + countDocs(f), 0);
}

function scopeOf(tree: LibraryTree, ref: Pick<FolderRef, 'context' | 'project'>): DocScope | undefined {
  return tree.scopes.find((s) => s.context === ref.context && s.project === ref.project);
}

export function findFolder(tree: LibraryTree, ref: FolderRef): DocFolderNode | null {
  const scope = scopeOf(tree, ref);
  if (!scope) return null;
  let node: DocFolderNode = { name: scope.name, path: '', folders: scope.folders, docs: scope.docs };
  if (!ref.path) return node;
  for (const part of ref.path.split('/')) {
    const next = node.folders.find((f) => f.name === part);
    if (!next) return null;
    node = next;
  }
  return node;
}

export function findDoc(tree: LibraryTree, docId: string): DocSummary | null {
  const walk = (n: { docs: DocSummary[]; folders: DocFolderNode[] }): DocSummary | null =>
    n.docs.find((d) => d.doc_id === docId) ?? n.folders.map(walk).find(Boolean) ?? null;
  for (const s of tree.scopes) {
    const hit = walk(s);
    if (hit) return hit;
  }
  return null;
}

export function groupByContext(scopes: DocScope[]): Array<{ context: string; scopes: DocScope[] }> {
  const out: Array<{ context: string; scopes: DocScope[] }> = [];
  for (const s of scopes) {
    let g = out.find((x) => x.context === s.context);
    if (!g) out.push((g = { context: s.context, scopes: [] }));
    g.scopes.push(s);
  }
  for (const g of out) g.scopes.sort((a, b) => (a.project === null ? -1 : b.project === null ? 1 : 0));
  return out;
}

export function isInside(child: FolderRef, parent: FolderRef): boolean {
  if (child.context !== parent.context || child.project !== parent.project) return false;
  return child.path === parent.path || child.path.startsWith(`${parent.path}/`);
}
```

```tsx
// desktop/src/renderer/components/docs/KindChip.tsx
import type { DocSummary } from '../../../shared/api-types';
import { KIND_META, kindLabel } from './kinds';

export function KindChip({ doc }: { doc: Pick<DocSummary, 'kind' | 'original'> }) {
  const meta = KIND_META[doc.kind] ?? KIND_META.opaque;
  return (
    <span
      className="shrink-0 rounded-[4px] px-[5px] py-[2px] font-mono text-9 font-semibold tracking-[0.06em]"
      style={{ color: meta.fg, background: meta.bg }}
    >
      {kindLabel(doc)}
    </span>
  );
}
```

- [ ] **Step 4: Implement `DocTree.tsx`**

```tsx
// desktop/src/renderer/components/docs/DocTree.tsx
import { useState } from 'react';
import type { DocFolderNode, DocScope, DocSummary, FolderRef, LibraryTree } from '../../../shared/api-types';
import type { DocSelection } from '../../stores/docs';
import { Lucide } from '../Lucide';
import { KindChip } from './KindChip';
import { folderKey } from './kinds';
import { countDocs, decodeDrag, DRAG_MIME, encodeDrag, groupByContext, isInside } from './tree-model';

interface Props {
  tree: LibraryTree;
  selection: DocSelection;
  onSelect: (s: DocSelection) => void;
  onMoveDoc: (docId: string, to: FolderRef) => void;
  onMoveFolder: (from: FolderRef, to: FolderRef) => void;
  onUploadFiles: (files: File[], to: FolderRef) => void;
  onCreateFolder: (ref: FolderRef) => void;
  onRenameFolder: (from: FolderRef, to: FolderRef) => void;
  onDeleteFolder: (ref: FolderRef) => void;
}

const PROJECT_DOTS = ['var(--neon)', 'var(--pill-water-fg)', '#F2C14E', 'var(--pill-oxblood-fg)', '#A9B6FF', 'var(--pill-moss-fg)'];

function joinPath(parent: string, name: string): string {
  return parent ? `${parent}/${name}` : name;
}

// Module scope (not inside DocTree) so parent re-renders, e.g. drag hover, don't remount it mid-typing.
function FolderInput({ initial, onDone }: { initial: string; onDone: (v: string | null) => void }) {
  return (
    <input
      autoFocus
      defaultValue={initial}
      placeholder="folder name"
      className="ml-6 w-[calc(100%-1.5rem)] rounded border border-hairline-2 bg-vellum px-2 py-1 text-12 text-ink-0 outline-none focus:border-neon"
      onKeyDown={(e) => {
        if (e.key === 'Enter') onDone((e.target as HTMLInputElement).value.trim() || null);
        if (e.key === 'Escape') onDone(null);
      }}
      onBlur={() => onDone(null)}
    />
  );
}

export function DocTree(props: Props) {
  const { tree, selection, onSelect } = props;
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [dropKey, setDropKey] = useState<string | null>(null);
  const [creatingIn, setCreatingIn] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);

  const toggle = (k: string) => setCollapsed((c) => ({ ...c, [k]: !c[k] }));

  const dropHandlers = (ref: FolderRef, disabled: boolean) => ({
    onDragOver: (e: React.DragEvent) => {
      if (disabled) return;
      e.preventDefault();
      setDropKey(folderKey(ref));
    },
    onDragLeave: () => setDropKey((k) => (k === folderKey(ref) ? null : k)),
    onDrop: (e: React.DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setDropKey(null);
      if (disabled) return;
      const files = Array.from(e.dataTransfer.files ?? []);
      if (files.length) return props.onUploadFiles(files, ref);
      const payload = decodeDrag(e.dataTransfer.getData(DRAG_MIME));
      if (!payload) return;
      if (payload.type === 'doc') return props.onMoveDoc(payload.docId, ref);
      if (isInside(ref, payload.ref)) return;
      const name = payload.ref.path.split('/').pop()!;
      props.onMoveFolder(payload.ref, { ...ref, path: joinPath(ref.path, name) });
    },
  });

  const rowCls = (active: boolean, key: string) =>
    `group flex w-full items-center gap-[7px] rounded-md px-1.5 py-[5px] text-left text-13 ${
      active ? 'bg-neon-mist text-neon' : 'text-ink-1 hover:bg-vellum'
    } ${dropKey === key ? 'outline-dashed outline-1 -outline-offset-1 outline-neon bg-neon-mist/40 text-ink-0' : ''}`;

  const docRow = (d: DocSummary, depth: number) => {
    const active = selection?.type === 'doc' && selection.docId === d.doc_id;
    return (
      <button
        key={d.doc_id}
        type="button"
        draggable
        onDragStart={(e) => {
          e.dataTransfer.setData(DRAG_MIME, encodeDrag({ type: 'doc', docId: d.doc_id }));
          e.dataTransfer.effectAllowed = 'move';
        }}
        onClick={() => onSelect({ type: 'doc', docId: d.doc_id })}
        className={rowCls(active, '')}
        style={{ paddingLeft: 6 + depth * 18 }}
      >
        <KindChip doc={d} />
        <span className="truncate">{d.title}</span>
        {d.index_status === 'failed' && <span className="ml-auto h-1.5 w-1.5 rounded-full bg-[#F2C14E]" title="indexing failed" />}
      </button>
    );
  };

  const folderRows = (scope: DocScope, node: DocFolderNode, depth: number): React.ReactNode => {
    const ref: FolderRef = { context: scope.context, project: scope.project, path: node.path };
    const key = folderKey(ref);
    const open = !collapsed[key];
    const active = selection?.type === 'folder' && folderKey(selection.ref) === key;
    return (
      <div key={key}>
        {renaming === key ? (
          <FolderInput
            initial={node.name}
            onDone={(v) => {
              setRenaming(null);
              if (v && v !== node.name) {
                const parent = node.path.split('/').slice(0, -1).join('/');
                props.onRenameFolder(ref, { ...ref, path: joinPath(parent, v) });
              }
            }}
          />
        ) : (
          <div
            data-testid={`folder-${key}`}
            draggable={!scope.archived}
            onDragStart={(e) => e.dataTransfer.setData(DRAG_MIME, encodeDrag({ type: 'folder', ref }))}
            {...dropHandlers(ref, scope.archived)}
            className={rowCls(active, key)}
            style={{ paddingLeft: 6 + depth * 18 }}
          >
            <button type="button" aria-label={open ? 'collapse' : 'expand'} onClick={() => toggle(key)} className="w-2.5 text-[9px] text-ink-3">
              {open ? '▾' : '▸'}
            </button>
            <button type="button" onClick={() => onSelect({ type: 'folder', ref })} className="flex min-w-0 flex-1 items-center gap-[7px]">
              <Lucide name="folder" size={13} className="shrink-0 opacity-80" />
              <span className="truncate">{node.name}</span>
            </button>
            {!scope.archived && (
              <span className="hidden items-center gap-1 group-hover:flex">
                <button type="button" aria-label={`new folder in ${key}`} onClick={() => setCreatingIn(key)} className="text-ink-3 hover:text-neon"><Lucide name="folder-plus" size={12} /></button>
                <button type="button" aria-label={`rename ${key}`} onClick={() => setRenaming(key)} className="text-ink-3 hover:text-neon"><Lucide name="pencil" size={12} /></button>
                <button type="button" aria-label={`delete ${key}`} onClick={() => props.onDeleteFolder(ref)} className="text-ink-3 hover:text-oxblood"><Lucide name="trash-2" size={12} /></button>
              </span>
            )}
            <span className="ml-auto font-mono text-10 text-ink-3 group-hover:hidden">{countDocs(node)}</span>
          </div>
        )}
        {creatingIn === key && (
          <FolderInput
            initial=""
            onDone={(v) => {
              setCreatingIn(null);
              if (v) props.onCreateFolder({ ...ref, path: joinPath(node.path, v) });
            }}
          />
        )}
        {open && (
          <>
            {node.folders.map((f) => folderRows(scope, f, depth + 1))}
            {node.docs.map((d) => docRow(d, depth + 1))}
          </>
        )}
      </div>
    );
  };

  const scopeRows = (scope: DocScope, i: number) => {
    const ref: FolderRef = { context: scope.context, project: scope.project, path: '' };
    const key = folderKey(ref);
    const open = !collapsed[key];
    const active = selection?.type === 'folder' && folderKey(selection.ref) === key;
    const root: DocFolderNode = { name: scope.name, path: '', folders: scope.folders, docs: scope.docs };
    return (
      <div key={key} className={scope.archived ? 'opacity-50' : ''}>
        <div data-testid={`folder-${key}`} {...dropHandlers(ref, scope.archived)} className={`${rowCls(active, key)} ${scope.project ? 'font-medium text-ink-0' : 'text-ink-2'}`}>
          <button type="button" aria-label={open ? 'collapse' : 'expand'} onClick={() => toggle(key)} className="w-2.5 text-[9px] text-ink-3">
            {open ? '▾' : '▸'}
          </button>
          <button type="button" onClick={() => onSelect({ type: 'folder', ref })} className="flex min-w-0 flex-1 items-center gap-[7px]">
            {scope.project ? (
              <span className="h-[7px] w-[7px] shrink-0 rounded-[2px]" style={{ background: PROJECT_DOTS[i % PROJECT_DOTS.length] }} />
            ) : (
              <Lucide name="inbox" size={13} className="shrink-0 opacity-80" />
            )}
            <span className="truncate">{scope.name}</span>
          </button>
          {!scope.archived && (
            <button type="button" aria-label={`new folder in ${key}`} onClick={() => setCreatingIn(key)} className="hidden text-ink-3 hover:text-neon group-hover:block">
              <Lucide name="folder-plus" size={12} />
            </button>
          )}
          <span data-testid={`count-${scope.context}/${scope.project ?? '_'}/`} className="ml-auto font-mono text-10 text-ink-3 group-hover:hidden">
            {countDocs(root)}
          </span>
        </div>
        {creatingIn === key && (
          <FolderInput initial="" onDone={(v) => { setCreatingIn(null); if (v) props.onCreateFolder({ ...ref, path: v }); }} />
        )}
        {open && (
          <>
            {scope.folders.map((f) => folderRows(scope, f, 1))}
            {scope.docs.map((d) => docRow(d, 1))}
          </>
        )}
      </div>
    );
  };

  let projectIndex = 0;
  return (
    <nav className="flex-1 overflow-y-auto px-2 pb-3" aria-label="docs tree">
      {tree.attention.length > 0 && (
        <button
          type="button"
          onClick={() => onSelect({ type: 'attention' })}
          className={`mb-1 flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-12 ${selection?.type === 'attention' ? 'bg-[rgba(242,193,78,.12)] text-[#F2C14E]' : 'text-[#F2C14E] hover:bg-vellum'}`}
        >
          <Lucide name="triangle-alert" size={13} />
          <span>needs attention</span>
          <span className="ml-auto font-mono text-10">{tree.attention.length}</span>
        </button>
      )}
      {groupByContext(tree.scopes).map((g) => {
        const ctxKey = `ctx:${g.context}`;
        const open = !collapsed[ctxKey];
        return (
          <div key={g.context} className="mt-2">
            <button type="button" onClick={() => toggle(ctxKey)} className="flex w-full items-center gap-[7px] px-1.5 py-1 font-mono text-[10.5px] uppercase tracking-[0.1em] text-ink-2">
              <span className="w-2.5 text-[9px] text-ink-3">{open ? '▾' : '▸'}</span>
              <span>{g.context}</span>
            </button>
            {open && g.scopes.map((s) => scopeRows(s, s.project ? projectIndex++ : 0))}
          </div>
        );
      })}
    </nav>
  );
}
```

- [ ] **Step 5: Run tests + typecheck**

Run: `cd desktop && npx vitest run src/renderer/__tests__/docs-tree-model.test.ts src/renderer/__tests__/DocTree.test.tsx && npm run typecheck`
Expected: PASS. If `toHaveTextContent` is not registered in setup (check `grep -n jest-dom src/renderer/test/setup.ts`), replace it with `expect(screen.getByTestId(...).textContent).toBe('3')`.

- [ ] **Step 6: Commit**

```bash
git add desktop/src/renderer/components/docs/tree-model.ts desktop/src/renderer/components/docs/KindChip.tsx desktop/src/renderer/components/docs/DocTree.tsx desktop/src/renderer/__tests__/docs-tree-model.test.ts desktop/src/renderer/__tests__/DocTree.test.tsx desktop/src/renderer/__tests__/fixtures/library.ts
git commit -m "feat(docs): library tree with drag-and-drop moves, OS file drops and inline folder ops

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 11: pdf.js wrapper, thumbnails, FolderView (list + grid)

**Files:**
- Modify: `desktop/package.json` (dependency `"pdfjs-dist": "4.10.38"`)
- Create: `desktop/src/renderer/components/docs/pdf.ts`, `desktop/src/renderer/components/docs/Thumb.tsx`, `desktop/src/renderer/components/docs/upload.ts`, `desktop/src/renderer/components/docs/FolderView.tsx`
- Test: `desktop/src/renderer/__tests__/FolderView.test.tsx`

**Interfaces:**
- Produces:
  - `pdf.ts`:
    - `loadPdf(url: string): Promise<PdfHandle>` where `PdfHandle = { numPages: number; renderPage(canvas: HTMLCanvasElement, page: number, scale: number): Promise<void> }`
    - `renderThumb(canvas: HTMLCanvasElement, url: string, width: number): Promise<void>` (page 1, cached handle per url)
  - `upload.ts`:
    - `CLIENT_MAX_BYTES = 20_000_000`
    - `fileToBase64(file: File): Promise<string>`
  - `<Thumb doc={DocSummary} />`
  - `<FolderView refKey: string; folderRef: FolderRef; node: DocFolderNode; archived: boolean; uploads: UploadGhost[]; selectedDocId: string | null; onSelectDoc(id); onOpenDoc(id); onOpenFolder(ref); onUploadFiles(files, ref); onNewFolder(ref) />`

- [ ] **Step 1: Write the failing test**

```tsx
// desktop/src/renderer/__tests__/FolderView.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../components/docs/pdf', () => ({ renderThumb: vi.fn(async () => {}), loadPdf: vi.fn() }));

import { FolderView } from '../components/docs/FolderView';
import { findFolder } from '../components/docs/tree-model';
import { useDocs } from '../stores/docs';
import { libraryFixture } from './fixtures/library';

const ref = { context: 'work', project: 'payments', path: '' };

function setup(uploads = useDocs.getState().uploads) {
  const props = {
    refKey: 'work/payments/', folderRef: ref, node: findFolder(libraryFixture(), ref)!, archived: false, uploads,
    selectedDocId: null, onSelectDoc: vi.fn(), onOpenDoc: vi.fn(), onOpenFolder: vi.fn(), onUploadFiles: vi.fn(), onNewFolder: vi.fn(),
  };
  render(<FolderView {...props} />);
  return props;
}

describe('FolderView', () => {
  beforeEach(() => {
    localStorage.clear();
    useDocs.setState({ viewModes: {}, uploads: [] });
  });

  it('lists subfolders and docs, opens on double click', () => {
    const p = setup();
    expect(screen.getByText('diagrams')).toBeTruthy();
    fireEvent.click(screen.getByText('Rate card Q4'));
    expect(p.onSelectDoc).toHaveBeenCalledWith('cccccccccccc');
    fireEvent.doubleClick(screen.getByText('Rate card Q4'));
    expect(p.onOpenDoc).toHaveBeenCalledWith('cccccccccccc');
    fireEvent.doubleClick(screen.getByText('diagrams'));
    expect(p.onOpenFolder).toHaveBeenCalledWith({ ...ref, path: 'diagrams' });
  });

  it('switches to grid and remembers it per folder', () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: /grid/ }));
    expect(screen.getAllByTestId('doc-card')).toHaveLength(1);
    expect(useDocs.getState().viewMode('work/payments/')).toBe('grid');
  });

  it('shows upload ghosts with errors', () => {
    setup([
      { id: 'u1', name: 'Ledger ERD.png', size: 4_800_000, key: 'work/payments/', status: 'uploading' },
      { id: 'u2', name: 'huge.zip', size: 30_000_000, key: 'work/payments/', status: 'error', error: 'too large (max 20 MB)' },
    ]);
    expect(screen.getByText('Ledger ERD.png')).toBeTruthy();
    expect(screen.getByText('too large (max 20 MB)')).toBeTruthy();
  });

  it('uploads files dropped on the pane into this folder', () => {
    const p = setup();
    const f = new File(['x'], 'a.pdf');
    fireEvent.drop(screen.getByTestId('folder-view'), { dataTransfer: { files: [f], getData: () => '', types: ['Files'] } });
    expect(p.onUploadFiles).toHaveBeenCalledWith([f], ref);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/FolderView.test.tsx`
Expected: FAIL (module missing)

- [ ] **Step 3: Install pdfjs-dist**

Run: `cd desktop && npm install pdfjs-dist@4.10.38 --save-exact`
Expected: `package.json` lists `"pdfjs-dist": "4.10.38"`.

- [ ] **Step 4: Implement `pdf.ts`, `upload.ts`, `Thumb.tsx`**

```ts
// desktop/src/renderer/components/docs/pdf.ts
// The only module that touches pdfjs-dist, so tests can mock it wholesale.
import { getDocument, GlobalWorkerOptions, type PDFDocumentProxy } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.mjs?url';

GlobalWorkerOptions.workerSrc = workerUrl;

export interface PdfHandle {
  numPages: number;
  renderPage(canvas: HTMLCanvasElement, page: number, scale: number): Promise<void>;
}

const cache = new Map<string, Promise<PDFDocumentProxy>>();

function open(url: string): Promise<PDFDocumentProxy> {
  let p = cache.get(url);
  if (!p) {
    p = getDocument({ url }).promise;
    p.catch(() => cache.delete(url));
    cache.set(url, p);
  }
  return p;
}

export async function loadPdf(url: string): Promise<PdfHandle> {
  const pdf = await open(url);
  return {
    numPages: pdf.numPages,
    async renderPage(canvas, pageNo, scale) {
      const page = await pdf.getPage(pageNo);
      const ratio = window.devicePixelRatio || 1;
      const viewport = page.getViewport({ scale: scale * ratio });
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.style.width = `${viewport.width / ratio}px`;
      canvas.style.height = `${viewport.height / ratio}px`;
      await page.render({ canvasContext: canvas.getContext('2d')!, viewport }).promise;
    },
  };
}

export async function renderThumb(canvas: HTMLCanvasElement, url: string, width: number): Promise<void> {
  const pdf = await open(url);
  const page = await pdf.getPage(1);
  const base = page.getViewport({ scale: 1 });
  const viewport = page.getViewport({ scale: width / base.width });
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  await page.render({ canvasContext: canvas.getContext('2d')!, viewport }).promise;
}
```

If `npm run typecheck` complains about the `?url` import, add `/// <reference types="vite/client" />` at the top of `pdf.ts`. (Check first whether `src/renderer/vite-env.d.ts` already provides it: `ls src/renderer/*.d.ts`.)

```ts
// desktop/src/renderer/components/docs/upload.ts
export const CLIENT_MAX_BYTES = 20_000_000;

export function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error(`could not read ${file.name}`));
    reader.onload = () => {
      const url = String(reader.result ?? '');
      resolve(url.slice(url.indexOf(',') + 1));
    };
    reader.readAsDataURL(file);
  });
}
```

```tsx
// desktop/src/renderer/components/docs/Thumb.tsx
import { useEffect, useRef, useState } from 'react';
import type { DocSummary } from '../../../shared/api-types';
import { docUrl, KIND_META, kindLabel } from './kinds';
import { renderThumb } from './pdf';

const TINT: Record<string, string> = {
  pdf: 'linear-gradient(160deg,#2a1714,var(--bg-vellum))',
  image: 'linear-gradient(160deg,#122029,var(--bg-vellum))',
  docx: 'linear-gradient(160deg,#171a2e,var(--bg-vellum))',
  xlsx: 'linear-gradient(160deg,#16201A,var(--bg-vellum))',
  text: 'linear-gradient(160deg,#1a220c,var(--bg-vellum))',
  opaque: 'var(--bg-fog)',
};

function PdfThumb({ doc }: { doc: DocSummary }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    if (ref.current) renderThumb(ref.current, docUrl(doc.original_path), 160).catch(() => setFailed(true));
  }, [doc.original_path]);
  if (failed) return <TextThumb doc={doc} />;
  return <canvas ref={ref} className="mt-3 w-[62%] self-end rounded-t-[3px] bg-white shadow-[0_-4px_20px_rgba(0,0,0,.3)]" />;
}

function TextThumb({ doc }: { doc: DocSummary }) {
  return (
    <div className="mt-3 h-[88%] w-[62%] self-end overflow-hidden rounded-t-[3px] bg-[#F4F4F0] p-2.5 text-[6.5px] leading-[1.45] text-[#3a3d44]">
      {doc.excerpt || <span className="font-mono text-[9px]" style={{ color: KIND_META[doc.kind].fg }}>{kindLabel(doc)}</span>}
    </div>
  );
}

export function Thumb({ doc }: { doc: DocSummary }) {
  let inner: React.ReactNode;
  if (doc.kind === 'image') {
    inner = <img src={docUrl(doc.original_path)} alt="" loading="lazy" className="h-full w-full object-cover" />;
  } else if (doc.kind === 'pdf') {
    inner = <PdfThumb doc={doc} />;
  } else if (doc.kind === 'opaque') {
    inner = <span className="font-mono text-12 text-ink-2">{kindLabel(doc)}</span>;
  } else {
    inner = <TextThumb doc={doc} />;
  }
  return (
    <div className="flex h-[120px] items-center justify-center overflow-hidden" style={{ background: TINT[doc.kind] }}>
      {inner}
    </div>
  );
}
```

- [ ] **Step 5: Implement `FolderView.tsx`**

```tsx
// desktop/src/renderer/components/docs/FolderView.tsx
import { useMemo, useState } from 'react';
import type { DocFolderNode, DocSummary, FolderRef } from '../../../shared/api-types';
import { useDocs, type UploadGhost } from '../../stores/docs';
import { Lucide } from '../Lucide';
import { KindChip } from './KindChip';
import { formatSize } from './kinds';
import { Thumb } from './Thumb';
import { countDocs, DRAG_MIME, encodeDrag } from './tree-model';

interface Props {
  refKey: string;
  folderRef: FolderRef;
  node: DocFolderNode;
  archived: boolean;
  uploads: UploadGhost[];
  selectedDocId: string | null;
  onSelectDoc: (id: string) => void;
  onOpenDoc: (id: string) => void;
  onOpenFolder: (ref: FolderRef) => void;
  onUploadFiles: (files: File[], ref: FolderRef) => void;
  onNewFolder: (ref: FolderRef) => void;
}

type SortKey = 'name' | 'kind' | 'modified' | 'size';

function relTime(iso: string): string {
  const days = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (Number.isNaN(days)) return '';
  if (days < 1) return 'today';
  if (days < 7) return `${days}d`;
  if (days < 30) return `${Math.floor(days / 7)}w`;
  return `${Math.floor(days / 30)}mo`;
}

function sortDocs(docs: DocSummary[], key: SortKey): DocSummary[] {
  const by: Record<SortKey, (a: DocSummary, b: DocSummary) => number> = {
    name: (a, b) => a.title.localeCompare(b.title),
    kind: (a, b) => a.kind.localeCompare(b.kind) || a.title.localeCompare(b.title),
    modified: (a, b) => b.created.localeCompare(a.created),
    size: (a, b) => b.size - a.size,
  };
  return docs.slice().sort(by[key]);
}

export function FolderView(p: Props) {
  const mode = useDocs((s) => s.viewModes[p.refKey] ?? 'list');
  const setViewMode = useDocs((s) => s.setViewMode);
  const [sort, setSort] = useState<SortKey>('name');
  const [dragOver, setDragOver] = useState(false);
  const docs = useMemo(() => sortDocs(p.node.docs, sort), [p.node.docs, sort]);
  const ghosts = p.uploads.filter((u) => u.key === p.refKey);
  const childRef = (name: string): FolderRef => ({ ...p.folderRef, path: p.folderRef.path ? `${p.folderRef.path}/${name}` : name });
  const dragDoc = (d: DocSummary) => (e: React.DragEvent) => e.dataTransfer.setData(DRAG_MIME, encodeDrag({ type: 'doc', docId: d.doc_id }));

  const empty = !p.node.folders.length && !docs.length && !ghosts.length;

  return (
    <div
      data-testid="folder-view"
      className={`relative flex min-h-0 flex-1 flex-col ${dragOver ? 'bg-neon-mist/30' : ''}`}
      onDragOver={(e) => {
        if (p.archived || !Array.from(e.dataTransfer.types ?? []).includes('Files')) return;
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragOver(false);
        const files = Array.from(e.dataTransfer.files ?? []);
        if (files.length && !p.archived) p.onUploadFiles(files, p.folderRef);
      }}
    >
      <div className="flex items-center gap-2 border-b border-hairline px-[18px] py-2">
        <div className="flex overflow-hidden rounded-lg border border-hairline-2 font-mono text-11">
          {(['list', 'grid'] as const).map((m) => (
            <button key={m} type="button" onClick={() => setViewMode(p.refKey, m)} className={`px-2.5 py-1 ${mode === m ? 'bg-fog text-ink-0' : 'text-ink-2'}`}>
              {m === 'list' ? '≡ list' : '▦ grid'}
            </button>
          ))}
        </div>
        {mode === 'list' && (
          <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)} className="rounded border border-hairline-2 bg-paper px-2 py-1 font-mono text-11 text-ink-1" aria-label="sort by">
            <option value="name">name</option>
            <option value="kind">kind</option>
            <option value="modified">added</option>
            <option value="size">size</option>
          </select>
        )}
        <span className="flex-1" />
        {!p.archived && (
          <button type="button" onClick={() => p.onNewFolder(p.folderRef)} className="inline-flex items-center gap-1.5 rounded-[7px] border border-hairline-2 px-2.5 py-1 font-mono text-11 text-ink-1 hover:text-ink-0">
            <Lucide name="folder-plus" size={12} /> folder
          </button>
        )}
      </div>

      {empty ? (
        <div className="m-6 grid flex-1 place-items-center rounded-xl border border-dashed border-hairline-3 text-center text-13 text-ink-2">
          <div>
            <div className="mb-1 text-ink-0">drop files here</div>
            they'll be filed in this folder and indexed for chat & search
          </div>
        </div>
      ) : mode === 'list' ? (
        <div className="overflow-y-auto p-2 text-13">
          {p.node.folders.map((f) => (
            <button key={f.path} type="button" onDoubleClick={() => p.onOpenFolder(childRef(f.name))} onClick={() => p.onOpenFolder(childRef(f.name))} className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-ink-1 hover:bg-vellum">
              <Lucide name="folder" size={13} />
              <span className="truncate">{f.name}</span>
              <span className="ml-auto font-mono text-10 text-ink-3">{countDocs(f)}</span>
            </button>
          ))}
          {docs.map((d) => (
            <button
              key={d.doc_id}
              type="button"
              draggable
              onDragStart={dragDoc(d)}
              onClick={() => p.onSelectDoc(d.doc_id)}
              onDoubleClick={() => p.onOpenDoc(d.doc_id)}
              className={`grid w-full grid-cols-[auto_1fr_70px_60px] items-center gap-2 rounded-md px-2 py-1.5 text-left ${p.selectedDocId === d.doc_id ? 'bg-neon-mist text-ink-0' : 'text-ink-1 hover:bg-vellum'}`}
            >
              <KindChip doc={d} />
              <span className="truncate">{d.title}</span>
              <span className="text-right font-mono text-10 text-ink-3">{relTime(d.created)}</span>
              <span className="text-right font-mono text-10 text-ink-3">{formatSize(d.size)}</span>
            </button>
          ))}
          {ghosts.map((g) => (
            <div key={g.id} className="relative grid grid-cols-[1fr_auto] items-center gap-2 overflow-hidden rounded-md px-2 py-1.5 text-ink-2">
              <span className="truncate">{g.name}</span>
              <span className={`font-mono text-10 ${g.status === 'error' ? 'text-oxblood' : ''}`}>{g.status === 'error' ? g.error : 'uploading…'}</span>
              {g.status === 'uploading' && <span className="absolute inset-x-0 bottom-0 h-[2px] animate-pulse bg-neon shadow-[0_0_10px_var(--neon)]" />}
            </div>
          ))}
        </div>
      ) : (
        <div className="overflow-y-auto">
          {p.node.folders.length > 0 && (
            <div className="flex flex-wrap gap-2 px-[18px] pt-4">
              {p.node.folders.map((f) => (
                <button key={f.path} type="button" onClick={() => p.onOpenFolder(childRef(f.name))} className="flex min-w-[150px] items-center gap-2 rounded-[10px] border border-hairline bg-vellum px-3 py-2 text-12 text-ink-1 hover:border-hairline-3">
                  <Lucide name="folder" size={13} />
                  {f.name}
                  <span className="ml-auto font-mono text-10 text-ink-3">{countDocs(f)}</span>
                </button>
              ))}
            </div>
          )}
          <div className="grid grid-cols-[repeat(auto-fill,minmax(170px,1fr))] gap-3.5 p-[18px]">
            {docs.map((d) => (
              <button
                key={d.doc_id}
                data-testid="doc-card"
                type="button"
                draggable
                onDragStart={dragDoc(d)}
                onClick={() => p.onSelectDoc(d.doc_id)}
                onDoubleClick={() => p.onOpenDoc(d.doc_id)}
                className={`overflow-hidden rounded-xl border bg-vellum text-left transition-shadow ${p.selectedDocId === d.doc_id ? 'border-neon/50 shadow-[0_0_0_1px_rgba(197,255,61,.25),0_12px_30px_rgba(0,0,0,.4)]' : 'border-hairline hover:border-hairline-3'}`}
              >
                <Thumb doc={d} />
                <div className="flex flex-col gap-1 px-3 py-2.5">
                  <span className="truncate text-12 font-medium text-ink-0">{d.title}</span>
                  <span className="flex items-center gap-1.5 font-mono text-10 text-ink-3">
                    <KindChip doc={d} />
                    {d.pages ? `${d.pages} pp` : formatSize(d.size)} · {relTime(d.created)}
                  </span>
                </div>
              </button>
            ))}
            {ghosts.map((g) => (
              <div key={g.id} className="relative overflow-hidden rounded-xl border border-hairline bg-vellum opacity-85">
                <div className="grid h-[120px] place-items-center bg-[repeating-linear-gradient(135deg,var(--bg-vellum)_0_10px,#181a1f_10px_20px)] font-mono text-11 text-ink-2">
                  {g.status === 'error' ? <span className="px-3 text-center text-oxblood">{g.error}</span> : 'uploading…'}
                </div>
                <div className="px-3 py-2.5 text-12 text-ink-1">{g.name}</div>
                {g.status === 'uploading' && <span className="absolute inset-x-0 bottom-0 h-[3px] animate-pulse bg-neon shadow-[0_0_10px_var(--neon)]" />}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Run tests + typecheck**

Run: `cd desktop && npx vitest run src/renderer/__tests__/FolderView.test.tsx && npm run typecheck`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add desktop/package.json desktop/package-lock.json desktop/src/renderer/components/docs/pdf.ts desktop/src/renderer/components/docs/upload.ts desktop/src/renderer/components/docs/Thumb.tsx desktop/src/renderer/components/docs/FolderView.tsx desktop/src/renderer/__tests__/FolderView.test.tsx
git commit -m "feat(docs): folder view with list/grid switch, thumbnails and upload ghosts

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Reader (per-kind viewers) + inspector + attention panel

**Files:**
- Create: `desktop/src/renderer/components/docs/PdfViewer.tsx`, `desktop/src/renderer/components/docs/DocReader.tsx`, `desktop/src/renderer/components/docs/DocInspector.tsx`, `desktop/src/renderer/components/docs/AttentionPanel.tsx`
- Test: `desktop/src/renderer/__tests__/DocReader.test.tsx`, `desktop/src/renderer/__tests__/DocInspector.test.tsx`

**Interfaces:**
- Consumes: `loadPdf` (Task 11), `MarkdownBody` (`components/MarkdownBody.tsx`, prop `children: string`), the hooks from Task 9.
- Produces:
  - `<DocReader doc: DocSummary; body: string | undefined; crumb: string; onClose(); onOpenExternal(); onReveal(); onDelete() />`
  - `<DocInspector doc: DocSummary; scopeName: string; onRename(title: string); onReindex() />`
  - `<AttentionPanel items: AttentionItem[]; onAdopt(item); onRemoveOrphan(docId); onReindex(docId) />`

- [ ] **Step 1: Write the failing tests**

```tsx
// desktop/src/renderer/__tests__/DocReader.test.tsx
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const renderPage = vi.fn(async () => {});
vi.mock('../components/docs/pdf', () => ({
  loadPdf: vi.fn(async () => ({ numPages: 24, renderPage })),
  renderThumb: vi.fn(async () => {}),
}));

import { DocReader } from '../components/docs/DocReader';
import { doc } from './fixtures/library';

function setup(d = doc({}), body?: string) {
  const p = { doc: d, body, crumb: 'work / Payments / specs', onClose: vi.fn(), onOpenExternal: vi.fn(), onReveal: vi.fn(), onDelete: vi.fn() };
  render(<DocReader {...p} />);
  return p;
}

describe('DocReader', () => {
  it('renders pdfs page by page with a pager', async () => {
    setup();
    await waitFor(() => expect(screen.getByText('/ 24')).toBeTruthy());
    expect(renderPage).toHaveBeenLastCalledWith(expect.any(HTMLCanvasElement), 1, 1);
    fireEvent.click(screen.getByLabelText('next page'));
    await waitFor(() => expect(renderPage).toHaveBeenLastCalledWith(expect.any(HTMLCanvasElement), 2, 1));
  });

  it('renders images from gbdoc://', () => {
    setup(doc({ kind: 'image', original: 'a.png', original_path: '20-contexts/work/docs/a.png' }));
    expect(screen.getByRole('img').getAttribute('src')).toBe('gbdoc://doc/20-contexts/work/docs/a.png');
  });

  it('renders text-ish kinds from the extracted body', () => {
    setup(doc({ kind: 'docx', original: 'a.docx' }), 'Hello **world**');
    expect(screen.getByText('world').tagName).toBe('STRONG');
  });

  it('offers open-in for opaque files and closes on Escape', () => {
    const p = setup(doc({ kind: 'opaque', original: 'a.zip' }));
    fireEvent.click(screen.getAllByText(/open in/)[0]!);
    expect(p.onOpenExternal).toHaveBeenCalled();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(p.onClose).toHaveBeenCalled();
  });

  it('shows the indexing state pill', () => {
    setup(doc({ index_status: 'failed' }));
    expect(screen.getByText('index failed')).toBeTruthy();
  });
});
```

```tsx
// desktop/src/renderer/__tests__/DocInspector.test.tsx
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { AttentionPanel } from '../components/docs/AttentionPanel';
import { DocInspector } from '../components/docs/DocInspector';
import { doc } from './fixtures/library';

describe('DocInspector', () => {
  it('shows metadata and renames inline', () => {
    const onRename = vi.fn();
    render(<DocInspector doc={doc({})} scopeName="Payments" onRename={onRename} onReindex={vi.fn()} />);
    expect(screen.getByText('PDF · 24 pages')).toBeTruthy();
    expect(screen.getByText('2.2 MB')).toBeTruthy();
    expect(screen.getByText('Payments')).toBeTruthy();
    fireEvent.click(screen.getByText('Payments API v2'));
    const input = screen.getByDisplayValue('Payments API v2');
    fireEvent.change(input, { target: { value: 'Payments API v3' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onRename).toHaveBeenCalledWith('Payments API v3');
  });

  it('offers retry when indexing failed', () => {
    const onReindex = vi.fn();
    render(<DocInspector doc={doc({ index_status: 'failed' })} scopeName="Payments" onRename={vi.fn()} onReindex={onReindex} />);
    fireEvent.click(screen.getByText('retry indexing'));
    expect(onReindex).toHaveBeenCalled();
  });
});

describe('AttentionPanel', () => {
  it('maps each item kind to its repair action', () => {
    const p = { onAdopt: vi.fn(), onRemoveOrphan: vi.fn(), onReindex: vi.fn() };
    render(
      <AttentionPanel
        items={[
          { kind: 'unclaimed_original', context: 'work', project: null, folder: 'inbox', name: 'x.pdf', doc_id: null },
          { kind: 'orphan_note', context: 'work', project: null, folder: '', name: 'y-abc.md', doc_id: 'dddddddddddd' },
          { kind: 'index_failed', context: 'work', project: 'payments', folder: '', name: 'z.pdf', doc_id: 'eeeeeeeeeeee' },
        ]}
        {...p}
      />,
    );
    fireEvent.click(screen.getByText('add to library'));
    expect(p.onAdopt).toHaveBeenCalledWith(expect.objectContaining({ name: 'x.pdf' }));
    fireEvent.click(screen.getByText('remove note'));
    expect(p.onRemoveOrphan).toHaveBeenCalledWith('dddddddddddd');
    fireEvent.click(screen.getByText('retry'));
    expect(p.onReindex).toHaveBeenCalledWith('eeeeeeeeeeee');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd desktop && npx vitest run src/renderer/__tests__/DocReader.test.tsx src/renderer/__tests__/DocInspector.test.tsx`
Expected: FAIL (modules missing)

- [ ] **Step 3: Implement `PdfViewer.tsx`**

```tsx
// desktop/src/renderer/components/docs/PdfViewer.tsx
import { useEffect, useRef, useState } from 'react';
import { loadPdf, type PdfHandle } from './pdf';

const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2];

export function PdfViewer({ url }: { url: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [pdf, setPdf] = useState<PdfHandle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(2); // index into ZOOMS → 1.0

  useEffect(() => {
    let live = true;
    setPdf(null);
    setPage(1);
    loadPdf(url).then((h) => live && setPdf(h)).catch((e: unknown) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, [url]);

  useEffect(() => {
    if (pdf && canvas.current) pdf.renderPage(canvas.current, page, ZOOMS[zoom]!).catch((e: unknown) => setError(String(e)));
  }, [pdf, page, zoom]);

  if (error) return <div className="p-8 text-13 text-oxblood">couldn't render this PDF: {error}</div>;

  return (
    <div className="relative flex min-h-0 flex-1 justify-center overflow-auto bg-[radial-gradient(1200px_400px_at_50%_-10%,rgba(197,255,61,.05),transparent_60%)] p-6">
      <canvas ref={canvas} className="h-fit rounded-[3px] shadow-[0_20px_50px_rgba(0,0,0,.55)]" />
      {pdf && (
        <div className="fixed bottom-6 left-1/2 flex -translate-x-1/2 items-center gap-3.5 rounded-full border border-hairline-2 bg-vellum/90 px-3.5 py-1.5 font-mono text-11 text-ink-1 shadow-[0_10px_30px_rgba(0,0,0,.5)] backdrop-blur">
          <button type="button" aria-label="previous page" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="disabled:opacity-30">‹</button>
          <b className="font-medium text-ink-0">{page}</b>
          <span>/ {pdf.numPages}</span>
          <button type="button" aria-label="next page" disabled={page >= pdf.numPages} onClick={() => setPage((p) => p + 1)} className="disabled:opacity-30">›</button>
          <span className="text-ink-3">|</span>
          <button type="button" aria-label="zoom out" disabled={zoom === 0} onClick={() => setZoom((z) => z - 1)} className="disabled:opacity-30">−</button>
          <span>{Math.round(ZOOMS[zoom]! * 100)}%</span>
          <button type="button" aria-label="zoom in" disabled={zoom === ZOOMS.length - 1} onClick={() => setZoom((z) => z + 1)} className="disabled:opacity-30">+</button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Implement `DocReader.tsx`**

```tsx
// desktop/src/renderer/components/docs/DocReader.tsx
import { useEffect } from 'react';
import type { DocSummary } from '../../../shared/api-types';
import { Lucide } from '../Lucide';
import { MarkdownBody } from '../MarkdownBody';
import { docUrl } from './kinds';
import { PdfViewer } from './PdfViewer';

interface Props {
  doc: DocSummary;
  body: string | undefined;
  crumb: string;
  onClose: () => void;
  onOpenExternal: () => void;
  onReveal: () => void;
  onDelete: () => void;
}

function StatusPill({ status }: { status: DocSummary['index_status'] }) {
  if (status === 'failed') {
    return <span className="inline-flex items-center gap-1.5 rounded-full bg-[rgba(242,193,78,.12)] px-2.5 py-[3px] font-mono text-[10.5px] text-[#F2C14E]">index failed</span>;
  }
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full bg-neon-mist px-2.5 py-[3px] font-mono text-[10.5px] text-neon-ink">
      <span className="h-1.5 w-1.5 rounded-full bg-neon shadow-[0_0_8px_var(--neon)]" />
      indexed
    </span>
  );
}

function Viewer({ doc, body, onOpenExternal }: Pick<Props, 'doc' | 'body' | 'onOpenExternal'>) {
  if (doc.kind === 'pdf') return <PdfViewer url={docUrl(doc.original_path)} />;
  if (doc.kind === 'image') {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto p-6">
        <img src={docUrl(doc.original_path)} alt={doc.title} className="max-h-full max-w-full rounded shadow-[0_20px_50px_rgba(0,0,0,.55)]" />
      </div>
    );
  }
  if (doc.kind === 'opaque') {
    return (
      <div className="grid flex-1 place-items-center">
        <div className="rounded-xl border border-hairline-2 bg-vellum px-8 py-6 text-center text-13 text-ink-1">
          <div className="mb-3">no in-app preview for this file type</div>
          <button type="button" onClick={onOpenExternal} className="rounded-[7px] bg-neon px-3 py-1.5 font-mono text-11 font-semibold text-[#0E0F12]">open in default app ↗</button>
        </div>
      </div>
    );
  }
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-10 py-8">
      {body === undefined ? <div className="text-13 text-ink-3">loading…</div> : <MarkdownBody className="mx-auto max-w-[760px]">{body || '_no extractable text_'}</MarkdownBody>}
    </div>
  );
}

export function DocReader({ doc, body, crumb, onClose, onOpenExternal, onReveal, onDelete }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !(e.target instanceof HTMLInputElement)) onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-[#0A0B0D]">
      <div className="flex h-[52px] shrink-0 items-center gap-3 border-b border-hairline bg-paper px-[18px]">
        <button type="button" aria-label="back to folder" onClick={onClose} className="text-ink-3 hover:text-ink-0"><Lucide name="arrow-left" size={14} /></button>
        <span className="truncate font-mono text-[11.5px] text-ink-2">
          {crumb} / <em className="not-italic text-ink-0">{doc.original}</em>
        </span>
        <span className="flex-1" />
        <StatusPill status={doc.index_status} />
        <button type="button" onClick={onOpenExternal} className="rounded-[7px] border border-hairline-2 px-2.5 py-1 font-mono text-11 text-ink-1 hover:text-ink-0">open in ↗</button>
        <button type="button" aria-label="reveal in folder" onClick={onReveal} className="rounded-[7px] border border-hairline-2 p-1.5 text-ink-1 hover:text-ink-0"><Lucide name="folder-open" size={13} /></button>
        <button type="button" aria-label="move to trash" onClick={onDelete} className="rounded-[7px] border border-hairline-2 p-1.5 text-ink-1 hover:text-oxblood"><Lucide name="trash-2" size={13} /></button>
      </div>
      <Viewer doc={doc} body={body} onOpenExternal={onOpenExternal} />
    </div>
  );
}
```

- [ ] **Step 5: Implement `DocInspector.tsx` and `AttentionPanel.tsx`**

```tsx
// desktop/src/renderer/components/docs/DocInspector.tsx
import { useState } from 'react';
import type { DocSummary } from '../../../shared/api-types';
import { formatSize, kindLabel } from './kinds';

interface Props {
  doc: DocSummary;
  scopeName: string;
  onRename: (title: string) => void;
  onReindex: () => void;
}

const Cap = ({ children }: { children: React.ReactNode }) => (
  <span className="font-mono text-10 uppercase tracking-[0.12em] text-ink-3">{children}</span>
);

export function DocInspector({ doc, scopeName, onRename, onReindex }: Props) {
  const [editing, setEditing] = useState(false);
  const kindLine = `${kindLabel(doc)}${doc.pages ? ` · ${doc.pages} pages` : ''}`;
  const added = new Date(doc.created).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  return (
    <aside className="flex w-[268px] shrink-0 flex-col gap-[18px] border-l border-hairline bg-vellum px-4 py-[18px] text-[12.5px]">
      <div>
        <Cap>document</Cap>
        {editing ? (
          <input
            autoFocus
            defaultValue={doc.title}
            className="mt-1.5 w-full rounded border border-neon bg-paper px-2 py-1 text-16 text-ink-0 outline-none"
            onKeyDown={(e) => {
              const v = (e.target as HTMLInputElement).value.trim();
              if (e.key === 'Enter') {
                setEditing(false);
                if (v && v !== doc.title) onRename(v);
              }
              if (e.key === 'Escape') setEditing(false);
            }}
            onBlur={() => setEditing(false)}
          />
        ) : (
          <h4 className="mt-1.5 cursor-text text-16 font-medium leading-tight text-ink-0" title="click to rename" onClick={() => setEditing(true)}>
            {doc.title}
          </h4>
        )}
      </div>
      <dl className="grid grid-cols-[70px_1fr] gap-y-1.5 text-12">
        <dt className="font-mono text-[10.5px] text-ink-3">kind</dt>
        <dd className="text-ink-1">{kindLine}</dd>
        <dt className="font-mono text-[10.5px] text-ink-3">size</dt>
        <dd className="text-ink-1">{formatSize(doc.size)}</dd>
        <dt className="font-mono text-[10.5px] text-ink-3">added</dt>
        <dd className="text-ink-1">{added}</dd>
        <dt className="font-mono text-[10.5px] text-ink-3">{doc.project ? 'project' : 'context'}</dt>
        <dd className="text-ink-1">{doc.project ? scopeName : doc.context}</dd>
      </dl>
      {doc.index_status === 'failed' && (
        <div className="rounded-[10px] border border-[rgba(242,193,78,.3)] bg-[rgba(242,193,78,.06)] p-3 leading-normal text-ink-1">
          Poltergeist couldn't read this file's text, so chat and search can't see it yet.
          <button type="button" onClick={onReindex} className="mt-2 block font-mono text-11 text-[#F2C14E] hover:underline">retry indexing</button>
        </div>
      )}
    </aside>
  );
}
```

```tsx
// desktop/src/renderer/components/docs/AttentionPanel.tsx
import type { AttentionItem } from '../../../shared/api-types';
import { Lucide } from '../Lucide';

interface Props {
  items: AttentionItem[];
  onAdopt: (item: AttentionItem) => void;
  onRemoveOrphan: (docId: string) => void;
  onReindex: (docId: string) => void;
}

const COPY: Record<AttentionItem['kind'], { title: string; hint: string; action: string }> = {
  unclaimed_original: { title: 'not in the library yet', hint: 'added outside the app (Finder, sync)', action: 'add to library' },
  orphan_note: { title: 'original file is missing', hint: 'the note remains but its file is gone', action: 'remove note' },
  index_failed: { title: 'indexing failed', hint: "chat and search can't see its text", action: 'retry' },
};

export function AttentionPanel({ items, onAdopt, onRemoveOrphan, onReindex }: Props) {
  return (
    <div className="flex-1 overflow-y-auto p-6">
      <h2 className="mb-1 text-20 font-medium text-ink-0">needs attention</h2>
      <p className="mb-5 text-13 text-ink-2">files and notes that are out of step with each other. Nothing here was deleted.</p>
      <div className="flex flex-col gap-2">
        {items.map((it) => {
          const c = COPY[it.kind];
          const where = [it.context, it.project, it.folder].filter(Boolean).join(' / ');
          const act = () => {
            if (it.kind === 'unclaimed_original') onAdopt(it);
            else if (it.kind === 'orphan_note') onRemoveOrphan(it.doc_id!);
            else onReindex(it.doc_id!);
          };
          return (
            <div key={`${it.kind}:${where}:${it.name}`} className="flex items-center gap-3 rounded-[10px] border border-hairline bg-vellum px-4 py-3">
              <Lucide name="triangle-alert" size={14} className="text-[#F2C14E]" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-13 text-ink-0">{it.name}</div>
                <div className="font-mono text-10 text-ink-3">{c.title} · {where} · {c.hint}</div>
              </div>
              <button type="button" onClick={act} className="rounded-[7px] border border-hairline-2 px-2.5 py-1 font-mono text-11 text-ink-1 hover:border-neon hover:text-neon">{c.action}</button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Run tests + typecheck**

Run: `cd desktop && npx vitest run src/renderer/__tests__/DocReader.test.tsx src/renderer/__tests__/DocInspector.test.tsx && npm run typecheck`
Expected: PASS. If `MarkdownBody` requires the note-view store/provider in tests, it already works in `NoteView.test.tsx`, so copy any wrapper that test uses.

- [ ] **Step 7: Commit**

```bash
git add desktop/src/renderer/components/docs/PdfViewer.tsx desktop/src/renderer/components/docs/DocReader.tsx desktop/src/renderer/components/docs/DocInspector.tsx desktop/src/renderer/components/docs/AttentionPanel.tsx desktop/src/renderer/__tests__/DocReader.test.tsx desktop/src/renderer/__tests__/DocInspector.test.tsx
git commit -m "feat(docs): reader with per-kind viewers, inspector and needs-attention panel

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: Docs screen, quick open, navigation

**Files:**
- Create: `desktop/src/renderer/components/docs/QuickOpen.tsx`, `desktop/src/renderer/screens/docs.tsx`
- Modify: `desktop/src/renderer/stores/navigation.ts` (add `| 'docs'`), `desktop/src/renderer/components/Sidebar.tsx` (NAV_ITEMS: `{ id: 'docs', icon: 'library', label: 'docs' }` between jots and vault), `desktop/src/renderer/App.tsx` (import + `{active === 'docs' && <DocsScreen />}`)
- Test: `desktop/src/renderer/__tests__/DocsScreen.test.tsx`

**Interfaces:**
- Consumes: everything from Tasks 9–12; `useSettings((s) => s.vaultPath)`; `toast`; `ApiError`.
- Produces: `DocsScreen`, `<QuickOpen open onClose onPick(docId) />`.

- [ ] **Step 1: Write the failing test**

```tsx
// desktop/src/renderer/__tests__/DocsScreen.test.tsx
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../components/docs/pdf', () => ({ renderThumb: vi.fn(async () => {}), loadPdf: vi.fn(async () => ({ numPages: 1, renderPage: vi.fn(async () => {}) })) }));
vi.mock('../lib/api/client', () => ({
  ApiError: class extends Error { status?: number },
  get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(),
}));

import * as client from '../lib/api/client';
import { DocsScreen } from '../screens/docs';
import { useDocs } from '../stores/docs';
import { doc, libraryFixture } from './fixtures/library';

function renderScreen() {
  vi.mocked(client.get).mockImplementation(((path: string) => {
    if (path === '/v1/library/tree') return Promise.resolve(libraryFixture());
    if (path.startsWith('/v1/library/docs/')) return Promise.resolve({ ...doc({}), body: 'body' });
    if (path.startsWith('/v1/library/search')) return Promise.resolve([doc({})]);
    return Promise.resolve([]);
  }) as never);
  vi.mocked(client.post).mockResolvedValue({ ...doc({ doc_id: 'ffffffffffff' }), duplicate: false } as never);
  vi.mocked(client.patch).mockResolvedValue(doc({}) as never);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><DocsScreen /></QueryClientProvider>);
}

describe('DocsScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useDocs.setState({ selection: null, uploads: [], quickOpen: false, viewModes: {} });
  });

  it('opens a doc from the tree into the reader + inspector', async () => {
    renderScreen();
    fireEvent.click(await screen.findByText('Payments API v2'));
    expect(await screen.findByText('document')).toBeTruthy();
    expect(screen.getByText('indexed')).toBeTruthy();
  });

  it('uploads dropped files as base64 into the target folder', async () => {
    renderScreen();
    const target = await screen.findByTestId('folder-work/payments/specs');
    const f = new File(['hello'], 'a.md', { type: 'text/markdown' });
    fireEvent.drop(target, { dataTransfer: { files: [f], getData: () => '', types: ['Files'] } });
    await waitFor(() => expect(client.post).toHaveBeenCalledWith('/v1/library/docs', {
      context: 'work', project: 'payments', folder: 'specs', name: 'a.md', mime: 'text/markdown', content_b64: btoa('hello'),
    }));
  });

  it('rejects files over the client cap without calling the API', async () => {
    renderScreen();
    const target = await screen.findByTestId('folder-work/payments/specs');
    const big = new File(['x'], 'big.zip');
    Object.defineProperty(big, 'size', { value: 25_000_000 });
    fireEvent.drop(target, { dataTransfer: { files: [big], getData: () => '', types: ['Files'] } });
    await waitFor(() => expect(useDocs.getState().uploads[0]?.status).toBe('error'));
    expect(client.post).not.toHaveBeenCalled();
  });

  it('opens quick open on Cmd+P and jumps to the picked doc', async () => {
    renderScreen();
    await screen.findByText('Payments');
    fireEvent.keyDown(window, { key: 'p', metaKey: true });
    fireEvent.change(await screen.findByPlaceholderText('find a doc…'), { target: { value: 'pay' } });
    // Results load async; Enter before they arrive would pick nothing.
    await waitFor(() => expect(screen.getAllByText('Payments API v2').length).toBeGreaterThan(1));
    fireEvent.keyDown(screen.getByPlaceholderText('find a doc…'), { key: 'Enter' });
    await waitFor(() => expect(useDocs.getState().selection).toEqual({ type: 'doc', docId: 'aaaaaaaaaaaa' }));
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/DocsScreen.test.tsx`
Expected: FAIL (module missing)

- [ ] **Step 3: Implement `QuickOpen.tsx`**

```tsx
// desktop/src/renderer/components/docs/QuickOpen.tsx
import { useEffect, useState } from 'react';
import { useLibrarySearch } from '../../lib/api/hooks';
import { KindChip } from './KindChip';

interface Props {
  open: boolean;
  onClose: () => void;
  onPick: (docId: string) => void;
}

export function QuickOpen({ open, onClose, onPick }: Props) {
  const [q, setQ] = useState('');
  const [active, setActive] = useState(0);
  const results = useLibrarySearch(q).data ?? [];

  useEffect(() => {
    if (!open) setQ('');
  }, [open]);
  useEffect(() => setActive(0), [q]);

  if (!open) return null;
  const pick = (i: number) => {
    const hit = results[i];
    if (!hit) return;
    onPick(hit.doc_id);
    onClose();
  };
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 pt-[14vh]" onMouseDown={onClose}>
      <div className="w-[520px] overflow-hidden rounded-xl border border-hairline-2 bg-vellum shadow-[0_24px_60px_rgba(0,0,0,.65)]" onMouseDown={(e) => e.stopPropagation()}>
        <input
          autoFocus
          value={q}
          placeholder="find a doc…"
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setActive((a) => Math.min(a + 1, results.length - 1)); }
            if (e.key === 'ArrowUp') { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
            if (e.key === 'Enter') pick(active);
            if (e.key === 'Escape') onClose();
          }}
          className="w-full border-b border-hairline bg-transparent px-4 py-3 text-14 text-ink-0 outline-none placeholder:text-ink-3"
        />
        <div className="max-h-[320px] overflow-y-auto py-1">
          {results.map((d, i) => (
            <button
              key={d.doc_id}
              type="button"
              onMouseEnter={() => setActive(i)}
              onClick={() => pick(i)}
              className={`flex w-full items-center gap-2.5 px-4 py-2 text-left text-[13.5px] ${i === active ? 'bg-neon-mist text-ink-0' : 'text-ink-1'}`}
            >
              <KindChip doc={d} />
              <span className="truncate">{d.title}</span>
              <span className={`ml-auto truncate font-mono text-[10.5px] ${i === active ? 'text-neon-ink' : 'text-ink-3'}`}>
                {[d.project ?? d.context, d.folder].filter(Boolean).join(' / ')}
              </span>
            </button>
          ))}
          {q && results.length === 0 && <div className="px-4 py-3 text-12 text-ink-3">no matching docs</div>}
        </div>
        <div className="flex gap-3.5 border-t border-hairline px-4 py-2 font-mono text-10 text-ink-3">
          <span>↑↓ navigate</span><span>↵ open</span><span>esc close</span>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Implement `screens/docs.tsx`**

```tsx
// desktop/src/renderer/screens/docs.tsx
import { useCallback, useEffect, useRef } from 'react';
import type { AttentionItem, FolderRef } from '../../shared/api-types';
import { AttentionPanel } from '../components/docs/AttentionPanel';
import { DocInspector } from '../components/docs/DocInspector';
import { DocReader } from '../components/docs/DocReader';
import { DocTree } from '../components/docs/DocTree';
import { FolderView } from '../components/docs/FolderView';
import { folderKey, vaultAbs } from '../components/docs/kinds';
import { QuickOpen } from '../components/docs/QuickOpen';
import { findDoc, findFolder } from '../components/docs/tree-model';
import { CLIENT_MAX_BYTES, fileToBase64 } from '../components/docs/upload';
import { Lucide } from '../components/Lucide';
import {
  useAdoptOriginal,
  useCreateFolder,
  useDeleteDoc,
  useDeleteFolder,
  useDocDetail,
  useLibraryTree,
  useMoveFolder,
  usePatchDoc,
  useReindexDoc,
  useRemoveOrphan,
  useUploadDoc,
} from '../lib/api/hooks';
import { useDocs } from '../stores/docs';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';

const errMsg = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function DocsScreen() {
  const tree = useLibraryTree();
  const { selection, select, uploads, addUpload, failUpload, removeUpload, quickOpen, setQuickOpen } = useDocs();
  const vaultPath = useSettings((s) => s.vaultPath);
  const fileInput = useRef<HTMLInputElement>(null);

  const upload = useUploadDoc();
  const patchDoc = usePatchDoc();
  const deleteDoc = useDeleteDoc();
  const reindex = useReindexDoc();
  const createFolder = useCreateFolder();
  const moveFolder = useMoveFolder();
  const deleteFolder = useDeleteFolder();
  const adopt = useAdoptOriginal();
  const removeOrphan = useRemoveOrphan();

  const data = tree.data;
  const selectedDoc = data && selection?.type === 'doc' ? findDoc(data, selection.docId) : null;
  const detail = useDocDetail(selectedDoc?.doc_id ?? null);

  // The folder shown in the main pane: the selected folder, or the selected doc's folder.
  const folderRef: FolderRef | null =
    selection?.type === 'folder'
      ? selection.ref
      : selectedDoc
        ? { context: selectedDoc.context, project: selectedDoc.project, path: selectedDoc.folder }
        : data?.scopes.find((s) => s.project)
          ? { context: data.scopes.find((s) => s.project)!.context, project: data.scopes.find((s) => s.project)!.project, path: '' }
          : null;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'p') {
        e.preventDefault();
        setQuickOpen(true);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [setQuickOpen]);

  const uploadFiles = useCallback(
    async (files: File[], to: FolderRef) => {
      const key = folderKey(to);
      await Promise.all(
        files.map(async (file) => {
          const id = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
          addUpload({ id, name: file.name, size: file.size, key });
          if (file.size > CLIENT_MAX_BYTES) {
            failUpload(id, 'too large (max 20 MB)');
            toast.error(`${file.name} is larger than 20 MB`);
            return;
          }
          try {
            const res = await upload.mutateAsync({
              context: to.context, project: to.project, folder: to.path, name: file.name,
              mime: file.type, content_b64: await fileToBase64(file),
            });
            removeUpload(id);
            if (res.duplicate) toast.info(`${file.name} is already in the library`);
          } catch (e) {
            failUpload(id, errMsg(e));
            toast.error(`upload failed: ${file.name}: ${errMsg(e)}`);
          }
        }),
      );
    },
    [addUpload, failUpload, removeUpload, upload],
  );

  const run = (p: Promise<unknown>, ok?: string) =>
    p.then(() => ok && toast.success(ok)).catch((e: unknown) => toast.error(errMsg(e)));

  const scopeName = (ctx: string, proj: string | null) =>
    data?.scopes.find((s) => s.context === ctx && s.project === proj)?.name ?? ctx;
  const crumbFor = (ref: FolderRef) => [ref.context, scopeName(ref.context, ref.project), ...ref.path.split('/').filter(Boolean)].join(' / ');

  const openExternal = async () => {
    if (!selectedDoc) return;
    const r = await window.gb.shell.openPath(vaultAbs(vaultPath, selectedDoc.original_path));
    if (!r.ok) toast.error(r.error ?? 'could not open file');
  };
  const reveal = async () => {
    if (!selectedDoc) return;
    const r = await window.gb.shell.showItemInFolder(vaultAbs(vaultPath, selectedDoc.original_path));
    if (!r.ok) toast.error(r.error ?? 'could not reveal file');
  };

  const node = data && folderRef ? findFolder(data, folderRef) : null;
  const scopeArchived = !!data?.scopes.find((s) => folderRef && s.context === folderRef.context && s.project === folderRef.project)?.archived;

  let main: React.ReactNode;
  if (tree.isLoading) main = <div className="p-8 text-13 text-ink-3">loading library…</div>;
  else if (tree.isError) main = <div className="p-8 text-13 text-oxblood">couldn't load the library: {errMsg(tree.error)}</div>;
  else if (selection?.type === 'attention' && data) {
    main = (
      <AttentionPanel
        items={data.attention}
        onAdopt={(it: AttentionItem) => run(adopt.mutateAsync({ context: it.context, project: it.project, folder: it.folder, name: it.name }), `added ${it.name}`)}
        onRemoveOrphan={(id) => run(removeOrphan.mutateAsync(id), 'note moved to trash')}
        onReindex={(id) => run(reindex.mutateAsync(id))}
      />
    );
  } else if (selectedDoc) {
    main = (
      <DocReader
        doc={selectedDoc}
        body={detail.data?.body}
        crumb={crumbFor({ context: selectedDoc.context, project: selectedDoc.project, path: selectedDoc.folder })}
        onClose={() => select({ type: 'folder', ref: { context: selectedDoc.context, project: selectedDoc.project, path: selectedDoc.folder } })}
        onOpenExternal={openExternal}
        onReveal={reveal}
        onDelete={() => {
          const back: FolderRef = { context: selectedDoc.context, project: selectedDoc.project, path: selectedDoc.folder };
          run(deleteDoc.mutateAsync(selectedDoc.doc_id).then(() => select({ type: 'folder', ref: back })), 'moved to trash');
        }}
      />
    );
  } else if (folderRef && node) {
    main = (
      <>
        <div className="flex h-[52px] shrink-0 items-center gap-3 border-b border-hairline px-[18px]">
          <span className="truncate font-mono text-[11.5px] text-ink-2">{crumbFor(folderRef)}</span>
        </div>
        <FolderView
          refKey={folderKey(folderRef)}
          folderRef={folderRef}
          node={node}
          archived={scopeArchived}
          uploads={uploads}
          selectedDocId={null}
          onSelectDoc={(id) => select({ type: 'doc', docId: id })}
          onOpenDoc={(id) => select({ type: 'doc', docId: id })}
          onOpenFolder={(ref) => select({ type: 'folder', ref })}
          onUploadFiles={uploadFiles}
          onNewFolder={(ref) => run(createFolder.mutateAsync({ ...ref, path: ref.path ? `${ref.path}/new folder` : 'new folder' }))}
        />
      </>
    );
  } else {
    main = (
      <div className="grid flex-1 place-items-center text-center text-13 text-ink-2">
        <div>
          <Lucide name="library" size={28} className="mx-auto mb-3 text-ink-3" />
          <div className="text-ink-0">your docs library is empty</div>
          create a project in settings, then drop files onto it
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-1 overflow-hidden bg-paper">
      <aside className="flex w-[258px] shrink-0 flex-col border-r border-hairline">
        <div className="flex items-center justify-between px-3.5 pb-2.5 pt-4">
          <b className="text-15 font-medium text-ink-0">docs</b>
          <button
            type="button"
            disabled={!folderRef || scopeArchived}
            onClick={() => fileInput.current?.click()}
            className="inline-flex items-center gap-1.5 rounded-[7px] bg-neon px-2.5 py-1.5 font-mono text-11 font-semibold text-[#0E0F12] disabled:opacity-40"
          >
            <Lucide name="plus" size={12} /> upload
          </button>
          <input
            ref={fileInput}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              const files = Array.from(e.target.files ?? []);
              e.target.value = '';
              if (folderRef && files.length) void uploadFiles(files, folderRef);
            }}
          />
        </div>
        <button type="button" onClick={() => setQuickOpen(true)} className="mx-3 mb-2.5 flex items-center justify-between rounded-lg border border-hairline bg-vellum px-2.5 py-[7px] text-[12.5px] text-ink-3">
          find a doc… <kbd className="rounded border border-hairline-2 px-1.5 font-mono text-10 text-ink-2">⌘P</kbd>
        </button>
        {data && (
          <DocTree
            tree={data}
            selection={selection}
            onSelect={select}
            onMoveDoc={(docId, to) => run(patchDoc.mutateAsync({ docId, context: to.context, project: to.project, folder: to.path }))}
            onMoveFolder={(from, to) => run(moveFolder.mutateAsync({ from, to }))}
            onUploadFiles={(files, to) => void uploadFiles(files, to)}
            onCreateFolder={(ref) => run(createFolder.mutateAsync(ref))}
            onRenameFolder={(from, to) => run(moveFolder.mutateAsync({ from, to }))}
            onDeleteFolder={(ref) => run(deleteFolder.mutateAsync(ref))}
          />
        )}
      </aside>
      <section className="flex min-w-0 flex-1 flex-col">{main}</section>
      {selectedDoc && (
        <DocInspector
          doc={selectedDoc}
          scopeName={scopeName(selectedDoc.context, selectedDoc.project)}
          onRename={(title) => run(patchDoc.mutateAsync({ docId: selectedDoc.doc_id, title }))}
          onReindex={() => run(reindex.mutateAsync(selectedDoc.doc_id))}
        />
      )}
      <QuickOpen open={quickOpen} onClose={() => setQuickOpen(false)} onPick={(docId) => select({ type: 'doc', docId })} />
    </div>
  );
}
```

- [ ] **Step 5: Wire navigation**

- `stores/navigation.ts`: add `| 'docs'` to `ScreenId`.
- `components/Sidebar.tsx`: in `NAV_ITEMS`, insert `{ id: 'docs', icon: 'library', label: 'docs' },` between the `jots` and `vault` entries.
- `App.tsx`: `import { DocsScreen } from './screens/docs';` and `{active === 'docs' && <DocsScreen />}` next to the `jots` line.

- [ ] **Step 6: Run the full desktop suite + typecheck + lint**

Run: `cd desktop && npx vitest run && npm run typecheck && npm run lint`
Expected: all PASS, with no lint warnings (lint is `--max-warnings 0`; release builds run it).

- [ ] **Step 7: Commit**

```bash
git add desktop/src/renderer/components/docs/QuickOpen.tsx desktop/src/renderer/screens/docs.tsx desktop/src/renderer/stores/navigation.ts desktop/src/renderer/components/Sidebar.tsx desktop/src/renderer/App.tsx desktop/src/renderer/__tests__/DocsScreen.test.tsx
git commit -m "feat(docs): docs screen wiring tree, folder view, reader, inspector and ⌘P

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: End-to-end verification in the running app

**Files:** none (verification only; fix-forward commits if anything breaks)

- [ ] **Step 1: Full test suites**

Run: `uv run --extra dev --extra api pytest -q && cd desktop && npx vitest run && npm run typecheck && npm run lint`
Expected: everything green. If the Python suite was already failing on `origin/main`, record the pre-existing failures first (`git stash; pytest -q; git stash pop`) and show that the set is unchanged.

- [ ] **Step 2: Launch the app**

Use the `run` skill to start the desktop app in dev mode against your real vault. Before starting, check that no recording is live, because the sidecar touches recorder state.

- [ ] **Step 3: Manual checklist (all must pass)**

1. The **docs** rail item appears between jots and vault. The tree shows every context with an "unfiled" scope, plus every project.
2. Drag a real PDF, PNG, DOCX, XLSX and `.md` onto a project folder. Ghost cards appear, then the docs. Each opens in the reader: PDF pages and pager, the image, Office as text, markdown rendered.
3. Grid view shows a PDF first-page thumbnail and the image thumbnail. Switch folders and come back, and the grid choice is remembered.
4. Drag a doc to another project. In Finder (`reveal in folder`), both the original and the `*-xxxxxx.md` note moved.
5. Create, rename and move a folder across projects. Delete a non-empty folder and get the error toast. Delete an empty one and it's gone.
6. Copy a file into a docs folder with Finder. It shows under **needs attention**, and "add to library" adopts it.
7. Trash a doc. Both files are in the macOS Trash.
8. ⌘P finds a doc by partial title.
9. In Chat, ask about the uploaded PDF's content after the scheduler's next semantic refresh (or trigger one), and confirm the answer cites the companion note.
10. Archive a project in settings. Its scope is dimmed, and dropping onto it does nothing.

- [ ] **Step 4: Commit any fixes**, each with its own test, then push the branch only when the user asks.

---

## Self-review notes

- **Spec coverage (slice 1):**

  | Spec section | Task |
  |---|---|
  | §1 layout | 2–4 |
  | §2 index / upload / move / rename / delete / folders / tree / attention / search | 3–6 |
  | §3 API | 7 |
  | §4 `gbdoc://` + uploads + open/reveal | 8, 13 |
  | §6 tree / DnD / list-grid / reader / viewers / thumbnails / inspector (non-AI) / upload feedback / ⌘P | 10–13 |
  | §7 limits + guard + atomic writes | 2, 4, 5, 8 |

  Backlinks and the `/docs` picker (§8) and §5 belong to slices 2–3 and are deliberately absent.
- **Deviations recorded in the spec:** folder-delete uses query params (Task 7 Step 6). Text/code view uses `MarkdownBody`, and attention "relink" is dropped (spec already updated in the planning commit). The tree uses hover action buttons rather than a right-click menu.
- **Known limitation, stated so it isn't mistaken for a bug:** a `.md` original uploaded as a doc is itself indexed by semantic search alongside its companion note (duplicate hit). Acceptable for v1. Revisit if it's noisy.
