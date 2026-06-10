# Rich Markdown Editor + Copy-Formatted Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the bare CodeMirror note editor with a TipTap WYSIWYG markdown editor (markdown shorthand renders as you type, files on disk stay plain markdown), and add one-action "copy formatted" that puts HTML + markdown on the system clipboard so any note pastes rich into Slack/Confluence/Teams. Surfaces: the jots screen and the vault note viewer (`NoteView`), the latter becoming fully editable via a new `PATCH /v1/notes/body` endpoint.

**Architecture:** A shared TipTap extension stack (`desktop/src/renderer/lib/editor/extensions.ts`) is consumed by both the new `RichMarkdownEditor` component and headless round-trip fixture tests, so the fixtures gate the exact schema the user types into. (De)serialisation goes through `tiptap-markdown`; a post-serialise pass restores Obsidian wikilinks that prosemirror-markdown would otherwise escape. Copy-formatted serialises the ProseMirror selection (or whole doc) to HTML + markdown in the renderer and ships it over a new `gb:clipboard:write-rich` IPC channel to Electron `clipboard.write({ html, text })`. Jot saves keep using `PATCH /v1/notes/{jot_id}`; vault-note saves use the new by-path endpoint, which rewrites only the body, preserves all frontmatter keys, and bumps `updated` when that key exists. A footer toggle swaps to the existing CodeMirror `JotEditor` as a source-mode escape hatch.

**Tech Stack:** Python 3.11 + FastAPI (sidecar), pytest + python-frontmatter (backend), Electron + React 18 + TypeScript (desktop), TipTap 2.27.2 + tiptap-markdown 0.8.10 (editor), Zustand (state), React Query (data), Vitest + React Testing Library + jsdom (renderer/main tests).

**Spec:** `docs/superpowers/specs/2026-06-09-rich-markdown-editor-design.md`

**Branch:** `feat/rich-markdown-editor` (this worktree). All `pytest` commands run from the worktree root with the repo venv: `/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest …`. All desktop commands run from `desktop/`.

Facts verified against the working tree before writing this plan (do not re-litigate them):

1. **Route shadowing is real.** `ghostbrain/api/routes/notes.py` already has `PATCH /{jot_id}` with `PathParam(..., min_length=8)`. Starlette matches routes in registration order and the path segment `body` (4 chars) satisfies the `/{jot_id}` regex, so the jot route captures it and the validator 422s (`string_too_short`) — it does NOT fall through to a later `/body` route. Verified empirically with a scratch FastAPI app: `/{jot_id}`-first → 422; `/body`-first → 200. The new route MUST be registered physically above `patch_note` in the file.
2. **`tiptap-markdown@0.9.0` requires TipTap v3** (`peerDependencies: { '@tiptap/core': '^3.0.1' }`). The v2-compatible line is `0.8.10` (`@tiptap/core ^2.0.3`). This plan pins TipTap `2.27.2` + tiptap-markdown `0.8.10`.
3. **Task lists serialize loose by default.** tiptap-markdown's internal `MarkdownTightLists` extension only registers the `tight` attribute on `bulletList`/`orderedList`; `taskList` serialisation delegates to bulletList's `renderList`, which reads `node.attrs.tight` — absent attribute → blank line between items. A small global-attribute extension (`TaskListTight`, Task 3) fixes it. Verified headless: with the fix, `- [ ] a\n- [x] b` round-trips byte-stable.
4. **Wikilinks get corrupted without a fix.** prosemirror-markdown escapes brackets: `[[a/_b]]` → `\[\[a/\_b\]\]`. Since vault notes contain `[[wikilinks]]`, an editable vault viewer would corrupt files on save. `restoreWikilinks()` (Task 3) post-processes the serialised output; verified to restore plain, underscore, and `|alias` forms byte-stable. Intraword underscores, `#hashtags`, and bare `|` are NOT escaped by the serializer (verified) and need no handling.
5. **All 12 round-trip fixtures in Task 3 were executed against the exact pinned versions and pass.** Two accepted canonicalisations are encoded in the fixtures: soft line breaks inside a paragraph collapse to spaces (CommonMark-equivalent), so the multi-line blockquote fixture uses `>` paragraph separators; tight lists stay tight, loose stay loose.
6. **`frontmatter.dumps` with empty metadata emits a literal `---\n{}\n---` block.** Verified with the repo venv. `save_note_body` must special-case frontmatter-less files so plain markdown files don't gain a `{}` header.
7. **The "vault note viewer" is `desktop/src/renderer/components/NoteView.tsx`** — a slide-over dialog mounted once in `App.tsx` and opened via the `useNoteView` zustand store from today/daily/meetings/AskPanel/MeetingPrep. `screens/vault.tsx` is just an "open vault folder in Finder" page with no viewer; it is untouched by this plan.

---

## Task 1: Backend repo — `save_note_body(path, body)`

**Files:**
- Modify: `ghostbrain/api/repo/note.py`
- Test: `ghostbrain/api/tests/test_repo_note_save.py` (create)

The function lives next to `get_note` and reuses the existing `_resolve_safe` path guard (vault containment, `..` rejection, `.md`-only). It rewrites only the body, preserves every frontmatter key, and bumps `updated` only when that key already exists (it never invents one — connector files own their schema).

- [ ] **Step 1: Write the failing test**

Create `ghostbrain/api/tests/test_repo_note_save.py`:

```python
"""save_note_body — frontmatter-preserving body rewrite for the rich editor."""
import frontmatter
import pytest

from ghostbrain.api.repo.note import (
    NoteInvalidPath,
    NoteNotFound,
    save_note_body,
)
from ghostbrain.api.tests.conftest import write_note

SYNCED = (
    "---\n"
    "source: gmail\n"
    "context: sanlam\n"
    "tags:\n"
    "- mail\n"
    "updated: '2026-01-01T00:00:00+00:00'\n"
    "---\n"
    "\n"
    "old body\n"
)


def test_save_rewrites_body_and_preserves_frontmatter(tmp_vault):
    write_note(tmp_vault, "20-contexts/sanlam/notes/synced.md", SYNCED)
    result = save_note_body("20-contexts/sanlam/notes/synced.md", "# edited\n\nnew body")
    post = frontmatter.load(tmp_vault / "20-contexts/sanlam/notes/synced.md")
    assert post.content.strip() == "# edited\n\nnew body"
    # connector-managed file: every frontmatter key survives untouched
    assert post["source"] == "gmail"
    assert post["context"] == "sanlam"
    assert post["tags"] == ["mail"]
    assert result["path"] == "20-contexts/sanlam/notes/synced.md"


def test_save_bumps_updated_when_key_exists(tmp_vault):
    write_note(tmp_vault, "20-contexts/sanlam/notes/synced.md", SYNCED)
    result = save_note_body("20-contexts/sanlam/notes/synced.md", "new body")
    post = frontmatter.load(tmp_vault / "20-contexts/sanlam/notes/synced.md")
    assert post["updated"] != "2026-01-01T00:00:00+00:00"
    assert result["updated"] == post["updated"]


def test_save_does_not_invent_updated_key(tmp_vault):
    write_note(
        tmp_vault,
        "20-contexts/personal/notes/no-updated.md",
        "---\nsource: manual\n---\n\nbody\n",
    )
    result = save_note_body("20-contexts/personal/notes/no-updated.md", "rewritten")
    post = frontmatter.load(tmp_vault / "20-contexts/personal/notes/no-updated.md")
    assert "updated" not in post.metadata
    assert result["updated"] is None


def test_save_plain_file_stays_frontmatter_free(tmp_vault):
    # frontmatter.dumps with empty metadata would emit a literal `---\n{}\n---`
    # block — the repo fn must special-case this (verified hazard).
    write_note(tmp_vault, "10-daily/2026-06-09.md", "plain body, no frontmatter\n")
    save_note_body("10-daily/2026-06-09.md", "rewritten")
    raw = (tmp_vault / "10-daily/2026-06-09.md").read_text()
    assert raw == "rewritten\n"
    assert "---" not in raw


def test_save_unknown_path_raises(tmp_vault):
    with pytest.raises(NoteNotFound):
        save_note_body("20-contexts/sanlam/notes/missing.md", "x")


def test_save_traversal_rejected(tmp_vault):
    with pytest.raises(NoteInvalidPath):
        save_note_body("../../etc/passwd.md", "x")


def test_save_non_md_rejected(tmp_vault):
    with pytest.raises(NoteInvalidPath):
        save_note_body("20-contexts/sanlam/notes/script.sh", "x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/test_repo_note_save.py -q`
Expected: FAIL — `ImportError: cannot import name 'save_note_body'`.

- [ ] **Step 3: Implement `save_note_body`**

Append to `ghostbrain/api/repo/note.py` (after `get_note`):

```python
def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def save_note_body(rel_path: str, body: str) -> dict:
    """Rewrite only the markdown body of a vault note; frontmatter preserved.

    - Bumps ``updated`` when the key already exists (house convention from
      notes_manual); never invents the key — connector files own their schema.
    - Files without frontmatter stay frontmatter-free: ``frontmatter.dumps``
      with empty metadata would otherwise emit a literal ``---\\n{}\\n---``
      block (verified against python-frontmatter in this venv).
    - Path validation reuses the house ``_resolve_safe`` guard.
    """
    target = _resolve_safe(rel_path)
    if not target.exists() or not target.is_file():
        raise NoteNotFound(rel_path)
    try:
        post = frontmatter.load(target)
    except Exception as e:
        raise NoteNotFound(f"could not parse: {e}")
    post.content = body
    if "updated" in post.metadata:
        post["updated"] = _now_iso()
    if post.metadata:
        target.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    else:
        target.write_text(body if body.endswith("\n") else body + "\n", encoding="utf-8")
    updated = post.metadata.get("updated")
    return {"path": rel_path, "updated": str(updated) if updated is not None else None}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/test_repo_note_save.py -q`
Expected: PASS — 7 tests green.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/note.py ghostbrain/api/tests/test_repo_note_save.py
git commit -m "feat(api): save_note_body — frontmatter-preserving by-path body rewrite"
```

---

## Task 2: Backend route — `PATCH /v1/notes/body` (registered BEFORE `/{jot_id}`)

**Files:**
- Modify: `ghostbrain/api/models/note.py`
- Modify: `ghostbrain/api/routes/notes.py`
- Test: `ghostbrain/api/tests/test_routes_notes_body.py` (create)

- [ ] **Step 1: Write the failing test**

Create `ghostbrain/api/tests/test_routes_notes_body.py`:

```python
"""PATCH /v1/notes/body — by-path body rewrite for the rich editor."""
from datetime import datetime, timezone

import frontmatter

from ghostbrain.api.repo.notes_manual import write_inbox_jot
from ghostbrain.api.tests.conftest import write_note

SYNCED = (
    "---\n"
    "source: gmail\n"
    "context: sanlam\n"
    "updated: '2026-01-01T00:00:00+00:00'\n"
    "---\n"
    "\n"
    "old body\n"
)


def test_patch_body_rewrites_and_preserves_frontmatter(tmp_vault, client, auth_headers):
    write_note(tmp_vault, "20-contexts/sanlam/notes/synced.md", SYNCED)
    resp = client.patch(
        "/v1/notes/body",
        json={"path": "20-contexts/sanlam/notes/synced.md", "body": "# edited\n\nnew body"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["path"] == "20-contexts/sanlam/notes/synced.md"
    post = frontmatter.load(tmp_vault / "20-contexts/sanlam/notes/synced.md")
    assert post.content.strip() == "# edited\n\nnew body"
    # connector file edit is allowed; source key untouched
    assert post["source"] == "gmail"
    assert post["updated"] != "2026-01-01T00:00:00+00:00"
    assert data["updated"] == post["updated"]


def test_patch_body_not_shadowed_by_jot_route(tmp_vault, client, auth_headers):
    """Regression guard for route ordering.

    PATCH /{jot_id} has min_length=8 on the path param; "body" (4 chars)
    matches its path regex, so if /body were registered after it, this request
    would return 422 string_too_short from the jot route's validator instead
    of reaching the by-path handler (verified empirically). This test pins the
    registration order.
    """
    write_note(
        tmp_vault,
        "20-contexts/personal/notes/n.md",
        "---\nupdated: '2026-01-01T00:00:00+00:00'\n---\n\nx\n",
    )
    resp = client.patch(
        "/v1/notes/body",
        json={"path": "20-contexts/personal/notes/n.md", "body": "y"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["path"] == "20-contexts/personal/notes/n.md"


def test_patch_body_jot_route_still_reachable(tmp_vault, client, auth_headers):
    (tmp_vault / "00-inbox" / "raw" / "manual").mkdir(parents=True, exist_ok=True)
    when = datetime(2026, 6, 9, 9, 0, 0, tzinfo=timezone.utc)
    rec = write_inbox_jot("still works", captured_at=when)
    resp = client.patch(
        f"/v1/notes/{rec['id']}", json={"body": "edited jot"}, headers=auth_headers
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == rec["id"]


def test_patch_body_unknown_path_404(tmp_vault, client, auth_headers):
    resp = client.patch(
        "/v1/notes/body",
        json={"path": "20-contexts/sanlam/notes/missing.md", "body": "x"},
        headers=auth_headers,
    )
    assert resp.status_code == 404


def test_patch_body_traversal_400(tmp_vault, client, auth_headers):
    resp = client.patch(
        "/v1/notes/body",
        json={"path": "../../etc/passwd.md", "body": "x"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_patch_body_empty_body_422(tmp_vault, client, auth_headers):
    write_note(
        tmp_vault,
        "20-contexts/sanlam/notes/n.md",
        "---\nsource: manual\n---\n\nbody\n",
    )
    resp = client.patch(
        "/v1/notes/body",
        json={"path": "20-contexts/sanlam/notes/n.md", "body": "   "},
        headers=auth_headers,
    )
    assert resp.status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/test_routes_notes_body.py -q`
Expected: FAIL — `test_patch_body_not_shadowed_by_jot_route` and friends get **422** (`string_too_short` from the `/{jot_id}` path validator), proving the shadowing hazard; 404/400 cases also 422 for the same reason.

- [ ] **Step 3: Add the request model**

Edit `ghostbrain/api/models/note.py` — add after the existing `UpdateNoteRequest` class:

```python
class UpdateNoteBodyRequest(BaseModel):
    """PATCH /v1/notes/body — rich-editor save for any vault note by path."""

    path: str  # vault-relative
    body: str
```

- [ ] **Step 4: Add the route — physically above `patch_note`**

Edit `ghostbrain/api/routes/notes.py`. First widen the imports:

Replace:

```python
from ghostbrain.api.models.note import CreateNoteRequest, RouteNoteRequest, UpdateNoteRequest
from ghostbrain.api.repo.note import NoteInvalidPath, NoteNotFound, get_note
```

with:

```python
from ghostbrain.api.models.note import (
    CreateNoteRequest,
    RouteNoteRequest,
    UpdateNoteBodyRequest,
    UpdateNoteRequest,
)
from ghostbrain.api.repo.note import (
    NoteInvalidPath,
    NoteNotFound,
    get_note,
    save_note_body,
)
```

Then insert this route **immediately above** the existing `@router.patch("/{jot_id}")` / `def patch_note(` block (order is load-bearing):

```python
# ── Order-sensitive: /body must be registered BEFORE /{jot_id} ──────────────
# Starlette matches routes in registration order, and the literal segment
# "body" satisfies the /{jot_id} path regex ([^/]+). The jot route's
# min_length=8 validator would then 422 the request ("string_too_short")
# instead of falling through to this handler. Pinned by
# test_patch_body_not_shadowed_by_jot_route.
@router.patch("/body")
def patch_note_body(req: UpdateNoteBodyRequest) -> dict:
    """Rewrite the markdown body of any vault note by path.

    Frontmatter is preserved; `updated` bumped when the key exists. Unlike the
    jot PATCH, this does NOT re-derive tags — connector files own their schema.
    """
    if not req.body.strip():
        raise HTTPException(status_code=422, detail="body must not be empty")
    try:
        return save_note_body(req.path, req.body)
    except NoteInvalidPath as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NoteNotFound:
        raise HTTPException(status_code=404, detail=f"Note not found: {req.path}")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/test_routes_notes_body.py ghostbrain/api/tests/test_routes_notes_mutate.py -q`
Expected: PASS — 6 new tests + the 5 pre-existing jot-mutation tests all green (proves the jot family is unaffected).

- [ ] **Step 6: Run the full backend suite**

Run: `/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/ -q`
Expected: PASS — 104 passed (91 pre-existing + 7 from Task 1 + 6 from this task).

- [ ] **Step 7: Commit**

```bash
git add ghostbrain/api/models/note.py ghostbrain/api/routes/notes.py \
        ghostbrain/api/tests/test_routes_notes_body.py
git commit -m "feat(api): PATCH /v1/notes/body — by-path note save, registered before /{jot_id}"
```

---

## Task 3: TipTap deps + shared extension stack + headless round-trip fixtures

**Files:**
- Modify: `desktop/package.json` (+ lockfile)
- Create: `desktop/src/renderer/lib/editor/extensions.ts`
- Create: `desktop/src/renderer/lib/editor/markdown.ts`
- Test: `desktop/src/renderer/__tests__/markdown-roundtrip.test.ts` (create)

The fixtures are the feature gate (spec §Testing). The extension stack is a single shared module so the component (Task 4) and the fixtures test the exact same schema. Every fixture below was executed against `@tiptap/*@2.27.2` + `tiptap-markdown@0.8.10` in jsdom before this plan was written — all pass.

- [ ] **Step 1: Install the pinned dependencies**

```bash
cd desktop && npm install @tiptap/react@2.27.2 @tiptap/core@2.27.2 @tiptap/pm@2.27.2 \
  @tiptap/starter-kit@2.27.2 @tiptap/extension-link@2.27.2 \
  @tiptap/extension-table@2.27.2 @tiptap/extension-table-row@2.27.2 \
  @tiptap/extension-table-cell@2.27.2 @tiptap/extension-table-header@2.27.2 \
  @tiptap/extension-task-list@2.27.2 @tiptap/extension-task-item@2.27.2 \
  tiptap-markdown@0.8.10
```

Do NOT upgrade `tiptap-markdown` to 0.9.x: it peer-depends on `@tiptap/core ^3.0.1` (TipTap v3, which also reorganises the extension packages). Nothing TipTap was previously installed (verified against `desktop/package.json`).

- [ ] **Step 2: Write the failing round-trip test**

Create `desktop/src/renderer/__tests__/markdown-roundtrip.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import { Editor } from '@tiptap/core';
import { buildEditorExtensions } from '../lib/editor/extensions';
import { getMarkdown } from '../lib/editor/markdown';

/**
 * Feature gate (spec §Testing): representative markdown must survive
 * editor in→out byte-stable, modulo trailing whitespace.
 *
 * Fixtures are written in the editor's canonical CommonMark/GFM form. Two
 * known, accepted canonicalisations (CommonMark-equivalent, byte-different):
 *  - soft line breaks inside a paragraph collapse to spaces — multi-line
 *    blockquotes therefore use `>` paragraph separators;
 *  - tight lists stay tight, loose lists stay loose (TaskListTight in the
 *    extension stack keeps task lists tight; without it they'd serialise
 *    with blank lines between items).
 */
function roundTrip(md: string): string {
  const editor = new Editor({ extensions: buildEditorExtensions(), content: md });
  try {
    return getMarkdown(editor);
  } finally {
    editor.destroy();
  }
}

function normalize(md: string): string {
  return md
    .split('\n')
    .map((line) => line.replace(/\s+$/, ''))
    .join('\n')
    .replace(/\n+$/, '');
}

const FIXTURES: Record<string, string> = {
  headings: '# h1\n\n## h2\n\n### h3\n\nbody text',
  emphasis: '**bold** and *italic* and `inline code`',
  'nested bullet lists': '- top\n  - nested\n    - deeper\n- second top',
  'ordered list': '1. first\n2. second\n3. third',
  'task list with checkbox state': '- [ ] open item\n- [x] done item',
  'nested task list': '- [ ] parent\n  - [x] child',
  table: '| name | value |\n| --- | --- |\n| alpha | 1 |\n| beta | 2 |',
  'fenced code with language': '```python\ndef hello():\n    return "world"\n```',
  link: 'see [the docs](https://example.com/docs) for more',
  blockquote: '> quoted line one\n>\n> quoted line two',
  'obsidian wikilinks': 'see [[20-contexts/sanlam/_profile]] and [[a/b|Title]]',
  'mixed document':
    '# meeting notes\n\n' +
    'context for **the ascp wizard** and `route_event`:\n\n' +
    '- [ ] follow up with [the docs](https://example.com)\n- [x] shipped\n\n' +
    '```ts\nconst x = 1;\n```',
};

describe('markdown round-trip (serialize(deserialize(md)))', () => {
  for (const [name, fixture] of Object.entries(FIXTURES)) {
    it(`round-trips ${name}`, () => {
      expect(normalize(roundTrip(fixture))).toBe(normalize(fixture));
    });
  }
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/markdown-roundtrip.test.ts`
Expected: FAIL — `Cannot find module '../lib/editor/extensions'`.

- [ ] **Step 4: Create the shared extension stack**

Create `desktop/src/renderer/lib/editor/extensions.ts`:

```typescript
import { Extension } from '@tiptap/core';
import type { Extensions } from '@tiptap/core';
import StarterKit from '@tiptap/starter-kit';
import Link from '@tiptap/extension-link';
import Table from '@tiptap/extension-table';
import TableRow from '@tiptap/extension-table-row';
import TableCell from '@tiptap/extension-table-cell';
import TableHeader from '@tiptap/extension-table-header';
import TaskList from '@tiptap/extension-task-list';
import TaskItem from '@tiptap/extension-task-item';
import { Markdown } from 'tiptap-markdown';

/**
 * tiptap-markdown's internal MarkdownTightLists extension only registers the
 * `tight` attribute on bulletList/orderedList. taskList serialisation
 * delegates to bulletList's renderList, which reads `node.attrs.tight` —
 * without the attribute, task lists serialise loose (blank line between
 * items) and fail the round-trip fixtures. This mirror extension closes the
 * gap. (Verified against the tiptap-markdown@0.8.10 dist source.)
 */
const TaskListTight = Extension.create({
  name: 'taskListTight',
  addGlobalAttributes() {
    return [
      {
        types: ['taskList'],
        attributes: {
          tight: {
            default: true,
            parseHTML: (element: HTMLElement) =>
              element.getAttribute('data-tight') === 'true' || !element.querySelector('p'),
            renderHTML: (attributes: { tight?: boolean }) => ({
              'data-tight': attributes.tight ? 'true' : null,
            }),
          },
        },
      },
    ];
  },
});

/**
 * Single source of truth for the editor schema. RichMarkdownEditor AND the
 * headless round-trip fixture tests both build from this — a fixture pass
 * therefore proves the exact schema the user types into.
 */
export function buildEditorExtensions(): Extensions {
  return [
    StarterKit,
    Link.configure({ openOnClick: false }),
    Table.configure({ resizable: false }),
    TableRow,
    TableHeader,
    TableCell,
    TaskList,
    TaskItem.configure({ nested: true }),
    TaskListTight,
    Markdown.configure({
      html: false, // vault files are plain markdown; raw HTML is dropped
      tightLists: true,
      linkify: false,
      breaks: false,
      transformPastedText: true, // pasting markdown text parses it
      transformCopiedText: false, // copy-formatted has its own path (Task 6)
    }),
  ];
}
```

- [ ] **Step 5: Create the serialiser helpers**

Create `desktop/src/renderer/lib/editor/markdown.ts`:

```typescript
import type { Editor } from '@tiptap/core';
import { DOMSerializer } from '@tiptap/pm/model';

/** Shape of tiptap-markdown's editor.storage.markdown (set in onBeforeCreate;
 * verified against the 0.8.10 dist source). */
interface MarkdownStorage {
  getMarkdown(): string;
  serializer: { serialize(content: unknown): string };
}

function mdStorage(editor: Editor): MarkdownStorage {
  return editor.storage.markdown as unknown as MarkdownStorage;
}

// prosemirror-markdown escapes "[" / "]" (and emphasis chars adjacent to
// them), which corrupts Obsidian wikilinks: [[a/_b]] → \[\[a/\_b\]\]. Restore
// them after serialisation; the inner unescape only touches backslash-escaped
// punctuation INSIDE the [[...]] span. Intraword underscores, #hashtags and
// bare pipes are not escaped by the serializer (verified) — no handling
// needed outside wikilinks.
const ESCAPED_WIKILINK_RE = /\\\[\\\[(.+?)\\\]\\\]/g;

export function restoreWikilinks(md: string): string {
  return md.replace(
    ESCAPED_WIKILINK_RE,
    (_m, inner: string) => `[[${inner.replace(/\\([\\_*[\]|`~#])/g, '$1')}]]`,
  );
}

/** Serialize the whole document to vault markdown. */
export function getMarkdown(editor: Editor): string {
  return restoreWikilinks(mdStorage(editor).getMarkdown());
}

export interface ClipboardPayload {
  html: string;
  markdown: string;
}

/**
 * Selection-aware payload for copy-formatted (spec: selection if one exists,
 * otherwise the whole note):
 *  - empty selection → whole doc as HTML + markdown;
 *  - otherwise → only the selected slice, HTML via DOMSerializer on the slice
 *    fragment, markdown via tiptap-markdown's serializer on a doc node built
 *    from the slice (falls back to plain text if the slice cannot form a doc).
 */
export function clipboardPayload(editor: Editor): ClipboardPayload {
  if (editor.state.selection.empty) {
    return { html: editor.getHTML(), markdown: getMarkdown(editor) };
  }
  const slice = editor.state.selection.content();
  const container = document.createElement('div');
  container.appendChild(
    DOMSerializer.fromSchema(editor.schema).serializeFragment(slice.content),
  );
  const docNode = editor.schema.topNodeType.createAndFill(null, slice.content);
  const markdown = docNode
    ? restoreWikilinks(mdStorage(editor).serializer.serialize(docNode))
    : editor.state.doc.textBetween(
        editor.state.selection.from,
        editor.state.selection.to,
        '\n',
      );
  return { html: container.innerHTML, markdown };
}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/__tests__/markdown-roundtrip.test.ts`
Expected: PASS — 12 fixtures green. (These exact fixtures were pre-validated against the pinned versions; a failure here means an install/version drift — check `npm ls @tiptap/core tiptap-markdown` shows 2.27.2 / 0.8.10.)

Also run: `cd desktop && npm run typecheck`
Expected: no type errors.

- [ ] **Step 7: Commit**

```bash
git add desktop/package.json desktop/package-lock.json \
        desktop/src/renderer/lib/editor/extensions.ts \
        desktop/src/renderer/lib/editor/markdown.ts \
        desktop/src/renderer/__tests__/markdown-roundtrip.test.ts
git commit -m "feat(desktop): TipTap v2 stack + markdown round-trip fixture gate"
```

---

## Task 4: `RichMarkdownEditor` component (WYSIWYG + autosave + source toggle)

**Files:**
- Create: `desktop/src/renderer/components/RichMarkdownEditor.tsx`
- Test: `desktop/src/renderer/__tests__/RichMarkdownEditor.test.tsx` (create)

Inherits `JotEditor`'s autosave semantics verbatim: 1s debounce, save only on change, pending timer cancelled on prop switch (cross-write guard), unmount cleanup, optimistic `lastSaved`. Adds: spec props (`markdown`, `onSave`, `readOnly?`, `debounceMs?`), a footer `rich`/`src` toggle that swaps to the existing CodeMirror `JotEditor`, and automatic source-mode fallback when markdown fails to parse (never block opening a note).

Test-driving note (house pattern, same reason as the CodeMirror tests): jsdom lacks the layout APIs that `userEvent.type` needs, so tests capture the `Editor` instance via an `onEditorReady` prop (mirrors `JotEditor`'s `onCreateEditor`) and drive changes through TipTap commands / ProseMirror transactions.

- [ ] **Step 1: Write the failing test**

Create `desktop/src/renderer/__tests__/RichMarkdownEditor.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import type { Editor } from '@tiptap/core';
import { RichMarkdownEditor } from '../components/RichMarkdownEditor';

vi.useFakeTimers();

function lastMarkdown(onSave: ReturnType<typeof vi.fn>): string {
  return onSave.mock.calls[onSave.mock.calls.length - 1]![0] as string;
}

describe('RichMarkdownEditor', () => {
  beforeEach(() => {
    vi.clearAllTimers();
  });

  afterEach(() => {
    vi.clearAllTimers();
  });

  it('renders markdown as rich nodes', () => {
    const { container } = render(
      <RichMarkdownEditor markdown={'# title\n\nbody text'} onSave={() => {}} />,
    );
    const h1 = container.querySelector('h1');
    expect(h1).not.toBeNull();
    expect(h1!.textContent).toBe('title');
    expect(screen.getByText('body text')).toBeInTheDocument();
  });

  it('applies the heading input rule while typing ("# " + space)', () => {
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown=""
        onSave={() => {}}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    expect(editor).toBeDefined();
    act(() => {
      const view = editor!.view;
      view.dispatch(view.state.tr.insertText('#', 1, 1));
      // Direct transactions bypass ProseMirror input rules; feed the plugin's
      // handleTextInput exactly like a real keystroke would.
      const handled = view.someProp('handleTextInput', (f) => f(view, 2, 2, ' '));
      expect(handled).toBe(true);
    });
    expect(editor!.state.doc.firstChild!.type.name).toBe('heading');
    expect(editor!.state.doc.firstChild!.attrs.level).toBe(1);
  });

  it('debounces autosave to 1s after the last change', () => {
    const onSave = vi.fn();
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown="initial"
        onSave={onSave}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    act(() => {
      editor!.commands.insertContentAt(editor!.state.doc.content.size, ' added');
    });
    expect(onSave).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(999);
    });
    expect(onSave).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(2);
    });
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(lastMarkdown(onSave)).toContain('added');
  });

  it('does not save when content is unchanged', () => {
    const onSave = vi.fn();
    render(<RichMarkdownEditor markdown="same" onSave={onSave} debounceMs={100} />);
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(onSave).not.toHaveBeenCalled();
  });

  it('cancels a pending save when the markdown prop switches (no cross-write)', () => {
    const onSave = vi.fn();
    let editor: Editor | undefined;
    const { rerender } = render(
      <RichMarkdownEditor
        markdown="A"
        onSave={onSave}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    // Edit note A — a debounced save is now pending with A's edited content.
    act(() => {
      editor!.commands.insertContentAt(editor!.state.doc.content.size, ' edited');
    });
    // Switch to note B before the debounce fires (component stays mounted).
    rerender(
      <RichMarkdownEditor markdown="B" onSave={onSave} onEditorReady={() => {}} />,
    );
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(onSave).not.toHaveBeenCalled();
  });

  it('does not fire a pending save after unmount', () => {
    const onSave = vi.fn();
    let editor: Editor | undefined;
    const { unmount } = render(
      <RichMarkdownEditor
        markdown="A"
        onSave={onSave}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    act(() => {
      editor!.commands.insertContentAt(editor!.state.doc.content.size, ' x');
    });
    unmount();
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(onSave).not.toHaveBeenCalled();
  });

  it('swaps to the CodeMirror source editor via the footer toggle', () => {
    const { container } = render(
      <RichMarkdownEditor markdown={'# title'} onSave={() => {}} />,
    );
    expect(container.querySelector('.cm-editor')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'src' }));
    expect(container.querySelector('.cm-editor')).not.toBeNull();
    // Source mode shows raw markdown, not a rendered heading.
    expect(screen.getByText(/# title/)).toBeInTheDocument();
    // and back:
    fireEvent.click(screen.getByRole('button', { name: 'rich' }));
    expect(container.querySelector('.cm-editor')).toBeNull();
    expect(container.querySelector('h1')).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/RichMarkdownEditor.test.tsx`
Expected: FAIL — `Cannot find module '../components/RichMarkdownEditor'`.

- [ ] **Step 3: Implement the component**

Create `desktop/src/renderer/components/RichMarkdownEditor.tsx`:

```typescript
import { useEffect, useRef, useState } from 'react';
import { Editor } from '@tiptap/core';
import { EditorContent, useEditor } from '@tiptap/react';
import { buildEditorExtensions } from '../lib/editor/extensions';
import { getMarkdown } from '../lib/editor/markdown';
import { toast } from '../stores/toast';
import { JotEditor } from './JotEditor';

interface Props {
  markdown: string;
  onSave: (markdown: string) => void;
  readOnly?: boolean;
  /** Autosave debounce in ms. Defaults to 1000. */
  debounceMs?: number;
  /** Called once when the TipTap Editor instance is created; useful for tests. */
  onEditorReady?: (editor: Editor) => void;
}

type Mode = 'rich' | 'source';

/** Pre-flight parse probe so markdown the rich editor cannot represent never
 * blocks opening a note (spec: automatic fallback to source mode + toast).
 * Costs one throwaway parse per mount — notes are small, acceptable. */
function parsesAsRich(markdown: string): boolean {
  try {
    const probe = new Editor({ extensions: buildEditorExtensions(), content: markdown });
    probe.destroy();
    return true;
  } catch {
    return false;
  }
}

export function RichMarkdownEditor({
  markdown,
  onSave,
  readOnly = false,
  debounceMs = 1000,
  onEditorReady,
}: Props) {
  // Evaluated once per mount; parents remount per note via key={...}.
  const [parseFailed] = useState(() => !parsesAsRich(markdown));
  const [mode, setMode] = useState<Mode>(parseFailed ? 'source' : 'rich');

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSaved = useRef(markdown);
  // Latest content from either mode — handed over when toggling so no
  // keystrokes are lost.
  const current = useRef(markdown);

  useEffect(() => {
    if (parseFailed) {
      toast.error('note could not be opened in rich mode — falling back to source');
    }
    // mount-only: parseFailed is fixed for the lifetime of the component
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function scheduleSave(next: string) {
    current.current = next;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      if (next !== lastSaved.current) {
        // Deliberate trade-off (same as JotEditor): lastSaved advances even
        // if the caller's save fails — no retry for debounced autosave.
        lastSaved.current = next;
        onSave(next);
      }
    }, debounceMs);
  }

  const editor = useEditor({
    extensions: buildEditorExtensions(),
    content: parseFailed ? '' : markdown,
    editable: !readOnly,
    onCreate: ({ editor: created }) => {
      onEditorReady?.(created);
    },
    onUpdate: ({ editor: updated }) => {
      scheduleSave(getMarkdown(updated));
    },
  });

  // Cross-write guard (mirrors JotEditor): if the markdown prop switches
  // while a save is pending, the stale timer would fire with the previous
  // note's content — cancel it and resync the document.
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    lastSaved.current = markdown;
    current.current = markdown;
    if (editor && !editor.isDestroyed && getMarkdown(editor) !== markdown) {
      try {
        // tiptap-markdown overrides setContent to parse markdown strings;
        // emitUpdate=false so the resync never schedules a save.
        editor.commands.setContent(markdown, false);
      } catch {
        setMode('source');
      }
    }
    // `editor` deliberately omitted: this effect must run on body switches,
    // not on editor (re)creation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [markdown]);

  // Unmount cleanup — no save may fire after the component is gone.
  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  function switchMode(next: Mode) {
    if (next === mode) return;
    if (next === 'source') {
      if (editor && !editor.isDestroyed) current.current = getMarkdown(editor);
      setMode('source');
      return;
    }
    if (!editor || editor.isDestroyed) return;
    try {
      editor.commands.setContent(current.current, false);
      setMode('rich');
    } catch {
      toast.error('could not parse markdown — staying in source mode');
    }
  }

  return (
    <div className="flex h-full flex-col" data-testid="rich-markdown-editor">
      <div className="flex-1 overflow-auto">
        {mode === 'rich' ? (
          <EditorContent
            editor={editor}
            className="gb-prose h-full px-4 py-3 text-14 leading-[1.65] text-ink-0 [&_.ProseMirror]:min-h-full [&_.ProseMirror]:outline-none"
          />
        ) : (
          <JotEditor
            body={current.current}
            debounceMs={debounceMs}
            onSave={(next) => {
              current.current = next;
              lastSaved.current = next;
              onSave(next);
            }}
          />
        )}
      </div>
      <div className="flex flex-shrink-0 items-center gap-2 border-t border-hairline px-3 py-[6px]">
        <div className="ml-auto flex items-center gap-1 font-mono text-10 text-ink-3">
          <button
            type="button"
            onClick={() => switchMode('rich')}
            className={
              mode === 'rich'
                ? 'rounded-sm bg-vellum px-2 py-[2px] text-ink-0'
                : 'rounded-sm px-2 py-[2px] hover:text-ink-1'
            }
          >
            rich
          </button>
          <button
            type="button"
            onClick={() => switchMode('source')}
            className={
              mode === 'source'
                ? 'rounded-sm bg-vellum px-2 py-[2px] text-ink-0'
                : 'rounded-sm px-2 py-[2px] hover:text-ink-1'
            }
          >
            src
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/__tests__/RichMarkdownEditor.test.tsx`
Expected: PASS — 7 tests green.

Also run: `cd desktop && npm run typecheck`
Expected: no type errors.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/components/RichMarkdownEditor.tsx \
        desktop/src/renderer/__tests__/RichMarkdownEditor.test.tsx
git commit -m "feat(desktop): RichMarkdownEditor — TipTap WYSIWYG with autosave + source toggle"
```

---

## Task 5: Clipboard IPC — `gb:clipboard:write-rich`

**Files:**
- Create: `desktop/src/main/clipboard.ts`
- Modify: `desktop/src/main/index.ts`
- Modify: `desktop/src/preload/index.ts`
- Modify: `desktop/src/shared/types.ts`
- Modify: `desktop/src/renderer/test/setup.ts` (the GbBridge stub must satisfy the widened type)
- Test: `desktop/src/main/__tests__/clipboard.test.ts` (create)

- [ ] **Step 1: Write the failing test**

Create `desktop/src/main/__tests__/clipboard.test.ts` (vi.hoisted + vi.mock pattern, same as `jot-overlay.test.ts`):

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';

// vi.hoisted: vi.mock factories are hoisted above plain const declarations.
const { clipboardMock, ipcMainMock } = vi.hoisted(() => {
  const clipboardMock = { write: vi.fn() };
  const ipcMainMock = { handle: vi.fn(), removeHandler: vi.fn() };
  return { clipboardMock, ipcMainMock };
});

vi.mock('electron', () => ({
  clipboard: clipboardMock,
  ipcMain: ipcMainMock,
}));

import { installClipboardBridge } from '../clipboard';

type Handler = (
  event: unknown,
  payload: unknown,
) => { ok: true } | { ok: false; error: string };

function registeredHandler(): Handler {
  const call = ipcMainMock.handle.mock.calls.find(
    ([channel]) => channel === 'gb:clipboard:write-rich',
  );
  if (!call) throw new Error('gb:clipboard:write-rich was not registered');
  return call[1] as Handler;
}

describe('clipboard bridge', () => {
  beforeEach(() => {
    clipboardMock.write.mockClear();
    ipcMainMock.handle.mockClear();
    ipcMainMock.removeHandler.mockClear();
  });

  it('registers the gb:clipboard:write-rich handler', () => {
    installClipboardBridge();
    expect(ipcMainMock.handle).toHaveBeenCalledWith(
      'gb:clipboard:write-rich',
      expect.any(Function),
    );
  });

  it('writes both flavours to the system clipboard', () => {
    installClipboardBridge();
    const result = registeredHandler()(null, { html: '<h1>x</h1>', text: '# x' });
    expect(clipboardMock.write).toHaveBeenCalledWith({ html: '<h1>x</h1>', text: '# x' });
    expect(result).toEqual({ ok: true });
  });

  it('rejects malformed payloads without touching the clipboard', () => {
    installClipboardBridge();
    const result = registeredHandler()(null, { html: 42 });
    expect(clipboardMock.write).not.toHaveBeenCalled();
    expect(result.ok).toBe(false);
  });

  it('removes a previous handler before re-registering', () => {
    installClipboardBridge();
    installClipboardBridge();
    expect(ipcMainMock.removeHandler).toHaveBeenCalledWith('gb:clipboard:write-rich');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/main/__tests__/clipboard.test.ts`
Expected: FAIL — `Cannot find module '../clipboard'`.

- [ ] **Step 3: Implement the main-process module**

Create `desktop/src/main/clipboard.ts`:

```typescript
import { clipboard, ipcMain } from 'electron';

export interface RichClipboardPayload {
  /** Rich flavour — what Slack/Confluence/Teams paste. */
  html: string;
  /** Plain flavour — the markdown equivalent, for terminals/editors. */
  text: string;
}

function isRichClipboardPayload(value: unknown): value is RichClipboardPayload {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as { html?: unknown }).html === 'string' &&
    typeof (value as { text?: unknown }).text === 'string'
  );
}

export function installClipboardBridge(): void {
  // Re-install safety: a second ipcMain.handle for the same channel throws.
  ipcMain.removeHandler('gb:clipboard:write-rich');
  ipcMain.handle('gb:clipboard:write-rich', (_e, payload: unknown) => {
    if (!isRichClipboardPayload(payload)) {
      return {
        ok: false as const,
        error: 'write-rich: expected { html: string, text: string }',
      };
    }
    try {
      clipboard.write({ html: payload.html, text: payload.text });
      return { ok: true as const };
    } catch (err) {
      return {
        ok: false as const,
        error: err instanceof Error ? err.message : String(err),
      };
    }
  });
}
```

- [ ] **Step 4: Wire it into the main process**

Edit `desktop/src/main/index.ts`. Add the import after the jot-overlay import:

Replace:

```typescript
import { installJotOverlay } from './jot-overlay';
```

with:

```typescript
import { installJotOverlay } from './jot-overlay';
import { installClipboardBridge } from './clipboard';
```

Then register it alongside the other module-level handlers. Replace:

```typescript
ipcMain.handle('gb:dialogs:pickVaultFolder', () => pickVaultFolder());
```

with:

```typescript
ipcMain.handle('gb:dialogs:pickVaultFolder', () => pickVaultFolder());

installClipboardBridge();
```

- [ ] **Step 5: Expose the preload bridge + shared type**

Edit `desktop/src/preload/index.ts` — inside the `bridge` object, add a `clipboard` block. Replace:

```typescript
  tray: {
    setFailing: (names: string[]) => ipcRenderer.invoke('gb:tray:setFailing', names),
  },
```

with:

```typescript
  tray: {
    setFailing: (names: string[]) => ipcRenderer.invoke('gb:tray:setFailing', names),
  },
  clipboard: {
    writeRich: (payload: { html: string; text: string }) =>
      ipcRenderer.invoke('gb:clipboard:write-rich', payload),
  },
```

Edit `desktop/src/shared/types.ts` — inside `GbBridge`, add after the `tray` field. Replace:

```typescript
  tray: {
    setFailing(names: string[]): Promise<{ ok: true } | { ok: false; error: string }>;
  };
```

with:

```typescript
  tray: {
    setFailing(names: string[]): Promise<{ ok: true } | { ok: false; error: string }>;
  };
  clipboard: {
    writeRich(payload: {
      html: string;
      text: string;
    }): Promise<{ ok: true } | { ok: false; error: string }>;
  };
```

Edit `desktop/src/renderer/test/setup.ts` — the `stubBridge` constructs a full `GbBridge` and will no longer typecheck without the new field. Replace:

```typescript
  tray: { setFailing: async () => ({ ok: true }) },
```

with:

```typescript
  tray: { setFailing: async () => ({ ok: true }) },
  clipboard: { writeRich: async () => ({ ok: true }) },
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/main/__tests__/clipboard.test.ts`
Expected: PASS — 4 tests green.

Also run: `cd desktop && npm run typecheck`
Expected: no type errors (proves preload/shared/setup are consistent).

- [ ] **Step 7: Commit**

```bash
git add desktop/src/main/clipboard.ts desktop/src/main/__tests__/clipboard.test.ts \
        desktop/src/main/index.ts desktop/src/preload/index.ts \
        desktop/src/shared/types.ts desktop/src/renderer/test/setup.ts
git commit -m "feat(desktop): gb:clipboard:write-rich IPC — html + markdown clipboard flavours"
```

---

## Task 6: Copy-formatted UI in the editor (button + ⌘⇧C, selection-aware, toast)

**Files:**
- Modify: `desktop/src/renderer/components/RichMarkdownEditor.tsx`
- Modify: `desktop/src/renderer/__tests__/RichMarkdownEditor.test.tsx` (extend)

- [ ] **Step 1: Write the failing tests**

Append this describe block to `desktop/src/renderer/__tests__/RichMarkdownEditor.test.tsx` (inside the file, after the existing `describe('RichMarkdownEditor', …)` block), and add `useToasts` to the imports:

Add to the imports at the top of the file:

```typescript
import { useToasts } from '../stores/toast';
import { waitFor } from '@testing-library/react';
```

(Adjust the existing `@testing-library/react` import line to include `waitFor`: `import { render, screen, act, fireEvent, waitFor } from '@testing-library/react';` and drop the separate line.)

Append:

```typescript
describe('RichMarkdownEditor copy-formatted', () => {
  beforeEach(() => {
    useToasts.setState({ toasts: [] });
  });

  it('copies the whole note when there is no selection', async () => {
    const writeRich = vi.fn().mockResolvedValue({ ok: true });
    window.gb = { ...window.gb, clipboard: { writeRich } };
    render(
      <RichMarkdownEditor markdown={'# title\n\nsome **bold** text'} onSave={() => {}} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /copy formatted/ }));
    await waitFor(() => expect(writeRich).toHaveBeenCalledTimes(1));
    const payload = writeRich.mock.calls[0]![0] as { html: string; text: string };
    expect(payload.html).toContain('<h1>title</h1>');
    expect(payload.html).toContain('<strong>bold</strong>');
    expect(payload.text).toBe('# title\n\nsome **bold** text');
  });

  it('copies only the selection when one exists', async () => {
    const writeRich = vi.fn().mockResolvedValue({ ok: true });
    window.gb = { ...window.gb, clipboard: { writeRich } };
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown={'# title\n\nsecond paragraph'}
        onSave={() => {}}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    act(() => {
      // Select the full second paragraph. Doc layout: heading node occupies
      // positions [0, headingNodeSize); the paragraph's inline content starts
      // one position inside the paragraph node.
      const doc = editor!.state.doc;
      const para = doc.child(1);
      const start = doc.firstChild!.nodeSize + 1;
      editor!.commands.setTextSelection({ from: start, to: start + para.content.size });
    });
    fireEvent.click(screen.getByRole('button', { name: /copy formatted/ }));
    await waitFor(() => expect(writeRich).toHaveBeenCalledTimes(1));
    const payload = writeRich.mock.calls[0]![0] as { html: string; text: string };
    expect(payload.html).toContain('second paragraph');
    expect(payload.html).not.toContain('title');
    expect(payload.text.trim()).toBe('second paragraph');
  });

  it('copies via meta+shift+C inside the editor', async () => {
    const writeRich = vi.fn().mockResolvedValue({ ok: true });
    window.gb = { ...window.gb, clipboard: { writeRich } };
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown="shortcut me"
        onSave={() => {}}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    fireEvent.keyDown(editor!.view.dom, { key: 'c', metaKey: true, shiftKey: true });
    await waitFor(() => expect(writeRich).toHaveBeenCalledTimes(1));
    expect((writeRich.mock.calls[0]![0] as { text: string }).text).toBe('shortcut me');
  });

  it('shows a success toast after copying', async () => {
    const writeRich = vi.fn().mockResolvedValue({ ok: true });
    window.gb = { ...window.gb, clipboard: { writeRich } };
    render(<RichMarkdownEditor markdown="x" onSave={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: /copy formatted/ }));
    await waitFor(() =>
      expect(
        useToasts.getState().toasts.some((t) => t.message.includes('copied')),
      ).toBe(true),
    );
  });

  it('shows an error toast when the clipboard write fails', async () => {
    const writeRich = vi.fn().mockResolvedValue({ ok: false, error: 'nope' });
    window.gb = { ...window.gb, clipboard: { writeRich } };
    render(<RichMarkdownEditor markdown="x" onSave={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: /copy formatted/ }));
    await waitFor(() =>
      expect(
        useToasts
          .getState()
          .toasts.some((t) => t.kind === 'error' && t.message.includes('copy failed')),
      ).toBe(true),
    );
  });

  it('hides the copy button in source mode', () => {
    render(<RichMarkdownEditor markdown="x" onSave={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'src' }));
    expect(screen.queryByRole('button', { name: /copy formatted/ })).toBeNull();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/RichMarkdownEditor.test.tsx`
Expected: FAIL — the 6 new tests fail (`Unable to find an accessible element with the role "button" and name /copy formatted/`); the 7 Task-4 tests still pass.

- [ ] **Step 3: Add copy-formatted to the component**

Replace the full contents of `desktop/src/renderer/components/RichMarkdownEditor.tsx` with the final version (Task 4 version + copy plumbing — the diffs are: `clipboardPayload`/`Btn`/`Lucide` imports, `handleCopyRef`, `editorProps.handleKeyDown`, `handleCopy`, the copy button in the footer):

```typescript
import { useEffect, useRef, useState } from 'react';
import { Editor } from '@tiptap/core';
import { EditorContent, useEditor } from '@tiptap/react';
import { buildEditorExtensions } from '../lib/editor/extensions';
import { clipboardPayload, getMarkdown } from '../lib/editor/markdown';
import { toast } from '../stores/toast';
import { Btn } from './Btn';
import { JotEditor } from './JotEditor';
import { Lucide } from './Lucide';

interface Props {
  markdown: string;
  onSave: (markdown: string) => void;
  readOnly?: boolean;
  /** Autosave debounce in ms. Defaults to 1000. */
  debounceMs?: number;
  /** Called once when the TipTap Editor instance is created; useful for tests. */
  onEditorReady?: (editor: Editor) => void;
}

type Mode = 'rich' | 'source';

/** Pre-flight parse probe so markdown the rich editor cannot represent never
 * blocks opening a note (spec: automatic fallback to source mode + toast).
 * Costs one throwaway parse per mount — notes are small, acceptable. */
function parsesAsRich(markdown: string): boolean {
  try {
    const probe = new Editor({ extensions: buildEditorExtensions(), content: markdown });
    probe.destroy();
    return true;
  } catch {
    return false;
  }
}

export function RichMarkdownEditor({
  markdown,
  onSave,
  readOnly = false,
  debounceMs = 1000,
  onEditorReady,
}: Props) {
  // Evaluated once per mount; parents remount per note via key={...}.
  const [parseFailed] = useState(() => !parsesAsRich(markdown));
  const [mode, setMode] = useState<Mode>(parseFailed ? 'source' : 'rich');

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSaved = useRef(markdown);
  // Latest content from either mode — handed over when toggling so no
  // keystrokes are lost.
  const current = useRef(markdown);
  // editorProps.handleKeyDown is captured once at editor creation — route the
  // shortcut through a ref so it always sees the latest closure.
  const handleCopyRef = useRef<() => void>(() => {});

  useEffect(() => {
    if (parseFailed) {
      toast.error('note could not be opened in rich mode — falling back to source');
    }
    // mount-only: parseFailed is fixed for the lifetime of the component
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function scheduleSave(next: string) {
    current.current = next;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      if (next !== lastSaved.current) {
        // Deliberate trade-off (same as JotEditor): lastSaved advances even
        // if the caller's save fails — no retry for debounced autosave.
        lastSaved.current = next;
        onSave(next);
      }
    }, debounceMs);
  }

  const editor = useEditor({
    extensions: buildEditorExtensions(),
    content: parseFailed ? '' : markdown,
    editable: !readOnly,
    editorProps: {
      handleKeyDown: (_view, event) => {
        if (
          (event.metaKey || event.ctrlKey) &&
          event.shiftKey &&
          event.key.toLowerCase() === 'c'
        ) {
          event.preventDefault();
          handleCopyRef.current();
          return true;
        }
        return false;
      },
    },
    onCreate: ({ editor: created }) => {
      onEditorReady?.(created);
    },
    onUpdate: ({ editor: updated }) => {
      scheduleSave(getMarkdown(updated));
    },
  });

  async function handleCopy() {
    if (!editor || editor.isDestroyed || mode !== 'rich') return;
    const payload = clipboardPayload(editor);
    const result = await window.gb.clipboard.writeRich({
      html: payload.html,
      text: payload.markdown,
    });
    if (result.ok) {
      toast.success('copied — paste anywhere');
    } else {
      toast.error(`copy failed: ${result.error}`);
    }
  }

  useEffect(() => {
    handleCopyRef.current = () => void handleCopy();
  });

  // Cross-write guard (mirrors JotEditor): if the markdown prop switches
  // while a save is pending, the stale timer would fire with the previous
  // note's content — cancel it and resync the document.
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    lastSaved.current = markdown;
    current.current = markdown;
    if (editor && !editor.isDestroyed && getMarkdown(editor) !== markdown) {
      try {
        // tiptap-markdown overrides setContent to parse markdown strings;
        // emitUpdate=false so the resync never schedules a save.
        editor.commands.setContent(markdown, false);
      } catch {
        setMode('source');
      }
    }
    // `editor` deliberately omitted: this effect must run on body switches,
    // not on editor (re)creation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [markdown]);

  // Unmount cleanup — no save may fire after the component is gone.
  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  function switchMode(next: Mode) {
    if (next === mode) return;
    if (next === 'source') {
      if (editor && !editor.isDestroyed) current.current = getMarkdown(editor);
      setMode('source');
      return;
    }
    if (!editor || editor.isDestroyed) return;
    try {
      editor.commands.setContent(current.current, false);
      setMode('rich');
    } catch {
      toast.error('could not parse markdown — staying in source mode');
    }
  }

  return (
    <div className="flex h-full flex-col" data-testid="rich-markdown-editor">
      <div className="flex-1 overflow-auto">
        {mode === 'rich' ? (
          <EditorContent
            editor={editor}
            className="gb-prose h-full px-4 py-3 text-14 leading-[1.65] text-ink-0 [&_.ProseMirror]:min-h-full [&_.ProseMirror]:outline-none"
          />
        ) : (
          <JotEditor
            body={current.current}
            debounceMs={debounceMs}
            onSave={(next) => {
              current.current = next;
              lastSaved.current = next;
              onSave(next);
            }}
          />
        )}
      </div>
      <div className="flex flex-shrink-0 items-center gap-2 border-t border-hairline px-3 py-[6px]">
        {mode === 'rich' && (
          <Btn
            variant="ghost"
            size="sm"
            icon={<Lucide name="clipboard-copy" size={12} />}
            onClick={() => void handleCopy()}
          >
            copy formatted
          </Btn>
        )}
        <div className="ml-auto flex items-center gap-1 font-mono text-10 text-ink-3">
          <button
            type="button"
            onClick={() => switchMode('rich')}
            className={
              mode === 'rich'
                ? 'rounded-sm bg-vellum px-2 py-[2px] text-ink-0'
                : 'rounded-sm px-2 py-[2px] hover:text-ink-1'
            }
          >
            rich
          </button>
          <button
            type="button"
            onClick={() => switchMode('source')}
            className={
              mode === 'source'
                ? 'rounded-sm bg-vellum px-2 py-[2px] text-ink-0'
                : 'rounded-sm px-2 py-[2px] hover:text-ink-1'
            }
          >
            src
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/__tests__/RichMarkdownEditor.test.tsx src/renderer/__tests__/markdown-roundtrip.test.ts`
Expected: PASS — 13 component tests (7 + 6) + 12 fixtures green.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/components/RichMarkdownEditor.tsx \
        desktop/src/renderer/__tests__/RichMarkdownEditor.test.tsx
git commit -m "feat(desktop): copy-formatted — selection-aware HTML+markdown clipboard with ⌘⇧C"
```

---

## Task 7: Jots screen swap (JotEditor → RichMarkdownEditor)

**Files:**
- Modify: `desktop/src/renderer/screens/jots.tsx`
- Modify: `desktop/src/renderer/__tests__/jots.test.tsx` (extend)

The screen keeps its `initialBodyRef` freeze + `key={selectedId}` remount pattern unchanged — the editor swap is two surgical edits. Jot saves keep flowing through `useUpdateJot` → `PATCH /v1/notes/{id}` (which re-derives tags). `JotEditor` itself stays — it is now the source-mode escape hatch inside `RichMarkdownEditor`.

- [ ] **Step 1: Extend the screen test**

Append to `desktop/src/renderer/__tests__/jots.test.tsx`, inside the existing `describe('JotsScreen', …)` block:

```typescript
  it('renders the rich editor with the source-mode escape hatch and copy button', async () => {
    apiRequest.mockImplementation(async (_m: string, path: string) => {
      if (path.includes('source=manual')) return { ok: true, status: 200, data: page };
      return { ok: true, status: 200, data: detail };
    });

    render(withQuery(<JotsScreen />));
    await waitFor(() => expect(screen.getByText(/full body here/)).toBeInTheDocument());
    expect(screen.getByTestId('rich-markdown-editor')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'src' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /copy formatted/ })).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/jots.test.tsx`
Expected: FAIL — the new test can't find `rich-markdown-editor` (screen still renders CodeMirror `JotEditor`); the 3 pre-existing tests still pass.

- [ ] **Step 3: Swap the editor**

Edit `desktop/src/renderer/screens/jots.tsx`. Replace the import:

```typescript
import { JotEditor } from '../components/JotEditor';
```

with:

```typescript
import { RichMarkdownEditor } from '../components/RichMarkdownEditor';
```

Replace the editor usage block:

```typescript
                {/* key={selectedId} remounts JotEditor on jot switch, wiping
                    internal debounce timers. The body prop is frozen to the
                    initial fetch so mid-session RQ refetches never reset the
                    editor's internal value. */}
                <JotEditor
                  key={selectedId!}
                  body={editorBody}
                  onSave={handleSaveBody}
                />
```

with:

```typescript
                {/* key={selectedId} remounts the editor on jot switch, wiping
                    internal debounce timers. The markdown prop is frozen to
                    the initial fetch so mid-session RQ refetches never reset
                    the editor's internal value. */}
                <RichMarkdownEditor
                  key={selectedId!}
                  markdown={editorBody}
                  onSave={handleSaveBody}
                />
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/__tests__/jots.test.tsx`
Expected: PASS — 4 tests green (3 pre-existing + 1 new; the pre-existing `/full body here/` assertions hold because TipTap renders the body text as paragraphs).

Also run: `cd desktop && npm run typecheck`
Expected: no type errors.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/screens/jots.tsx desktop/src/renderer/__tests__/jots.test.tsx
git commit -m "feat(desktop): jots screen uses RichMarkdownEditor (CodeMirror stays as src mode)"
```

---

## Task 8: Vault note viewer (`NoteView`) — editable + `useUpdateNoteByPath` + connector-warning chip

**Files:**
- Modify: `desktop/src/shared/api-types.ts`
- Modify: `desktop/src/renderer/lib/api/hooks.ts`
- Modify: `desktop/src/renderer/components/NoteView.tsx`
- Test: `desktop/src/renderer/__tests__/NoteView.test.tsx` (create)

The vault note viewer is the `NoteView` slide-over dialog (mounted once in `App.tsx`, opened from today/daily/meetings/AskPanel via the `useNoteView` store; `screens/vault.tsx` has no viewer — it just opens Finder). It currently renders read-only via `MarkdownBody` with wikilink stripping. The swap replaces `MarkdownBody` with an editable `RichMarkdownEditor`. The wikilink `stripWikilinks`/`transformWikilinks` step must NOT be applied any more: feeding stripped text into an editor that saves would destroy wikilinks on disk. Wikilinks now appear literally in the editor and survive saves via `restoreWikilinks` (Task 3, fixture-gated).

- [ ] **Step 1: Add the shared types**

Edit `desktop/src/shared/api-types.ts` — add directly after the existing `Note` interface:

```typescript
export interface UpdateNoteBodyRequest {
  path: string;
  body: string;
}

export interface UpdateNoteBodyResponse {
  path: string;
  updated: string | null;
}
```

- [ ] **Step 2: Add the hook**

Edit `desktop/src/renderer/lib/api/hooks.ts`. Add `UpdateNoteBodyRequest,` and `UpdateNoteBodyResponse,` to the type-import block (alphabetically after `Suggestion,` / before `UpdateRecorderSettings,`). Then append at the end of the file:

```typescript
export function useUpdateNoteByPath() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: UpdateNoteBodyRequest) =>
      patch<UpdateNoteBodyResponse>('/v1/notes/body', vars),
    onSuccess: () => {
      // Both caches read GET /v1/notes?path= — ['note'] (useNote/NoteView)
      // and ['note-by-path'] (useJot/jots screen).
      qc.invalidateQueries({ queryKey: ['note'] });
      qc.invalidateQueries({ queryKey: ['note-by-path'] });
    },
  });
}
```

- [ ] **Step 3: Write the failing test**

Create `desktop/src/renderer/__tests__/NoteView.test.tsx`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { Editor } from '@tiptap/core';
import { NoteView } from '../components/NoteView';
import { useNoteView } from '../stores/note-view';
import type { Note } from '../../shared/api-types';

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  useNoteView.getState().close();
  window.gb = {
    ...window.gb,
    api: { request: apiRequest },
  };
});

function withQuery(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const syncedNote: Note = {
  path: '20-contexts/sanlam/notes/synced.md',
  title: 'synced note',
  body: '# synced\n\nfrom gmail',
  frontmatter: { source: 'gmail', context: 'sanlam' },
};

const manualNote: Note = {
  path: '20-contexts/sanlam/notes/manual-20260609T090000-x.md',
  title: 'manual note',
  body: 'hand-written',
  frontmatter: { source: 'manual', context: 'sanlam' },
};

describe('NoteView', () => {
  it('renders the note in the rich editor with the synced-note warning chip', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: syncedNote });
    render(withQuery(<NoteView />));
    act(() => useNoteView.getState().open(syncedNote.path));
    await screen.findByText('from gmail');
    expect(screen.getByTestId('rich-markdown-editor')).toBeInTheDocument();
    expect(
      screen.getByText(/synced note — edits may be overwritten by the next sync/),
    ).toBeInTheDocument();
  });

  it('shows no warning chip for manual notes', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: manualNote });
    render(withQuery(<NoteView />));
    act(() => useNoteView.getState().open(manualNote.path));
    await screen.findByText('hand-written');
    expect(screen.queryByText(/edits may be overwritten/)).toBeNull();
  });

  it('saves edits through PATCH /v1/notes/body', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: syncedNote });
    let editor: Editor | undefined;
    render(
      withQuery(
        <NoteView
          onEditorReady={(e) => {
            editor = e;
          }}
        />,
      ),
    );
    act(() => useNoteView.getState().open(syncedNote.path));
    await waitFor(() => expect(editor).toBeDefined());
    act(() => {
      editor!.commands.insertContentAt(editor!.state.doc.content.size, 'edited tail');
    });
    // Real timers in this file — the editor debounce is 1s.
    await waitFor(
      () =>
        expect(apiRequest).toHaveBeenCalledWith('PATCH', '/v1/notes/body', {
          path: syncedNote.path,
          body: expect.stringContaining('edited tail'),
        }),
      { timeout: 3000 },
    );
  });
});
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/NoteView.test.tsx`
Expected: FAIL — `rich-markdown-editor` test id absent, no chip, no `onEditorReady` prop (TS error surfaces first via the test transform).

- [ ] **Step 5: Rewrite NoteView**

Replace the full contents of `desktop/src/renderer/components/NoteView.tsx`:

```typescript
import { useEffect, useRef } from 'react';
import type { Editor } from '@tiptap/core';

import { useNote, useUpdateNoteByPath } from '../lib/api/hooks';
import { useNoteView } from '../stores/note-view';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import { Lucide } from './Lucide';
import { Btn } from './Btn';
import { Pill } from './Pill';
import { RichMarkdownEditor } from './RichMarkdownEditor';
import { SkeletonRows } from './SkeletonRows';
import { PanelError } from './PanelError';

interface Props {
  /** Test hook: receives the TipTap Editor instance once created. */
  onEditorReady?: (editor: Editor) => void;
}

export function NoteView({ onEditorReady }: Props = {}) {
  const path = useNoteView((s) => s.path);
  const close = useNoteView((s) => s.close);
  const note = useNote(path);
  const vaultPath = useSettings((s) => s.vaultPath);
  const updateNote = useUpdateNoteByPath();

  useEffect(() => {
    if (path === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [path, close]);

  // Freeze the FIRST fetched body per path (same pattern as JotsScreen):
  // useUpdateNoteByPath invalidates ['note'] after every autosave, and a
  // refetched body flowing back into the editor as a prop change would reset
  // it mid-typing. key={path} below remounts the editor on note switch.
  const initialBodyRef = useRef<{ path: string; body: string } | null>(null);
  if (
    note.data &&
    path &&
    (initialBodyRef.current === null || initialBodyRef.current.path !== path)
  ) {
    initialBodyRef.current = { path, body: note.data.body };
  }
  if (path === null && initialBodyRef.current !== null) {
    initialBodyRef.current = null;
  }
  const editorBody =
    initialBodyRef.current?.path === path ? initialBodyRef.current.body : undefined;

  if (path === null) return null;

  // Connector-managed warning (spec): frontmatter `source` present and not
  // "manual" → best-effort edits, may be overwritten by the next sync.
  const source = note.data?.frontmatter?.source;
  const isSynced = typeof source === 'string' && source !== 'manual';

  const openInEditor = async () => {
    const target = `${vaultPath}/${path}`;
    const result = await window.gb.shell.openPath(target);
    if (!result.ok) toast.error(result.error);
  };

  const handleSaveBody = (next: string) => {
    updateNote.mutate(
      { path, body: next },
      { onError: (err) => toast.error(`save failed: ${err.message}`) },
    );
  };

  return (
    <div
      role="dialog"
      aria-label="note viewer"
      className="fixed inset-0 z-40 flex justify-end bg-[rgba(14,15,18,0.55)] backdrop-blur-sm"
      onClick={close}
    >
      <div
        className="flex h-full w-[820px] max-w-[92vw] flex-col border-l border-hairline bg-paper shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center gap-3 border-b border-hairline px-6 py-4">
          <Lucide name="file-text" size={14} color="var(--ink-2)" />
          <div className="min-w-0 flex-1 leading-[1.2]">
            <div className="truncate text-13 font-medium text-ink-0">
              {note.data?.title ?? path.split('/').pop()}
            </div>
            <div className="truncate font-mono text-10 text-ink-3">{path}</div>
          </div>
          {isSynced && (
            <Pill tone="oxblood">
              synced note — edits may be overwritten by the next sync
            </Pill>
          )}
          <Btn
            variant="ghost"
            size="sm"
            icon={<Lucide name="external-link" size={13} />}
            onClick={openInEditor}
          >
            open in editor
          </Btn>
          <Btn
            variant="ghost"
            size="sm"
            icon={<Lucide name="x" size={14} />}
            onClick={close}
            ariaLabel="close"
          />
        </header>

        <div className="flex flex-1 flex-col overflow-hidden">
          {note.isLoading && (
            <div className="p-6">
              <SkeletonRows count={6} />
            </div>
          )}
          {note.isError && (
            <div className="p-6">
              <PanelError
                message={
                  note.error instanceof Error ? note.error.message : 'failed to load note'
                }
                onRetry={() => note.refetch()}
              />
            </div>
          )}
          {editorBody !== undefined && (
            <RichMarkdownEditor
              key={path}
              markdown={editorBody}
              onSave={handleSaveBody}
              onEditorReady={onEditorReady}
            />
          )}
        </div>
      </div>
    </div>
  );
}
```

Deliberately removed (documented in Self-Review Notes): `stripWikilinks` (would corrupt files on save now that the body is editable), `MarkdownBody` (and its `gb-note:` wikilink click navigation), and the `FrontmatterStrip` metadata row (the chip + header path line carry the essential context; full frontmatter is still on disk).

- [ ] **Step 6: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/__tests__/NoteView.test.tsx`
Expected: PASS — 3 tests green (the save test takes ~1s wall time: real-timer debounce).

Also run: `cd desktop && npm run typecheck`
Expected: no type errors.

- [ ] **Step 7: Commit**

```bash
git add desktop/src/shared/api-types.ts desktop/src/renderer/lib/api/hooks.ts \
        desktop/src/renderer/components/NoteView.tsx \
        desktop/src/renderer/__tests__/NoteView.test.tsx
git commit -m "feat(desktop): editable vault note viewer — PATCH by path + synced-note warning chip"
```

---

## Task 9: Full regression gate

No new code — both stacks must be green before manual E2E.

- [ ] **Step 1: Backend suite**

Run: `/Users/jannik/development/nikrich/ghost-brain/.venv/bin/python -m pytest ghostbrain/api/tests/ -q`
Expected: 104 passed, 0 failed.

- [ ] **Step 2: Desktop suite**

Run: `cd desktop && npx vitest run`
Expected: all files green, 0 failures — including the pre-existing `App`, `JotEditor` (5), `JotTree` (3), `jots` (now 4), `MeetingPrep`, `UpcomingMeetings`, `api-forwarder`, `jot-overlay` (3), `meeting-notifier`, `settings` suites plus the new `markdown-roundtrip` (12), `RichMarkdownEditor` (13), `clipboard` (4), `NoteView` (3).

- [ ] **Step 3: Typecheck + lint**

Run: `cd desktop && npm run typecheck && npm run lint`
Expected: both exit 0.

- [ ] **Step 4: Commit (only if anything needed fixing)**

If steps 1–3 required fixes, commit them:

```bash
git add -A
git commit -m "fix(desktop): regression fixes from full-suite gate"
```

---

## Task 10: End-to-end manual verification

No code — one explicit E2E pass before calling the feature done.

- [ ] **Step 1: Boot the app**

```bash
cd desktop && npm run dev
```

- [ ] **Step 2: WYSIWYG editing on the jots screen**

Open "jots" in the sidebar, select a jot (or press ⌥-J, type `rich editor e2e check`, ⌘-Enter, wait ~5s for it to appear). In the editor type:

```
# heading test
```

then on new lines: `**bold**` followed by a space, `- [ ] task item`, and a fenced block via triple-backtick. Expected: each shorthand renders live (real heading, bold text, checkbox, code block) — no raw markdown left visible.

- [ ] **Step 3: Verify the file on disk stays plain markdown**

Wait ≥1s after the last keystroke, then:

```bash
grep -A4 "heading test" ~/ghostbrain/vault/20-contexts/*/notes/manual-*.md ~/ghostbrain/vault/00-inbox/raw/manual/manual-*.md 2>/dev/null
```

Expected: `# heading test`, `**bold**`, `- [ ] task item` as plain markdown in exactly one file.

- [ ] **Step 4: Copy formatted**

Select the heading + bold line, press ⌘⇧C (or click "copy formatted"). Expected: toast "copied — paste anywhere". Paste into Slack or TextEdit → rich text (real heading/bold). Paste into a terminal → markdown source. Then click "copy formatted" with no selection and paste → the whole note.

- [ ] **Step 5: Source toggle**

Click `src` in the editor footer → CodeMirror shows raw markdown. Edit a line, click `rich` → the edit appears rendered. Confirm the file on disk picked up the source-mode edit after ~1s.

- [ ] **Step 6: Editable vault note + connector chip**

Open "today" (or "daily"), click any synced note (e.g. a gmail/calendar capture) to open the NoteView slide-over. Expected: the chip "synced note — edits may be overwritten by the next sync" in the header. Append a line in the editor, wait ~1s, then verify on disk:

```bash
head -20 ~/ghostbrain/vault/<path-shown-in-the-noteview-header>
```

Expected: appended line present in the body, all frontmatter keys intact, `updated` bumped. Open a manual note the same way → no chip.

- [ ] **Step 7: Record the E2E pass**

Append to `docs/superpowers/specs/2026-06-09-rich-markdown-editor-design.md` under a new "## Implementation status" heading:

```
- 2026-06-09: E2E pass — WYSIWYG jot edit → plain-md on disk → copy-formatted rich paste → vault note edit with frontmatter preserved → source toggle.
```

```bash
git add docs/superpowers/specs/2026-06-09-rich-markdown-editor-design.md
git commit -m "docs(spec): record rich markdown editor E2E pass"
```

---

## Self-Review Notes

After writing this plan, I checked it against the spec and the working tree:

**Coverage:** Engine choice + round-trip risk → Task 3 (fixtures are the gate; spec open question 1 — task-checkbox round-trip — is answered YES, but only with the `TaskListTight` extension, which Task 3 adds and explains). Component §1 → Task 4 (spec props, JotEditor autosave semantics verbatim incl. cross-write guard and optimistic `lastSaved`, source toggle, parse-failure fallback with toast). Copy formatted §2 → Tasks 5 + 6 (IPC channel name, `clipboard.write({ html, text })`, selection-aware, ⌘⇧C, toasts incl. clipboard-failure error toast). Surfaces §3 → Tasks 7 + 8 (jots screen keeps `PATCH /v1/notes/{id}`; vault viewer editable via by-path endpoint; connector chip with the spec's exact wording; ⌥-J overlay untouched). Backend → Tasks 1 + 2 (404/400/422 statuses, frontmatter preservation, `updated` bump only when present, no tag re-derivation, connector-file edit allowed test). Testing § → fixture gate, clipboard handler tests (both flavours, selection vs whole-doc), backend PATCH-by-path tests, screen tests updated. Deferred items (dialects, direct-send, image paste, overlay formatting) have no tasks — correct per spec.

**Where the codebase contradicted assumptions (verified, plan reflects reality):**
- The "vault note viewer" is the `NoteView` slide-over component, not `screens/vault.tsx` (which only opens Finder). Task 8 targets `NoteView`.
- Backend tests use the conftest `tmp_vault`/`client`/`auth_headers` fixtures with `create_app(token=…)` and `headers=auth_headers` — NOT the ad-hoc `TestClient(app)` style the predecessor plan sketched. All new tests follow the conftest style.
- Route shadowing: `/body` vs `/{jot_id}` was verified empirically (jot-first → 422 `string_too_short`; body-first → 200). The order is pinned by a dedicated regression test.
- `tiptap-markdown@latest` (0.9.0) requires TipTap v3 — versions are pinned to 2.27.2/0.8.10 with an explicit do-not-upgrade note.
- `frontmatter.dumps` on empty metadata emits `---\n{}\n---` — `save_note_body` special-cases frontmatter-less files, with a test.

**Intentional deviations / scope decisions:**
- Wikilink handling: prosemirror-markdown escapes `[[…]]`; without a fix, the first vault-note save would corrupt every wikilink. `restoreWikilinks` (verified byte-stable for plain/underscore/alias forms) is added and fixture-gated. Consequence: `NoteView` no longer strips/linkifies wikilinks (`MarkdownBody`'s `gb-note:` click-through is gone in the editor view) — clickable wikilinks inside the rich editor would need a custom TipTap node and are left out; `MarkdownBody` itself is untouched and still serves the capture panel.
- `FrontmatterStrip` removed from `NoteView` — replaced functionally by the synced chip; noted in Task 8.
- Copy-formatted is hidden in source mode (raw markdown is directly copyable there); spec only requires it for the rich editor.
- Spec open question 2 (bundle size / lazy-loading the editor chunk) is not implemented — measure at `npm run pack` time; if the renderer chunk grows objectionably, wrap `RichMarkdownEditor` in `React.lazy` as a follow-up. No task because there is no evidence yet that it is needed.
- Known canonicalisations accepted and documented in the fixture test: soft line breaks collapse to spaces (multi-line blockquotes need `>` paragraph separators), loose/tight list shape is preserved as-is.

**Type consistency:** `UpdateNoteBodyRequest { path, body }` (TS, Task 8) ⇄ `UpdateNoteBodyRequest(BaseModel)` (pydantic, Task 2); `UpdateNoteBodyResponse { path, updated: string | null }` ⇄ `save_note_body` return `{"path": str, "updated": str | None}` (Task 1). `RichMarkdownEditor` props `{ markdown, onSave, readOnly?, debounceMs?, onEditorReady? }` are used identically in Tasks 4/6/7/8. `RichClipboardPayload { html, text }` (main, Task 5) matches the preload bridge, `GbBridge.clipboard.writeRich`, the setup stub, and the renderer call site (`text: payload.markdown`).

**No placeholders:** every step has complete runnable code or an exact command with its expected outcome; the Task 6 component edit repeats the full final file rather than describing a diff.
