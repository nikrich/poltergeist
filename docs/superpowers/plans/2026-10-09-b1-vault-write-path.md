# B1 Vault Write Path + Etags Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every API-side vault write goes through one module, `ghostbrain/vault_write`. It keeps the original frontmatter bytes on a body save, rewrites only the touched line on a field edit, writes atomically under a per-path lock and refuses stale writes by content-hash etag. The editor sends `If-Match` and shows a conflict banner with view diff / keep theirs / keep mine.

**Architecture:** `ghostbrain/vault_write/` is a new top-level package with no dependency on `ghostbrain/api`. `text.py` does the text work: parse, body splice and line-level field edits, with no I/O. `writer.py` does the I/O: path guard, lock, etag check, temp file plus `os.replace`, and exposes `write()`. The API repos (`note.py`, `notes_manual.py`, `generated_docs.py`, `chat_attachments.py`) call `vault_write.write()` and stop writing files themselves. The routes turn the `If-Match` header into `base_etag`, and `WriteConflict` becomes a global 409. In the desktop app, the IPC bridge carries an optional `{ ifMatch }` and the forwarder turns it into an `If-Match` header. A `useGuardedSave` hook and a `GuardedNoteEditor` component wrap `RichMarkdownEditor` in the Jots screen and in `NoteView`.

**Tech Stack:** Python 3.11+ (CI 3.11), FastAPI, PyYAML (`yaml.safe_dump` / `safe_load`), python-frontmatter (only where the existing create path already uses it), stdlib `threading` / `tempfile` / `hashlib`. Electron main (`node:http` forwarder), React 18, TanStack Query 5, TipTap, Vitest + Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-09-ai-changes-revert-design.md`. This plan covers slice **B1** only. It contains no change log, no Changes screen, no risk policy and no history snapshots; those are B2–B4 and A3.

## Global Constraints

- Every create, modify, move or delete of a vault **note** (`.md`, or generated `.html`) by an API route or MCP tool goes through `ghostbrain/vault_write`. Worker and connector writers are out of scope (B4 / non-goal).
- Etag is `sha256(file bytes)[:16]` as lowercase hex, computed over the raw on-disk bytes, BOM included.
- Body save: "Keep the original frontmatter block's exact text (from the opening `---` through the closing `---\n`) and replace only what follows."
- Field edit: "for each key that exists as a single-line scalar (`key: value`), rewrite that one line. For a missing key, insert a line before the closing `---`. Only when the key is a multi-line structure (a list or map) is that key's block re-serialised; the rest of the frontmatter stays byte-identical."
- "`updated` is bumped only when the key already exists, as today."
- Write atomically: "temp file in the same directory, then `os.replace`", under a per-path `threading.Lock`. "One sidecar process owns all writes."
- Etag mismatch → **409**. The editor "stops autosaving and shows a banner: 'This note changed outside the editor.'" The options are **View changes / Keep theirs / Keep mine**. "The user's unsaved text is never discarded silently."
- `actor` is a required argument of `write()`, with values `user | assistant | mcp | plugin:<id> | worker:<job>`. B1 validates it and threads it through but **stores nothing**. B2 records it.
- Don't add a new npm or pip dependency. The diff view uses an in-repo line diff.
- No real people's or employer names in code, tests or copy. Use neutral examples only (`acme`, `work`, `personal`, "Q3 one-pager").
- Python test commands use `python -m pytest ...`. New platform-neutral test files under `tests/` go into the fixed list in `.github/workflows/ci.yml`. Files under `ghostbrain/api/tests/` are already covered by the directory entry.
- Desktop gates: `npm run typecheck` (never `tsc --noEmit`, which is a no-op here), `npx vitest run`, and `npx eslint --max-warnings 0 <files>`.

## Review Focus

1. **A note with a BOM or leading blank lines, opened in the editor and saved.** The body the GET returns must be exactly what the splice replaces, or the frontmatter gets duplicated into the body. Pinned in Task 3 (`test_get_note_bom_body_excludes_frontmatter`) and Task 4 (`test_bom_note_round_trip_does_not_duplicate_frontmatter`).
2. **A jot re-routed, or stamped by Confluence export, while it is open.** Only the frontmatter changes, but the etag changes too. The next autosave must not raise a false conflict banner. Pinned in Task 8 (`auto-resolves a frontmatter-only change`).
3. **Two autosaves in flight at once.** The second save must not 409 against the user's own first write. Pinned in Task 8 (`queues overlapping saves and chains etags`).
4. **The user keeps typing while the banner is up and then picks Keep mine.** The latest text must be saved, not the text at the moment of conflict. Pinned in Task 8 (`keep mine saves the latest text typed during the conflict`).
5. **A body save on a note whose frontmatter is invalid YAML but has an `updated:` line.** The save must still succeed, keep the broken frontmatter bytes untouched and skip the bump. Pinned in Task 2 (`test_body_save_on_invalid_yaml_skips_bump_and_keeps_bytes`).

---

## Interfaces — `ghostbrain.vault_write` public API

A3 (page history), A5 (inline AI) and C1 (templates) call this, and B2/B3 extend it. Everything below is importable from `ghostbrain.vault_write`.

```python
# actor.py
Actor = str                       # validated string, see parse_actor
USER: Actor = "user"
ASSISTANT: Actor = "assistant"
MCP: Actor = "mcp"
def parse_actor(value: str) -> Actor            # ValueError unless user|assistant|mcp|plugin:<id>|worker:<job>
def plugin_actor(plugin_id: str) -> Actor       # "plugin:<id>"
def worker_actor(job: str) -> Actor             # "worker:<job>"

# errors.py
class VaultWriteError(Exception)
class InvalidPath(VaultWriteError, ValueError)  # traversal / absolute / wrong suffix  → HTTP 400
class FileMissing(VaultWriteError)              # modify/delete/move of a missing file → HTTP 404
class MalformedNote(VaultWriteError)            # not UTF-8, or fields edit on invalid YAML → HTTP 422
class WriteConflict(VaultWriteError):           # etag mismatch / create over existing → HTTP 409
    current_etag: str | None
    def __init__(self, current_etag: str | None, message: str = "note changed since you read it — re-read and retry")

# etag.py
def compute_etag(data: bytes) -> str            # sha256(data).hexdigest()[:16]
def normalize_if_match(value: str | None) -> str | None   # '"abc"' / 'W/"abc"' / 'abc' -> 'abc'; None/''/'*' -> None

# text.py (pure, no I/O)
DELETE_FIELD: Any                               # sentinel: fields={"k": DELETE_FIELD} removes key k
@dataclass(frozen=True)
class ParsedNote:
    bom: str; has_frontmatter: bool; fm_head: str; fm_inner: str; fm_close: str; gap: str; body: str; eol: str
    frontmatter_text: str  (property)           # bom + fm_head + fm_inner + fm_close — preserved by a body splice
    def render(self) -> str                     # parse_note(t).render() == t for every t
def parse_note(text: str) -> ParsedNote
def load_metadata(parsed: ParsedNote) -> dict[str, Any]          # MalformedNote on bad YAML / non-mapping
def splice_body(parsed: ParsedNote, body: str, *, ensure_newline: bool) -> ParsedNote
def apply_fields(parsed: ParsedNote, fields: Mapping[str, Any]) -> ParsedNote
def find_key_block(lines: list[str], key: str) -> tuple[int, int] | None
def lines_of(text: str) -> list[str]           # split on "\n" only, keepends

# writer.py
Op = Literal["create", "modify", "delete", "move"]
WRITABLE_SUFFIXES: tuple[str, ...] = (".md", ".html")
@dataclass(frozen=True)
class WriteResult:
    status: Literal["applied", "pending"]   # always "applied" in B1 (B3 adds "pending")
    change_id: str | None                    # always None in B1 (B2 fills it)
    etag: str | None                         # new etag; None after delete
    path: str                                # vault-relative POSIX path (dest for a move)
    updated: str | None                      # value written to `updated`, if any
@dataclass(frozen=True)
class NoteSnapshot:
    path: str; etag: str; parsed: ParsedNote
    body: str (property)                     # parsed.body.strip() — same as python-frontmatter's Post.content
    def metadata(self) -> dict[str, Any]
def resolve_safe(rel_path: str, *, suffixes: tuple[str, ...] = WRITABLE_SUFFIXES) -> Path
def write(
    rel_path: str, *,
    actor: Actor,
    content: str | None = None,              # full replacement (create / plugin upsert)
    body: str | None = None,                 # body-only replacement, frontmatter bytes kept
    fields: Mapping[str, Any] | None = None, # line-level frontmatter edits (DELETE_FIELD removes)
    op: Op = "modify",
    dest: str | None = None,                 # op="move" only
    reason: str = "",                        # B2 shows it on the Changes screen
    base_etag: str | None = None,            # if given and != current etag → WriteConflict
) -> WriteResult
def write_new(rel_path: str, content: str, *, actor: Actor, reason: str = "", max_attempts: int = 100) -> WriteResult
    # op="create" at rel_path, else "<stem>-2<suffix>", "-3", … — never overwrites
def current_etag(rel_path: str, *, suffixes: tuple[str, ...] = WRITABLE_SUFFIXES) -> str | None
def read(rel_path: str, *, suffixes: tuple[str, ...] = WRITABLE_SUFFIXES) -> NoteSnapshot   # FileMissing
```

Rules for `write()` arguments: `content` cannot be combined with `body` or `fields`. `create` needs `content`. `delete` takes nothing else. `move` needs `dest` and takes optional `body` or `fields`. `modify` needs at least one of `content`, `body` or `fields`. Any other combination raises `ValueError`, because it is a programmer error.

HTTP contract (B1):

- `GET /v1/notes?path=` returns `{path, title, body, frontmatter, etag}`.
- `PATCH /v1/notes/body`, `PATCH /v1/notes/{jot_id}` and `PUT /v1/notes` accept `If-Match` and return `etag`.
- A 409 body looks like `{"detail": "note changed since you read it — re-read and retry", "currentEtag": "<16 hex or null>"}`.

## File Structure

### Created

| File | Responsibility |
|---|---|
| `ghostbrain/vault_write/__init__.py` | Public re-exports (Interfaces above) |
| `ghostbrain/vault_write/errors.py` | Exception types |
| `ghostbrain/vault_write/actor.py` | Actor constants + validation |
| `ghostbrain/vault_write/etag.py` | `compute_etag`, `normalize_if_match` |
| `ghostbrain/vault_write/text.py` | Pure frontmatter text ops: parse, splice, field edits |
| `ghostbrain/vault_write/writer.py` | Path guard, locks, atomic write, `write`/`write_new`/`read`/`current_etag` |
| `ghostbrain/api/vault_http.py` | `If-Match` FastAPI dependency + exception → status handlers |
| `tests/test_vault_write_text.py` | Byte-exact text tests (awkward YAML) |
| `tests/test_vault_write_writer.py` | Writer tests (ops, etag, atomic, lock, perms) |
| `ghostbrain/api/tests/test_vault_http.py` | Error-mapping + GET etag tests |
| `ghostbrain/api/tests/test_note_write_path.py` | `note.py` migration golden + If-Match route tests |
| `ghostbrain/api/tests/test_notes_manual_write_path.py` | `notes_manual` migration golden + route tests |
| `ghostbrain/api/tests/test_create_writers_write_path.py` | generated docs + chat attachments migration tests |
| `desktop/src/renderer/lib/line-diff.ts` | Line-level LCS diff (shared later with A3's HistoryDrawer) |
| `desktop/src/renderer/lib/use-guarded-save.ts` | Etag-chained autosave + conflict state machine |
| `desktop/src/renderer/components/ConflictBanner.tsx` | Banner + diff view + the three actions |
| `desktop/src/renderer/components/GuardedNoteEditor.tsx` | `RichMarkdownEditor` + `useGuardedSave` + banner |
| `desktop/src/renderer/__tests__/api-client.test.ts` | `patch()` If-Match + ApiError |
| `desktop/src/renderer/__tests__/line-diff.test.ts` | Diff tests |
| `desktop/src/renderer/__tests__/use-guarded-save.test.tsx` | Hook tests |
| `desktop/src/renderer/__tests__/GuardedNoteEditor.test.tsx` | Banner UI tests |

### Modified

| File | Change |
|---|---|
| `ghostbrain/api/main.py` | `install_vault_write_errors(app)` |
| `ghostbrain/api/models/note.py` | `Note.etag` |
| `ghostbrain/api/repo/note.py` | `_resolve_safe` delegates; `get_note` via `vault_write.read` + etag; `save_note_body` / `save_note_at_path` via `write` |
| `ghostbrain/api/repo/notes_manual.py` | All six writers via `write`; `read_jot` via `vault_write.read`; actor kwargs |
| `ghostbrain/api/routes/notes.py` | `If-Match` on PATCH body / PATCH jot / PUT; actors |
| `ghostbrain/api/repo/generated_docs.py` | `write_new(..., actor=MCP)` |
| `ghostbrain/api/repo/chat_attachments.py` | Note file via `write_new(..., actor=USER)` |
| `ghostbrain/api/tests/test_routes_notes_upsert.py` | Exact-dict assertion gains `etag` |
| `.github/workflows/ci.yml` | Add the two new `tests/test_vault_write_*.py` files |
| `desktop/src/main/api-forwarder.ts` | `requestHeadersFrom()`; `forward(..., extraHeaders)` |
| `desktop/src/main/index.ts` | `gb:api:request` takes a 4th `opts` arg |
| `desktop/src/preload/index.ts` | Pass `opts` through |
| `desktop/src/shared/types.ts` | `api.request(..., opts?: { ifMatch?: string })` |
| `desktop/src/shared/api-types.ts` | `Note.etag?`, `UpdateNoteBodyResponse.etag`, `UpdateJotResponse`, `ExtractPhotoResponse.etag?` |
| `desktop/src/renderer/lib/api/client.ts` | `patch(path, body, { ifMatch })`; throws `ApiError` |
| `desktop/src/renderer/lib/api/hooks.ts` | `useUpdateJot` / `useUpdateNoteByPath` accept `ifMatch` |
| `desktop/src/renderer/components/RichMarkdownEditor.tsx` | Export `RichMarkdownEditorProps` |
| `desktop/src/renderer/screens/jots.tsx` | Render `GuardedNoteEditor`; freeze etag with body; adopt etag after extract-photo |
| `desktop/src/renderer/components/NoteView.tsx` | Render `GuardedNoteEditor` |
| `desktop/src/main/__tests__/api-forwarder.test.ts` | If-Match header tests |
| `desktop/src/renderer/__tests__/NoteView.test.tsx` | If-Match on autosave |

### Writer inventory: migrated in B1 vs left for later

| Writer (today) | B1 | Actor in B1 |
|---|---|---|
| `api/repo/note.py::save_note_body` (`PATCH /v1/notes/body`) | **Migrated**, `write(body=…)`, If-Match | `user` (header attribution is B2) |
| `api/repo/note.py::save_note_at_path` (`PUT /v1/notes`, plugins) | **Migrated**, `write(content=…, op=create\|modify)`, If-Match | `plugin:unattributed` (B2 stamps the real id) |
| `api/repo/notes_manual.py::write_inbox_jot` (`POST /v1/notes`, jot overlay, chat export) | **Migrated**, `write(content=…, op="create")` | `user` |
| `notes_manual.update_jot_body` (`PATCH /v1/notes/{id}`) | **Migrated**, `write(body=…, fields={updated,tags})`, If-Match | `user`; `assistant` from extract-photo |
| `notes_manual.move_jot` (manual route, auto-route, chat export) | **Migrated**, `write(op="move", fields=…)` | `user` manual; `worker:jot-router` LLM auto-route |
| `notes_manual.mark_manual_review` | **Migrated**, `write(fields=…)` | `worker:jot-router` |
| `notes_manual.set_frontmatter_fields` (Confluence export stamp) | **Migrated**, `write(fields=…)` | `user` |
| `notes_manual.delete_jot` (`DELETE /v1/notes/{id}`) | **Migrated**, `write(op="delete")` | `user` |
| `api/repo/generated_docs.py::write_doc` (`POST /v1/docs/write` ← MCP `poltergeist_write_doc`) | **Migrated**, `write_new(...)` | `mcp` |
| `api/repo/chat_attachments.py::save_attachment` (the `.md` note) | **Migrated**, `write_new(...)` | `user` |
| `chat_attachments._image_body` binary asset `write_bytes` | **Deferred.** Binary, content-addressed, not a note | — |
| `desktop/src/main/assets.ts` (jot photo assets in `90-meta/assets`) | **Deferred.** Binary, main process | — |
| `worker/reversal.py`, `profile/apply.py` | **Deferred to B4** (spec slice 4) | — |
| `semantic/refresh.py:298` (`frontmatter.dumps` rewrite of existing notes — reformats!) | **Deferred to B4.** Flagged as the next reformatting offender | — |
| `api/repo/import_atlassian.py` (worker `write_note` + stale-copy `unlink`), `worker/note_generator.py`, `worker/extractor.py`, `worker/digest.py`, `worker/weekly_digest.py`, `recorder/{linker,slides,manual,transcribe}.py`, `metrics/snapshot.py`, `profile/{decay,claude_md}.py`, `bootstrap.py` | **Not migrated.** Connector/worker ingest is a spec non-goal (Decision 1) | — |
| `api/repo/projects.py` (`90-meta/projects.json`), `api/repo/routing.py` + `routing_config.py` (`90-meta/routing.yaml`), `recorder/manual.py` config | **Deferred.** Config, not notes; `90-meta` policy is B3 | — |
| `api/repo/meeting_prep.py`, `chat_store.py`, `settings.py`, `dotenv_store.py`, recorder state | **Not vault notes** (state dir / config) | — |
| Plugin IPC `plugin(id).sidecar.request` | Unchanged; plugins can't send If-Match through the bridge in B1 (B2 threads plugin id) | — |

### Spec decisions made in this plan

These resolve gaps in the spec. The final report lists them too.

1. `base_etag` is **optional** in B1 and checked only when supplied. The spec's "required for actor != worker when op != create" moves to B2, because plugins and MCP don't send etags yet and making it required now would break the Familiar write-back.
2. `If-Match` crosses IPC as a 4th `opts` argument, `{ ifMatch }`. The main process accepts only a 16-hex etag and sets `If-Match: "<etag>"`. The server accepts quoted, `W/`-prefixed or bare values.
3. `content=` adds a trailing newline only for `.md`. `.html` is written verbatim so generated-doc bytes stay identical to today.
4. Splice details:
   - The gap of blank lines between the closing fence and the body is kept. If the old body was empty, one blank line is used (house style).
   - On a CRLF file, the new body's LF becomes CRLF.
   - A closing fence at EOF without a newline gets one EOL.
   - Trailing newlines on the body collapse to one.
5. An opening `---` with no closing fence means **no frontmatter**, matching python-frontmatter. GET and the splice share one parser, so they can't disagree.
6. The auto-bump of `updated` is best-effort and is skipped when the frontmatter YAML is unparseable, so a body save is never blocked by broken YAML.
7. A field edit whose new value equals the parsed old value (same type) is a no-op. A whole write that produces identical bytes doesn't touch the file.
8. YAML values are rendered with PyYAML defaults (`width=80`, block style) and the real key. This matches what the legacy `frontmatter.dumps` writers produced, which is what keeps the golden tests byte-equal.
9. `op="create"` on an existing path raises 409. `write_new` adds `-2`, `-3`, … for generated docs and chat attachments. Before, a same-second same-title write silently overwrote the earlier file.
10. `op="move"` onto an existing destination raises 409. Before, it silently overwrote.
11. Frontmatter-only external changes (re-route, Confluence stamp) are auto-resolved by the client. The client re-reads, sees the body unchanged, and resends once with the fresh etag. Only a body difference shows the banner.
12. In B1, Keep mine overwrites using the fresh etag with **no snapshot**, because the history store is A3. B2/A3 add the snapshot inside `write()` without changing callers.
13. A 409 body carries both `detail` (a string, so the forwarder's existing extraction still works) and `currentEtag`.
14. The MCP 409 message isn't reachable in B1 because MCP only creates via `write_new`. The `WriteConflict` default message already uses the spec wording for B2.

---

### Task 1: `vault_write` text operations (parse, splice, field edits)

**Files:**
- Create: `ghostbrain/vault_write/__init__.py`
- Create: `ghostbrain/vault_write/errors.py`
- Create: `ghostbrain/vault_write/text.py`
- Create: `tests/test_vault_write_text.py`
- Modify: `.github/workflows/ci.yml` (test list)

**Interfaces:**
- Consumes: nothing.
- Produces: `ParsedNote`, `parse_note`, `load_metadata`, `splice_body`, `apply_fields`, `find_key_block`, `lines_of`, `DELETE_FIELD`, plus every error class, with the signatures in the Interfaces block.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vault_write_text.py`:

```python
"""Byte-exact frontmatter text ops for the vault write path (spec B1)."""
from __future__ import annotations

import pytest

from ghostbrain.vault_write import (
    DELETE_FIELD,
    MalformedNote,
    apply_fields,
    find_key_block,
    lines_of,
    load_metadata,
    parse_note,
    splice_body,
)

AWKWARD = (
    "---\n"
    "# leading comment\n"
    'title: "Quoted: title"   # trailing comment\n'
    "zeta: 1\n"
    "alpha: 'it''s'\n"
    "unicode: café ✓ 日本\n"
    "tags:\n"
    "  - one\n"
    "  - two\n"
    "nested:\n"
    "  k: v\n"
    "updated: 2026-01-01T00:00:00+00:00\n"
    "empty:\n"
    "---\n"
    "\n"
    "old body\n"
)
CRLF = "---\r\ntitle: a\r\nzeta: 1\r\n---\r\n\r\nbody line\r\n"
BOM = "﻿---\ntitle: a\n---\n\nbody\n"
NO_TRAILING_NL = "---\ntitle: a\n---\n\nbody without newline"
FENCE_AT_EOF = "---\ntitle: a\n---"
LEADING_BLANKS = "\n\n---\ntitle: a\n---\nbody right after fence\n"
EMPTY_FM = "---\n---\nbody\n"
NO_FM = "just a body\nsecond line\n"
UNTERMINATED = "---\n\nA horizontal rule opened this note.\n"

ALL_SAMPLES = [AWKWARD, CRLF, BOM, NO_TRAILING_NL, FENCE_AT_EOF, LEADING_BLANKS, EMPTY_FM, NO_FM, UNTERMINATED, ""]
WITH_FM = [AWKWARD, CRLF, BOM, NO_TRAILING_NL, LEADING_BLANKS, EMPTY_FM]


def _changed_lines(old: str, new: str) -> list[int]:
    a, b = old.split("\n"), new.split("\n")
    assert len(a) == len(b), "line count changed"
    return [i for i, (x, y) in enumerate(zip(a, b)) if x != y]


@pytest.mark.parametrize("text", ALL_SAMPLES)
def test_parse_render_round_trip_is_identity(text):
    assert parse_note(text).render() == text


def test_parse_splits_awkward_note():
    p = parse_note(AWKWARD)
    assert p.has_frontmatter
    assert p.fm_head == "---\n"
    assert p.fm_inner.startswith("# leading comment\n")
    assert p.fm_close == "---\n"
    assert p.gap == "\n"
    assert p.body == "old body\n"
    assert p.eol == "\n"


def test_parse_keeps_bom_out_of_head_and_body():
    p = parse_note(BOM)
    assert p.bom == "﻿"
    assert p.frontmatter_text.startswith("﻿---\n")
    assert p.body == "body\n"


def test_parse_detects_crlf():
    assert parse_note(CRLF).eol == "\r\n"


def test_unterminated_fence_is_not_frontmatter():
    p = parse_note(UNTERMINATED)
    assert not p.has_frontmatter
    assert p.body == UNTERMINATED


def test_leading_blank_lines_belong_to_the_frontmatter_head():
    p = parse_note(LEADING_BLANKS)
    assert p.has_frontmatter
    assert p.fm_head == "\n\n---\n"
    assert p.gap == ""
    assert p.body == "body right after fence\n"


@pytest.mark.parametrize("text", WITH_FM)
def test_splice_keeps_frontmatter_bytes_identical(text):
    before = parse_note(text)
    after = splice_body(before, "# new\n\nreplaced body", ensure_newline=True)
    assert after.render().startswith(before.frontmatter_text)
    assert after.frontmatter_text == before.frontmatter_text
    assert after.render().endswith("replaced body" + before.eol)


def test_splice_awkward_note_exact_bytes():
    out = splice_body(parse_note(AWKWARD), "new body", ensure_newline=True).render()
    assert out == AWKWARD.replace("old body\n", "new body\n")


def test_splice_converts_body_to_crlf_on_crlf_file():
    out = splice_body(parse_note(CRLF), "x\ny", ensure_newline=True).render()
    assert out == "---\r\ntitle: a\r\nzeta: 1\r\n---\r\n\r\nx\r\ny\r\n"


def test_splice_collapses_trailing_newlines_to_one():
    out = splice_body(parse_note(AWKWARD), "x\n\n\n", ensure_newline=True).render()
    assert out.endswith("\n\nx\n")


def test_splice_without_ensure_newline_is_verbatim():
    out = splice_body(parse_note(NO_FM), "<p>x</p>", ensure_newline=False).render()
    assert out == "<p>x</p>"


def test_splice_fence_at_eof_adds_eol_and_blank_line():
    out = splice_body(parse_note(FENCE_AT_EOF), "x", ensure_newline=True).render()
    assert out == "---\ntitle: a\n---\n\nx\n"


def test_splice_keeps_body_directly_after_fence():
    out = splice_body(parse_note(LEADING_BLANKS), "new", ensure_newline=True).render()
    assert out == "\n\n---\ntitle: a\n---\nnew\n"


def test_splice_no_frontmatter_keeps_bom():
    out = splice_body(parse_note("﻿plain\n"), "rewritten", ensure_newline=True).render()
    assert out == "﻿rewritten\n"


def test_field_edit_touches_exactly_one_line_and_keeps_inline_comment():
    out = apply_fields(parse_note(AWKWARD), {"title": "New: title"}).render()
    changed = _changed_lines(AWKWARD, out)
    assert len(changed) == 1
    assert out.split("\n")[changed[0]] == "title: 'New: title'   # trailing comment"


def test_field_edit_of_timestamp_rewrites_only_that_line():
    out = apply_fields(parse_note(AWKWARD), {"updated": "2026-10-09T10:00:00+00:00"}).render()
    changed = _changed_lines(AWKWARD, out)
    assert len(changed) == 1
    assert out.split("\n")[changed[0]] == "updated: '2026-10-09T10:00:00+00:00'"


def test_field_edit_unicode_value():
    out = apply_fields(parse_note(AWKWARD), {"unicode": "naïve ✓"}).render()
    assert _changed_lines(AWKWARD, out) == [5]
    assert "unicode: naïve ✓\n" in out


def test_field_edit_null_key_gets_a_value():
    out = apply_fields(parse_note(AWKWARD), {"empty": "now set"}).render()
    assert len(_changed_lines(AWKWARD, out)) == 1
    assert "empty: now set\n---\n" in out


def test_multiline_field_reserialises_only_its_block():
    out = apply_fields(parse_note(AWKWARD), {"tags": ["one", "three"]}).render()
    before = AWKWARD.split("tags:\n")[0]
    after_block = "nested:\n  k: v\n"
    assert out.startswith(before)
    assert out[len(before):].startswith("tags:\n- one\n- three\nnested:\n")
    assert out.split("- three\n", 1)[1] == AWKWARD.split("  - two\n", 1)[1]
    assert after_block in out


def test_missing_key_inserted_before_closing_fence():
    out = apply_fields(parse_note(AWKWARD), {"added": 3}).render()
    assert out == AWKWARD.replace("empty:\n---\n", "empty:\nadded: 3\n---\n")


def test_nested_key_is_not_a_top_level_match():
    out = apply_fields(parse_note(AWKWARD), {"k": 1}).render()
    assert "nested:\n  k: v\n" in out
    assert "empty:\nk: 1\n---\n" in out


def test_unchanged_value_is_byte_identical():
    p = parse_note(AWKWARD)
    assert apply_fields(p, {"zeta": 1, "tags": ["one", "two"]}).render() == AWKWARD


def test_delete_field_removes_block_and_missing_delete_is_noop():
    out = apply_fields(parse_note(AWKWARD), {"tags": DELETE_FIELD, "nope": DELETE_FIELD}).render()
    assert out == AWKWARD.replace("tags:\n  - one\n  - two\n", "")


def test_quoted_key_is_matched():
    text = '---\n"weird key": 1\nother: 2\n---\n\nb\n'
    out = apply_fields(parse_note(text), {"weird key": 5}).render()
    assert out == '---\n"weird key": 5\nother: 2\n---\n\nb\n'


def test_fields_on_crlf_file_use_crlf():
    out = apply_fields(parse_note(CRLF), {"title": "b", "new": 1}).render()
    assert out == "---\r\ntitle: b\r\nzeta: 1\r\nnew: 1\r\n---\r\n\r\nbody line\r\n"


def test_fields_on_file_without_frontmatter_creates_block():
    out = apply_fields(parse_note(NO_FM), {"source": "manual"}).render()
    assert out == "---\nsource: manual\n---\n\njust a body\nsecond line\n"


def test_fields_on_bom_file_keep_bom():
    out = apply_fields(parse_note(BOM), {"title": "b"}).render()
    assert out == "﻿---\ntitle: b\n---\n\nbody\n"


def test_fields_on_invalid_yaml_raise():
    bad = "---\ntitle: [unclosed\n---\n\nbody\n"
    with pytest.raises(MalformedNote):
        apply_fields(parse_note(bad), {"title": "x"})


def test_long_value_wraps_like_pyyaml_and_stays_valid():
    long = "word " * 30
    out = apply_fields(parse_note(AWKWARD), {"title": long.strip()}).render()
    assert load_metadata(parse_note(out))["title"] == long.strip()
    assert "# trailing comment" not in out  # a wrapped (multi-line) value replaces the whole line


def test_find_key_block_spans_and_lines_of():
    lines = lines_of(parse_note(AWKWARD).fm_inner)
    assert find_key_block(lines, "tags") == (5, 8)
    assert find_key_block(lines, "zeta") == (2, 3)
    assert find_key_block(lines, "missing") is None
    assert lines_of("a\nb") == ["a\n", "b"]
    assert lines_of("a b\n") == ["a b\n"]  # only \n splits


def test_load_metadata():
    meta = load_metadata(parse_note(AWKWARD))
    assert meta["title"] == "Quoted: title"
    assert meta["alpha"] == "it's"
    assert meta["tags"] == ["one", "two"]
    assert load_metadata(parse_note(NO_FM)) == {}
    assert load_metadata(parse_note(EMPTY_FM)) == {}
    with pytest.raises(MalformedNote):
        load_metadata(parse_note("---\n- a list\n---\n\nb\n"))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_vault_write_text.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'ghostbrain.vault_write'`.

- [ ] **Step 3: Write the errors module**

Create `ghostbrain/vault_write/errors.py`:

```python
"""Exceptions raised by the vault write path. ``ghostbrain.api.vault_http``
maps them to HTTP statuses (400 / 404 / 409 / 422)."""
from __future__ import annotations

CONFLICT_MESSAGE = "note changed since you read it — re-read and retry"


class VaultWriteError(Exception):
    """Base class for every vault-write failure."""


class InvalidPath(VaultWriteError, ValueError):
    """Vault-relative path is absolute, traverses, escapes the root, or has a
    suffix the write path does not handle."""


class FileMissing(VaultWriteError):
    """modify / delete / move targeted a file that does not exist."""


class MalformedNote(VaultWriteError):
    """The file is not UTF-8, or a field edit hit frontmatter that is not a
    YAML mapping."""


class WriteConflict(VaultWriteError):
    """The file changed since the caller read it (etag mismatch), or a create
    / move destination already exists."""

    def __init__(self, current_etag: str | None, message: str = CONFLICT_MESSAGE) -> None:
        super().__init__(message)
        self.current_etag = current_etag
```

- [ ] **Step 4: Write the text module**

Create `ghostbrain/vault_write/text.py`:

```python
"""Byte-preserving frontmatter text operations (spec B §1 step 3).

Everything works on ``str`` decoded strictly from UTF-8 with a BOM kept as
U+FEFF, so ``parse_note(t).render() == t`` for every input and re-encoding
gives back the original bytes. Nothing the caller did not ask to change is
re-serialised: a body splice keeps the frontmatter block's exact text, and a
field edit rewrites only that key's line (or, for a multi-line value, only
that key's block).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Any, Mapping

import yaml

from ghostbrain.vault_write.errors import MalformedNote

BOM = "﻿"


class _DeleteField:
    """Sentinel type: ``fields={"k": DELETE_FIELD}`` removes key ``k``."""

    def __repr__(self) -> str:
        return "DELETE_FIELD"


DELETE_FIELD: Any = _DeleteField()

# Optional leading blank lines, then an opening fence of exactly three dashes.
_OPEN_RE = re.compile(r"(?:[ \t]*\r?\n)*---[ \t]*(\r?\n)")
_CLOSE_RE = re.compile(r"-{3,}[ \t]*(?:\r?\n)?")
_GAP_RE = re.compile(r"(?:[ \t]*\r?\n)*")
_LINE_RE = re.compile(r"[^\n]*\n|[^\n]+\Z")
# A top-level `key:` line. Keys start in column 0; quoted keys allowed.
_KEY_LINE_RE = re.compile(
    r"(?P<keyfull>(?P<key>\"(?:[^\"\\\r\n]|\\.)*\"|'(?:[^'\r\n]|'')*'"
    r"|[^\s#'\"\-?:,\[\]{}&*!|>%@`][^:\r\n]*?)[ \t]*)"
    r":(?=[ \t]|\r?\n|\Z)(?P<rest>[^\r\n]*)"
)
_SEQ_RE = re.compile(r"-(?:[ \t]|\r?\n|\Z)")
_QUOTED_VALUE_RE = re.compile(
    r"(?P<val>[ \t]*(?:\"(?:[^\"\\]|\\.)*\"|'(?:[^']|'')*'))(?P<comment>[ \t]+#.*)?[ \t]*"
)
_PLAIN_VALUE_RE = re.compile(r"(?P<val>.*?)(?P<comment>[ \t]+#.*)?")


def lines_of(text: str) -> list[str]:
    """Split on ``\\n`` only (``str.splitlines`` would also split on U+2028
    etc.), keeping line endings."""
    return _LINE_RE.findall(text)


@dataclass(frozen=True)
class ParsedNote:
    bom: str
    has_frontmatter: bool
    fm_head: str  # leading blank lines + opening fence line incl. EOL
    fm_inner: str  # YAML text between the fences
    fm_close: str  # closing fence line incl. its EOL (may lack one at EOF)
    gap: str  # whitespace-only lines between the closing fence and the body
    body: str
    eol: str  # "\r\n" or "\n" — the file's line ending

    @property
    def frontmatter_text(self) -> str:
        return self.bom + self.fm_head + self.fm_inner + self.fm_close

    def render(self) -> str:
        return self.frontmatter_text + self.gap + self.body


def _detect_eol(text: str) -> str:
    i = text.find("\n")
    return "\r\n" if i > 0 and text[i - 1] == "\r" else "\n"


def _to_eol(text: str, eol: str) -> str:
    return re.sub(r"(?<!\r)\n", "\r\n", text) if eol == "\r\n" else text


def parse_note(text: str) -> ParsedNote:
    bom = BOM if text.startswith(BOM) else ""
    rest = text[len(bom):]
    m = _OPEN_RE.match(rest)
    if m:
        offset = m.end()
        for line in lines_of(rest[m.end():]):
            if _CLOSE_RE.fullmatch(line):
                close_end = offset + len(line)
                gap_m = _GAP_RE.match(rest, close_end)
                gap = gap_m.group(0) if gap_m else ""
                return ParsedNote(
                    bom=bom,
                    has_frontmatter=True,
                    fm_head=rest[: m.end()],
                    fm_inner=rest[m.end():offset],
                    fm_close=line,
                    gap=gap,
                    body=rest[close_end + len(gap):],
                    eol=m.group(1),
                )
            offset += len(line)
    # No frontmatter — or an opening fence that never closes, which
    # python-frontmatter also treats as plain body (e.g. a leading <hr>).
    return ParsedNote(bom, False, "", "", "", "", rest, _detect_eol(rest))


def load_metadata(parsed: ParsedNote) -> dict[str, Any]:
    if not parsed.has_frontmatter:
        return {}
    try:
        data = yaml.safe_load(parsed.fm_inner)
    except yaml.YAMLError as e:
        raise MalformedNote(f"frontmatter is not valid YAML: {e}") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise MalformedNote("frontmatter is not a YAML mapping")
    return data


def splice_body(parsed: ParsedNote, body: str, *, ensure_newline: bool) -> ParsedNote:
    new_body = _to_eol(body, parsed.eol)
    if ensure_newline:
        new_body = new_body.rstrip("\r\n") + parsed.eol
    if not parsed.has_frontmatter:
        return replace(parsed, body=new_body)
    close = parsed.fm_close
    if not close.endswith("\n"):
        close += parsed.eol
    gap = parsed.gap
    if not gap and not parsed.body:
        gap = parsed.eol  # house style (frontmatter.dumps): one blank line
    return replace(parsed, fm_close=close, gap=gap, body=new_body)


def _key_matches(key_text: str, key: str) -> bool:
    if key_text[:1] in ("'", '"'):
        try:
            return yaml.safe_load(key_text) == key
        except yaml.YAMLError:
            return False
    return key_text == key


def find_key_block(lines: list[str], key: str) -> tuple[int, int] | None:
    """Return ``(start, end)`` line indices of top-level ``key``'s block: the
    key line plus indented / block-sequence continuation lines. Trailing blank
    lines are not part of the block."""
    for i, line in enumerate(lines):
        m = _KEY_LINE_RE.match(line)
        if m is None or not _key_matches(m.group("key"), key):
            continue
        end = j = i + 1
        while j < len(lines):
            nxt = lines[j]
            if not nxt.strip():
                j += 1
                continue
            if nxt[0] in " \t" or _SEQ_RE.match(nxt):
                end = j = j + 1
                continue
            break
        return i, end
    return None


def _dump(key: str, value: Any) -> str:
    # PyYAML defaults (width 80, block style) — byte-compatible with the
    # legacy ``frontmatter.dumps`` writers this path replaces.
    return yaml.safe_dump({key: value}, default_flow_style=False, allow_unicode=True, sort_keys=False)


def _dumped_key(key: str) -> str:
    return _dump(key, None)[: -len(": null\n")]


def _inline_comment(rest: str) -> str:
    m = _QUOTED_VALUE_RE.fullmatch(rest) or _PLAIN_VALUE_RE.fullmatch(rest)
    return (m.group("comment") or "") if m else ""


def _render_existing(block: list[str], key: str, value: Any, eol: str) -> list[str]:
    m = _KEY_LINE_RE.match(block[0])
    assert m is not None  # find_key_block only returns spans that start on a key line
    val_part = _dump(key, value)[len(_dumped_key(key)) + 1:]  # text after the colon
    if len(block) == 1 and val_part.startswith(" ") and val_part.count("\n") == 1:
        first = block[0]
        line_eol = "\r\n" if first.endswith("\r\n") else ("\n" if first.endswith("\n") else "")
        rest = m.group("rest")
        sep = rest[: len(rest) - len(rest.lstrip(" \t"))] or " "
        return [m.group("keyfull") + ":" + sep + val_part.strip() + _inline_comment(rest) + line_eol]
    return lines_of(_to_eol(m.group("keyfull") + ":" + val_part, eol))


def _same(a: Any, b: Any) -> bool:
    return type(a) is type(b) and a == b


def apply_fields(parsed: ParsedNote, fields: Mapping[str, Any]) -> ParsedNote:
    if not fields:
        return parsed
    if not parsed.has_frontmatter:
        live = {k: v for k, v in fields.items() if v is not DELETE_FIELD}
        if not live:
            return parsed
        inner = "".join(_to_eol(_dump(k, v), parsed.eol) for k, v in live.items())
        return replace(
            parsed,
            has_frontmatter=True,
            fm_head="---" + parsed.eol,
            fm_inner=inner,
            fm_close="---" + parsed.eol,
            gap=parsed.eol if parsed.body else "",
        )
    existing = load_metadata(parsed)
    lines = lines_of(parsed.fm_inner)
    for key, value in fields.items():
        span = find_key_block(lines, key)
        if value is DELETE_FIELD:
            if span is not None:
                del lines[span[0]:span[1]]
            continue
        if span is not None and key in existing and _same(existing[key], value):
            continue
        if span is None:
            lines.extend(lines_of(_to_eol(_dump(key, value), parsed.eol)))
        else:
            lines[span[0]:span[1]] = _render_existing(lines[span[0]:span[1]], key, value, parsed.eol)
    out = replace(parsed, fm_inner="".join(lines))
    meta = load_metadata(out)
    for key, value in fields.items():
        if value is DELETE_FIELD:
            if key in meta:
                raise MalformedNote(f"could not remove field {key!r}")
        elif meta.get(key) != value:
            raise MalformedNote(f"field {key!r} did not round-trip through YAML")
    return out
```

Create `ghostbrain/vault_write/__init__.py`. Task 2 extends this file.

```python
"""The single vault write path (spec 2026-10-09-ai-changes-revert-design.md, slice B1)."""
from ghostbrain.vault_write.errors import (
    FileMissing,
    InvalidPath,
    MalformedNote,
    VaultWriteError,
    WriteConflict,
)
from ghostbrain.vault_write.text import (
    DELETE_FIELD,
    ParsedNote,
    apply_fields,
    find_key_block,
    lines_of,
    load_metadata,
    parse_note,
    splice_body,
)

__all__ = [
    "DELETE_FIELD",
    "FileMissing",
    "InvalidPath",
    "MalformedNote",
    "ParsedNote",
    "VaultWriteError",
    "WriteConflict",
    "apply_fields",
    "find_key_block",
    "lines_of",
    "load_metadata",
    "parse_note",
    "splice_body",
]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_vault_write_text.py -q`
Expected: all pass. If `test_multiline_field_reserialises_only_its_block` or `test_find_key_block_spans_and_lines_of` fail on an index, print `lines_of(parse_note(AWKWARD).fm_inner)` and fix the **implementation**, not the expected spans. Line 0 is the comment, line 1 is `title`, line 2 is `zeta`, and line 5 is `tags`.

- [ ] **Step 6: Add the file to CI**

In `.github/workflows/ci.yml`, in the `Run tests` list, add this line directly after `tests/test_conftest_isolation.py \`:

```yaml
            tests/test_vault_write_text.py \
```

- [ ] **Step 7: Commit**

```bash
git add ghostbrain/vault_write/ tests/test_vault_write_text.py .github/workflows/ci.yml
git commit -m "feat(vault-write): byte-preserving frontmatter splice and line-level field edits"
```

---

### Task 2: `vault_write` writer (actor, etag, path guard, lock, atomic write, ops)

**Files:**
- Create: `ghostbrain/vault_write/actor.py`
- Create: `ghostbrain/vault_write/etag.py`
- Create: `ghostbrain/vault_write/writer.py`
- Modify: `ghostbrain/vault_write/__init__.py`
- Create: `tests/test_vault_write_writer.py`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: Task 1's `parse_note`, `splice_body`, `apply_fields`, `load_metadata`, `find_key_block`, `lines_of`, and the errors.
- Produces: `write`, `write_new`, `read`, `current_etag`, `resolve_safe`, `WriteResult`, `NoteSnapshot`, `Op`, `WRITABLE_SUFFIXES`, `compute_etag`, `normalize_if_match`, `Actor`, `USER`, `ASSISTANT`, `MCP`, `parse_actor`, `plugin_actor`, `worker_actor`, exactly as in the Interfaces block. Tests patch the module-level names `writer._now_iso` and `writer._read_bytes`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vault_write_writer.py`:

```python
"""vault_write.write — ops, etags, atomicity, locking (spec B1)."""
from __future__ import annotations

import os
import stat
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from ghostbrain import vault_write
from ghostbrain.vault_write import (
    ASSISTANT,
    DELETE_FIELD,
    MCP,
    USER,
    FileMissing,
    InvalidPath,
    WriteConflict,
    compute_etag,
    current_etag,
    normalize_if_match,
    parse_actor,
    plugin_actor,
    read,
    worker_actor,
    write,
    write_new,
)
from ghostbrain.vault_write import writer

NOW = "2026-10-09T10:00:00+00:00"
NOTE = (
    "---\n"
    "# keep me\n"
    "title: \"Odd: quoting\"\n"
    "zeta: 1\n"
    "updated: '2026-01-01T00:00:00+00:00'\n"
    "---\n"
    "\n"
    "old body\n"
)


@pytest.fixture
def vw_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("VAULT_PATH", str(vault))
    monkeypatch.setattr(writer, "_now_iso", lambda: NOW)
    return vault


def _put(vault: Path, rel: str, text: str) -> Path:
    p = vault / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(text.encode("utf-8"))
    return p


# ── actor / etag helpers ─────────────────────────────────────────────────

def test_actor_helpers():
    assert USER == "user" and ASSISTANT == "assistant" and MCP == "mcp"
    assert plugin_actor("familiar") == "plugin:familiar"
    assert worker_actor("jot-router") == "worker:jot-router"
    for bad in ("", "admin", "plugin:", "plugin:../x", "worker:a b", "User"):
        with pytest.raises(ValueError):
            parse_actor(bad)


def test_compute_etag_and_normalize_if_match():
    assert compute_etag(b"abc") == "ba7816bf8f01cfea"
    assert len(compute_etag(b"")) == 16
    assert normalize_if_match('"ba7816bf8f01cfea"') == "ba7816bf8f01cfea"
    assert normalize_if_match('W/"ba7816bf8f01cfea"') == "ba7816bf8f01cfea"
    assert normalize_if_match("ba7816bf8f01cfea") == "ba7816bf8f01cfea"
    assert normalize_if_match(None) is None
    assert normalize_if_match("") is None
    assert normalize_if_match("*") is None


# ── path guard ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("rel", ["", "/etc/x.md", "../x.md", "a/../../x.md", "x.sh", "a\x00.md"])
def test_rejects_unsafe_paths(vw_vault, rel):
    with pytest.raises(InvalidPath):
        write(rel, content="x", op="create", actor=USER)


def test_invalid_actor_and_bad_arg_combinations(vw_vault):
    with pytest.raises(ValueError):
        write("a.md", content="x", op="create", actor="admin")
    with pytest.raises(ValueError):
        write("a.md", content="x", body="y", actor=USER)
    with pytest.raises(ValueError):
        write("a.md", op="move", actor=USER)
    with pytest.raises(ValueError):
        write("a.md", actor=USER)  # modify with nothing to do
    with pytest.raises(ValueError):
        write("a.md", body="x", op="create", actor=USER)


# ── create ───────────────────────────────────────────────────────────────

def test_create_md_adds_trailing_newline(vw_vault):
    res = write("20-contexts/work/notes/a.md", content="# A", op="create", actor=USER)
    p = vw_vault / "20-contexts/work/notes/a.md"
    assert p.read_bytes() == b"# A\n"
    assert res.status == "applied" and res.change_id is None
    assert res.etag == compute_etag(b"# A\n")
    assert res.path == "20-contexts/work/notes/a.md"


def test_create_html_is_verbatim(vw_vault):
    write("docs/a.html", content="<p>x</p>", op="create", actor=MCP)
    assert (vw_vault / "docs/a.html").read_bytes() == b"<p>x</p>"


def test_create_over_existing_conflicts(vw_vault):
    p = _put(vw_vault, "a.md", "old\n")
    with pytest.raises(WriteConflict) as ei:
        write("a.md", content="new", op="create", actor=USER)
    assert ei.value.current_etag == compute_etag(b"old\n")
    assert p.read_text() == "old\n"


def test_new_file_mode_is_0644(vw_vault):
    if sys.platform == "win32":
        pytest.skip("POSIX permissions")
    write("a.md", content="x", op="create", actor=USER)
    assert stat.S_IMODE((vw_vault / "a.md").stat().st_mode) == 0o644


def test_write_new_suffixes_instead_of_overwriting(vw_vault):
    _put(vw_vault, "d/x.html", "first")
    res2 = write_new("d/x.html", "second", actor=MCP)
    res3 = write_new("d/x.html", "third", actor=MCP)
    assert res2.path == "d/x-2.html" and res3.path == "d/x-3.html"
    assert (vw_vault / "d/x.html").read_text() == "first"


# ── modify: body splice ──────────────────────────────────────────────────

def test_body_save_keeps_frontmatter_bytes_and_bumps_only_updated(vw_vault):
    p = _put(vw_vault, "n.md", NOTE)
    res = write("n.md", body="new body", actor=USER)
    out = p.read_text()
    assert out == NOTE.replace("2026-01-01T00:00:00+00:00", NOW).replace("old body", "new body")
    assert res.updated == NOW
    assert res.etag == compute_etag(p.read_bytes())


def test_body_save_without_updated_key_does_not_invent_it(vw_vault):
    p = _put(vw_vault, "n.md", "---\nsource: manual\n---\n\nbody\n")
    res = write("n.md", body="rewritten", actor=USER)
    assert p.read_text() == "---\nsource: manual\n---\n\nrewritten\n"
    assert res.updated is None


def test_body_save_on_invalid_yaml_skips_bump_and_keeps_bytes(vw_vault):
    broken = "---\ntitle: [unclosed\nupdated: '2026-01-01T00:00:00+00:00'\n---\n\nold\n"
    p = _put(vw_vault, "n.md", broken)
    res = write("n.md", body="new", actor=USER)
    assert p.read_text() == broken.replace("old\n", "new\n")
    assert res.updated is None


def test_identical_write_does_not_touch_the_file(vw_vault):
    p = _put(vw_vault, "n.md", "---\nsource: manual\n---\n\nsame\n")
    before = p.stat().st_mtime_ns
    time.sleep(0.01)
    res = write("n.md", body="same", actor=USER)
    assert p.stat().st_mtime_ns == before
    assert res.etag == compute_etag(p.read_bytes())


# ── etag precondition ────────────────────────────────────────────────────

def test_matching_base_etag_applies(vw_vault):
    p = _put(vw_vault, "n.md", NOTE)
    write("n.md", body="x", actor=USER, base_etag=compute_etag(NOTE.encode()))
    assert "x\n" in p.read_text()


def test_stale_base_etag_conflicts_and_leaves_file(vw_vault):
    p = _put(vw_vault, "n.md", NOTE)
    with pytest.raises(WriteConflict) as ei:
        write("n.md", body="x", actor=ASSISTANT, base_etag="0000000000000000")
    assert ei.value.current_etag == compute_etag(NOTE.encode())
    assert p.read_text() == NOTE


def test_base_etag_on_missing_file_conflicts(vw_vault):
    with pytest.raises(WriteConflict) as ei:
        write("gone.md", body="x", actor=USER, base_etag="0000000000000000")
    assert ei.value.current_etag is None


def test_modify_missing_file_raises_file_missing(vw_vault):
    with pytest.raises(FileMissing):
        write("gone.md", body="x", actor=USER)


# ── fields / delete / move ───────────────────────────────────────────────

def test_fields_edit_explicit_updated_wins(vw_vault):
    p = _put(vw_vault, "n.md", NOTE)
    res = write("n.md", fields={"zeta": 2, "updated": "2026-02-02T00:00:00+00:00"}, actor=USER)
    out = p.read_text()
    assert "zeta: 2\n" in out and "updated: '2026-02-02T00:00:00+00:00'\n" in out
    assert res.updated == "2026-02-02T00:00:00+00:00"
    assert "# keep me\n" in out


def test_delete(vw_vault):
    p = _put(vw_vault, "n.md", NOTE)
    res = write("n.md", op="delete", actor=USER)
    assert not p.exists() and res.etag is None


def test_move_with_fields_and_project_delete(vw_vault):
    _put(vw_vault, "inbox/j.md", "---\nproject: old\ncontext: null\n---\n\nb\n")
    res = write(
        "inbox/j.md", op="move", dest="ctx/work/j.md",
        fields={"context": "work", "project": DELETE_FIELD}, actor=worker_actor("jot-router"),
    )
    assert not (vw_vault / "inbox/j.md").exists()
    assert (vw_vault / "ctx/work/j.md").read_text() == "---\ncontext: work\n---\n\nb\n"
    assert res.path == "ctx/work/j.md"


def test_move_onto_existing_destination_conflicts(vw_vault):
    _put(vw_vault, "a.md", "a\n")
    _put(vw_vault, "b.md", "b\n")
    with pytest.raises(WriteConflict):
        write("a.md", op="move", dest="b.md", actor=USER)
    assert (vw_vault / "a.md").read_text() == "a\n"
    assert (vw_vault / "b.md").read_text() == "b\n"


# ── atomicity / permissions / locking ────────────────────────────────────

def test_failed_replace_leaves_original_and_no_temp_files(vw_vault, monkeypatch):
    p = _put(vw_vault, "n.md", NOTE)

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(writer.os, "replace", boom)
    with pytest.raises(OSError):
        write("n.md", body="x", actor=USER)
    assert p.read_text() == NOTE
    assert [f.name for f in vw_vault.iterdir()] == ["n.md"]


def test_existing_permissions_are_preserved(vw_vault):
    if sys.platform == "win32":
        pytest.skip("POSIX permissions")
    p = _put(vw_vault, "n.md", NOTE)
    p.chmod(0o640)
    write("n.md", body="x", actor=USER)
    assert stat.S_IMODE(p.stat().st_mode) == 0o640


def test_concurrent_field_edits_never_lose_updates(vw_vault, monkeypatch):
    p = _put(vw_vault, "n.md", "---\ntitle: a\n---\n\nbody\n")
    real_read = writer._read_bytes

    def slow_read(path):
        data = real_read(path)
        time.sleep(0.005)  # widen the read→write window a missing lock would lose
        return data

    monkeypatch.setattr(writer, "_read_bytes", slow_read)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: write("n.md", fields={f"k{i}": i}, actor=USER), range(16)))
    meta = yaml.safe_load(p.read_text().split("---\n")[1])
    assert all(meta[f"k{i}"] == i for i in range(16))


# ── read / current_etag ──────────────────────────────────────────────────

def test_read_snapshot_and_current_etag(vw_vault):
    _put(vw_vault, "n.md", NOTE)
    snap = read("n.md")
    assert snap.etag == compute_etag(NOTE.encode())
    assert snap.body == "old body"
    assert snap.metadata()["title"] == "Odd: quoting"
    assert current_etag("n.md") == snap.etag
    assert current_etag("missing.md") is None
    with pytest.raises(FileMissing):
        read("missing.md")


def test_package_reexports_everything_in_the_interface():
    for name in ("write", "write_new", "read", "current_etag", "resolve_safe", "WriteResult",
                 "NoteSnapshot", "WRITABLE_SUFFIXES", "Actor"):
        assert hasattr(vault_write, name), name
    assert os.path.basename(writer.__file__) == "writer.py"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest tests/test_vault_write_writer.py -q`
Expected: collection error, `ImportError: cannot import name 'ASSISTANT' from 'ghostbrain.vault_write'`.

- [ ] **Step 3: Write actor and etag**

Create `ghostbrain/vault_write/actor.py`:

```python
"""Who is writing. B1 validates and threads the actor; B2 records it on the
Changes screen. ``user`` writes never get a change row (spec B §1 step 7)."""
from __future__ import annotations

import re

Actor = str

USER: Actor = "user"
ASSISTANT: Actor = "assistant"
MCP: Actor = "mcp"

_ID = r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}"
_ACTOR_RE = re.compile(rf"user|assistant|mcp|plugin:{_ID}|worker:{_ID}")


def parse_actor(value: str) -> Actor:
    if not isinstance(value, str) or not _ACTOR_RE.fullmatch(value) or ".." in value:
        raise ValueError(f"invalid actor: {value!r}")
    return value


def plugin_actor(plugin_id: str) -> Actor:
    return parse_actor(f"plugin:{plugin_id}")


def worker_actor(job: str) -> Actor:
    return parse_actor(f"worker:{job}")
```

Create `ghostbrain/vault_write/etag.py`:

```python
"""Content-hash etags over raw file bytes (spec B §1 step 2)."""
from __future__ import annotations

import hashlib

ETAG_LEN = 16


def compute_etag(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:ETAG_LEN]


def normalize_if_match(value: str | None) -> str | None:
    """Accept ``"abc"``, ``W/"abc"`` or bare ``abc``. ``*`` / empty mean "no
    precondition" (the op's own existence rules still apply)."""
    if value is None:
        return None
    v = value.strip()
    if v.startswith("W/"):
        v = v[2:].strip()
    v = v.strip('"').strip()
    if not v or v == "*":
        return None
    return v
```

- [ ] **Step 4: Write the writer**

Create `ghostbrain/vault_write/writer.py`:

```python
"""The single vault write path: lock → etag check → minimal-diff bytes →
atomic replace (spec B §1).

B2 adds the history snapshot + change record and B3 the risk hold, both at
the marked hook point inside ``write``. That is why ``actor`` is required and
``reason`` accepted now, though B1 stores neither.
"""
from __future__ import annotations

import contextlib
import logging
import os
import stat
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Literal, Mapping

import ghostbrain.paths as _paths
from ghostbrain.vault_write.actor import Actor, parse_actor
from ghostbrain.vault_write.errors import FileMissing, InvalidPath, MalformedNote, WriteConflict
from ghostbrain.vault_write.etag import compute_etag
from ghostbrain.vault_write.text import (
    ParsedNote,
    apply_fields,
    find_key_block,
    lines_of,
    load_metadata,
    parse_note,
    splice_body,
)

log = logging.getLogger("ghostbrain.vault_write")

Op = Literal["create", "modify", "delete", "move"]
_OPS = ("create", "modify", "delete", "move")
WRITABLE_SUFFIXES: tuple[str, ...] = (".md", ".html")
NEW_FILE_MODE = 0o644


@dataclass(frozen=True)
class WriteResult:
    status: Literal["applied", "pending"]
    change_id: str | None
    etag: str | None
    path: str
    updated: str | None


@dataclass(frozen=True)
class NoteSnapshot:
    path: str
    etag: str
    parsed: ParsedNote

    @property
    def body(self) -> str:
        return self.parsed.body.strip()

    def metadata(self) -> dict[str, Any]:
        return load_metadata(self.parsed)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _root() -> Path:
    return _paths.vault_path().resolve()


def resolve_safe(rel_path: str, *, suffixes: tuple[str, ...] = WRITABLE_SUFFIXES) -> Path:
    """The house guard: vault-relative, no traversal, stays under the root,
    allowed suffix."""
    if not rel_path or rel_path.startswith("/") or "\x00" in rel_path:
        raise InvalidPath("path must be vault-relative")
    candidate = Path(rel_path)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise InvalidPath("path must not contain '..' or be absolute")
    root = _root()
    target = (root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise InvalidPath("path escapes the vault root") from None
    if target.suffix.lower() not in suffixes:
        raise InvalidPath(f"only {', '.join(suffixes)} files are allowed")
    return target


def _rel(path: Path) -> str:
    return path.relative_to(_root()).as_posix()


# Per-path locks. One sidecar process owns all writes (scheduler + worker run
# in-process), so a threading.Lock per resolved path is the whole story. The
# map only grows by paths actually written — small.
_registry_lock = threading.Lock()
_path_locks: dict[str, threading.Lock] = {}


@contextlib.contextmanager
def _locked(*paths: Path) -> Iterator[None]:
    keys = sorted({os.path.normcase(str(p)) for p in paths})  # fixed order: no deadlock on move
    with _registry_lock:
        locks = [_path_locks.setdefault(k, threading.Lock()) for k in keys]
    for lock in locks:
        lock.acquire()
    try:
        yield
    finally:
        for lock in reversed(locks):
            lock.release()


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as e:
        raise MalformedNote(f"file is not valid UTF-8: {e}") from None


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        mode = NEW_FILE_MODE
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)  # mkstemp creates 0600; keep the note's own mode
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def _content_bytes(path: Path, content: str) -> bytes:
    if path.suffix.lower() == ".md" and not content.endswith("\n"):
        content += "\n"
    return content.encode("utf-8")


def _edit_bytes(
    current: bytes, *, body: str | None, fields: Mapping[str, Any] | None, suffix: str
) -> tuple[bytes, str | None]:
    parsed = parse_note(_decode(current))
    edits = dict(fields or {})
    updated = edits["updated"] if isinstance(edits.get("updated"), str) else None
    if (
        "updated" not in edits
        and parsed.has_frontmatter
        and find_key_block(lines_of(parsed.fm_inner), "updated") is not None
    ):
        try:
            load_metadata(parsed)
        except MalformedNote:
            log.warning("skipping `updated` bump: frontmatter is not valid YAML")
        else:
            updated = _now_iso()
            edits["updated"] = updated
    if body is not None:
        parsed = splice_body(parsed, body, ensure_newline=suffix.lower() == ".md")
    if edits:
        parsed = apply_fields(parsed, edits)
    return parsed.render().encode("utf-8"), updated


def _check_args(
    op: str, content: str | None, body: str | None, fields: Mapping[str, Any] | None, dest: str | None
) -> None:
    if op not in _OPS:
        raise ValueError(f"unknown op: {op!r}")
    if content is not None and (body is not None or fields):
        raise ValueError("content is a full replacement; do not combine it with body/fields")
    if (dest is not None) != (op == "move"):
        raise ValueError("dest is required for op='move' and only allowed there")
    if op == "create" and content is None:
        raise ValueError("op='create' needs content")
    if op == "delete" and (content is not None or body is not None or fields):
        raise ValueError("op='delete' takes no content/body/fields")
    if op == "move" and content is not None:
        raise ValueError("op='move' takes body/fields, not content")
    if op == "modify" and content is None and body is None and not fields:
        raise ValueError("op='modify' needs content, body or fields")


def write(
    rel_path: str,
    *,
    actor: Actor,
    content: str | None = None,
    body: str | None = None,
    fields: Mapping[str, Any] | None = None,
    op: Op = "modify",
    dest: str | None = None,
    reason: str = "",
    base_etag: str | None = None,
) -> WriteResult:
    actor = parse_actor(actor)
    _check_args(op, content, body, fields, dest)
    src = resolve_safe(rel_path)
    dst = resolve_safe(dest) if dest is not None else None
    if dst is not None and dst == src:
        raise ValueError("move destination equals the source")
    log.debug("vault write op=%s path=%s actor=%s reason=%s", op, rel_path, actor, reason)
    with _locked(src, *([dst] if dst is not None else [])):
        current = _read_bytes(src)
        etag_now = compute_etag(current) if current is not None else None
        if base_etag is not None and base_etag != etag_now:
            raise WriteConflict(etag_now)
        # B2/B3 hook point: risk check (→ pending), history snapshot, change row.
        if op == "create":
            if current is not None:
                raise WriteConflict(etag_now)
            assert content is not None
            data = _content_bytes(src, content)
            _atomic_write(src, data)
            return WriteResult("applied", None, compute_etag(data), _rel(src), None)
        if current is None:
            raise FileMissing(rel_path)
        if op == "delete":
            src.unlink()
            return WriteResult("applied", None, None, _rel(src), None)
        updated: str | None = None
        if content is not None:
            data = _content_bytes(src, content)
        elif body is not None or fields:
            data, updated = _edit_bytes(current, body=body, fields=fields, suffix=src.suffix)
        else:
            data = current  # plain move
        if dst is not None:
            existing = _read_bytes(dst)
            if existing is not None:
                raise WriteConflict(compute_etag(existing))
            _atomic_write(dst, data)
            src.unlink()
            return WriteResult("applied", None, compute_etag(data), _rel(dst), updated)
        if data != current:
            _atomic_write(src, data)
        return WriteResult("applied", None, compute_etag(data), _rel(src), updated)


def write_new(
    rel_path: str, content: str, *, actor: Actor, reason: str = "", max_attempts: int = 100
) -> WriteResult:
    """Create ``rel_path``; if taken, ``<stem>-2<suffix>``, ``-3``, … Never
    overwrites (generated docs, chat attachments)."""
    p = PurePosixPath(rel_path)
    for n in range(1, max_attempts + 1):
        candidate = rel_path if n == 1 else str(p.with_name(f"{p.stem}-{n}{p.suffix}"))
        try:
            return write(candidate, content=content, op="create", actor=actor, reason=reason)
        except WriteConflict:
            continue
    raise WriteConflict(None, f"no free file name near {rel_path!r} after {max_attempts} attempts")


def current_etag(rel_path: str, *, suffixes: tuple[str, ...] = WRITABLE_SUFFIXES) -> str | None:
    data = _read_bytes(resolve_safe(rel_path, suffixes=suffixes))
    return compute_etag(data) if data is not None else None


def read(rel_path: str, *, suffixes: tuple[str, ...] = WRITABLE_SUFFIXES) -> NoteSnapshot:
    path = resolve_safe(rel_path, suffixes=suffixes)
    data = _read_bytes(path)
    if data is None:
        raise FileMissing(rel_path)
    return NoteSnapshot(_rel(path), compute_etag(data), parse_note(_decode(data)))
```

Replace `ghostbrain/vault_write/__init__.py` with:

```python
"""The single vault write path (spec 2026-10-09-ai-changes-revert-design.md, slice B1)."""
from ghostbrain.vault_write.actor import (
    ASSISTANT,
    MCP,
    USER,
    Actor,
    parse_actor,
    plugin_actor,
    worker_actor,
)
from ghostbrain.vault_write.errors import (
    FileMissing,
    InvalidPath,
    MalformedNote,
    VaultWriteError,
    WriteConflict,
)
from ghostbrain.vault_write.etag import compute_etag, normalize_if_match
from ghostbrain.vault_write.text import (
    DELETE_FIELD,
    ParsedNote,
    apply_fields,
    find_key_block,
    lines_of,
    load_metadata,
    parse_note,
    splice_body,
)
from ghostbrain.vault_write.writer import (
    WRITABLE_SUFFIXES,
    NoteSnapshot,
    Op,
    WriteResult,
    current_etag,
    read,
    resolve_safe,
    write,
    write_new,
)

__all__ = [
    "ASSISTANT", "DELETE_FIELD", "MCP", "USER", "WRITABLE_SUFFIXES",
    "Actor", "FileMissing", "InvalidPath", "MalformedNote", "NoteSnapshot", "Op",
    "ParsedNote", "VaultWriteError", "WriteConflict", "WriteResult",
    "apply_fields", "compute_etag", "current_etag", "find_key_block", "lines_of",
    "load_metadata", "normalize_if_match", "parse_actor", "parse_note", "plugin_actor",
    "read", "resolve_safe", "splice_body", "worker_actor", "write", "write_new",
]
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest tests/test_vault_write_writer.py tests/test_vault_write_text.py -q`
Expected: all pass. If `test_compute_etag_and_normalize_if_match` fails on the literal, recompute it with `python -c "import hashlib;print(hashlib.sha256(b'abc').hexdigest()[:16])"`. The value should be `ba7816bf8f01cfea`.

- [ ] **Step 6: Add the file to CI**

In `.github/workflows/ci.yml`, directly after the `tests/test_vault_write_text.py \` line, add:

```yaml
            tests/test_vault_write_writer.py \
```

- [ ] **Step 7: Commit**

```bash
git add ghostbrain/vault_write/ tests/test_vault_write_writer.py .github/workflows/ci.yml
git commit -m "feat(vault-write): atomic locked write path with content-hash etags"
```

---

### Task 3: API read side: etag on GET, shared parser, error mapping

**Files:**
- Create: `ghostbrain/api/vault_http.py`
- Modify: `ghostbrain/api/main.py` (call `install_vault_write_errors(app)` right after `install_error_handling(app)`)
- Modify: `ghostbrain/api/repo/note.py` (`_resolve_safe`, `get_note`)
- Modify: `ghostbrain/api/models/note.py` (`Note.etag`)
- Create: `ghostbrain/api/tests/test_vault_http.py`

**Interfaces:**
- Consumes: `vault_write.read`, `vault_write.resolve_safe`, `normalize_if_match`, and the error classes.
- Produces:
  - `ghostbrain.api.vault_http.if_match(value: str | None = Header(default=None, alias="If-Match")) -> str | None`, a FastAPI dependency.
  - `ghostbrain.api.vault_http.install_vault_write_errors(app: FastAPI) -> None`.
  - `get_note()` now returns the key `"etag": str`.
  - `note._resolve_safe` is unchanged in behaviour and delegates to `vault_write.resolve_safe(rel, suffixes=(".md",))`.

- [ ] **Step 1: Write the failing tests**

Create `ghostbrain/api/tests/test_vault_http.py`:

```python
"""GET etag + vault-write error → HTTP mapping (spec B1)."""
from __future__ import annotations

from fastapi import Depends
from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app
from ghostbrain.api.repo.note import get_note
from ghostbrain.api.tests.conftest import TEST_TOKEN, write_note
from ghostbrain.api.vault_http import if_match
from ghostbrain.vault_write import (
    FileMissing,
    InvalidPath,
    MalformedNote,
    WriteConflict,
    compute_etag,
)

NOTE = "---\ntitle: Hello\n---\n\nbody text\n"


def test_get_note_returns_etag_of_file_bytes(tmp_vault):
    p = write_note(tmp_vault, "20-contexts/work/notes/n.md", NOTE)
    data = get_note("20-contexts/work/notes/n.md")
    assert data["etag"] == compute_etag(p.read_bytes())
    assert data["body"] == "body text"
    assert data["title"] == "Hello"


def test_get_note_bom_body_excludes_frontmatter(tmp_vault):
    p = tmp_vault / "20-contexts/work/notes/bom.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes("﻿---\ntitle: Bom\n---\n\nreal body\n".encode("utf-8"))
    data = get_note("20-contexts/work/notes/bom.md")
    assert data["body"] == "real body"
    assert data["frontmatter"] == {"title": "Bom"}


def test_get_note_crlf(tmp_vault):
    p = tmp_vault / "20-contexts/work/notes/crlf.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"---\r\ntitle: C\r\n---\r\n\r\nline one\r\nline two\r\n")
    data = get_note("20-contexts/work/notes/crlf.md")
    assert data["body"] == "line one\r\nline two"
    assert data["frontmatter"]["title"] == "C"


def test_get_route_includes_etag(client, tmp_vault, auth_headers):
    p = write_note(tmp_vault, "20-contexts/work/notes/n.md", NOTE)
    r = client.get("/v1/notes", params={"path": "20-contexts/work/notes/n.md"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["etag"] == compute_etag(p.read_bytes())


def test_get_note_invalid_yaml_is_still_404(client, tmp_vault, auth_headers):
    write_note(tmp_vault, "20-contexts/work/notes/bad.md", "---\ntitle: [x\n---\n\nb\n")
    r = client.get("/v1/notes", params={"path": "20-contexts/work/notes/bad.md"}, headers=auth_headers)
    assert r.status_code == 404


def _app_raising(exc: Exception) -> TestClient:
    app = create_app(token=TEST_TOKEN)

    @app.get("/v1/__raise")
    def _raise() -> dict:
        raise exc

    @app.get("/v1/__ifmatch")
    def _ifmatch(base: str | None = Depends(if_match)) -> dict:
        return {"base": base}

    return TestClient(app)


def test_write_conflict_maps_to_409_with_current_etag(tmp_vault, tmp_state_dir, auth_headers):
    with _app_raising(WriteConflict("abcdefabcdefabcd")) as c:
        r = c.get("/v1/__raise", headers=auth_headers)
    assert r.status_code == 409
    assert r.json() == {
        "detail": "note changed since you read it — re-read and retry",
        "currentEtag": "abcdefabcdefabcd",
    }


def test_other_errors_map_to_404_422_400(tmp_vault, tmp_state_dir, auth_headers):
    for exc, status in ((FileMissing("x.md"), 404), (MalformedNote("bad"), 422), (InvalidPath("nope"), 400)):
        with _app_raising(exc) as c:
            assert c.get("/v1/__raise", headers=auth_headers).status_code == status


def test_if_match_dependency_normalizes(tmp_vault, tmp_state_dir, auth_headers):
    with _app_raising(RuntimeError("unused")) as c:
        assert c.get("/v1/__ifmatch", headers=auth_headers).json() == {"base": None}
        h = {**auth_headers, "If-Match": 'W/"0123456789abcdef"'}
        assert c.get("/v1/__ifmatch", headers=h).json() == {"base": "0123456789abcdef"}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest ghostbrain/api/tests/test_vault_http.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'ghostbrain.api.vault_http'`.

- [ ] **Step 3: Implement the HTTP glue**

Create `ghostbrain/api/vault_http.py`:

```python
"""HTTP glue for the vault write path: If-Match → base_etag, and
vault-write exceptions → status codes, registered once for every route."""
from __future__ import annotations

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from ghostbrain.vault_write import (
    FileMissing,
    InvalidPath,
    MalformedNote,
    WriteConflict,
    normalize_if_match,
)


def if_match(value: str | None = Header(default=None, alias="If-Match")) -> str | None:
    """FastAPI dependency: the etag a write is based on, or None."""
    return normalize_if_match(value)


def install_vault_write_errors(app: FastAPI) -> None:
    async def _conflict(_req: Request, exc: Exception) -> JSONResponse:
        assert isinstance(exc, WriteConflict)
        return JSONResponse(
            status_code=409,
            content={"detail": str(exc), "currentEtag": exc.current_etag},
        )

    async def _missing(_req: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": f"Note not found: {exc}"})

    async def _malformed(_req: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    async def _invalid(_req: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.add_exception_handler(WriteConflict, _conflict)
    app.add_exception_handler(FileMissing, _missing)
    app.add_exception_handler(MalformedNote, _malformed)
    app.add_exception_handler(InvalidPath, _invalid)
```

In `ghostbrain/api/main.py`, add the import `from ghostbrain.api.vault_http import install_vault_write_errors` next to the other `ghostbrain.api` imports. Then add one line inside `create_app`, directly after `install_error_handling(app)`:

```python
    install_vault_write_errors(app)
```

- [ ] **Step 4: Point `note.py` reads at the shared parser**

In `ghostbrain/api/repo/note.py`, replace the imports block and the `_resolve_safe` and `get_note` functions with the code below. Leave `_jsonable` and the exception classes as they are. `save_note_body` and `save_note_at_path` are untouched until Task 4.

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import frontmatter

from ghostbrain import vault_write
```

```python
def _resolve_safe(rel: str) -> Path:
    try:
        return vault_write.resolve_safe(rel, suffixes=(".md",))
    except vault_write.InvalidPath as e:
        raise NoteInvalidPath(str(e)) from None
```

```python
def get_note(rel_path: str) -> dict:
    """Read a note. The body comes from the same parser the write path splices
    with, so a save can never duplicate frontmatter into the body (BOM files,
    leading blank lines)."""
    target = _resolve_safe(rel_path)
    if not target.exists() or not target.is_file():
        raise NoteNotFound(rel_path)
    try:
        snap = vault_write.read(rel_path, suffixes=(".md",))
        meta = snap.metadata()
    except (vault_write.MalformedNote, vault_write.FileMissing) as e:
        raise NoteNotFound(f"could not parse: {e}")
    fm = _jsonable(dict(meta))
    title = str(fm.get("title") or target.stem)
    return {
        "path": rel_path,
        "title": title,
        "body": snap.body,
        "frontmatter": fm,
        "etag": snap.etag,
    }
```

The `import frontmatter` line stays until Task 4, because `save_note_body` still uses it.

In `ghostbrain/api/models/note.py`, add a field to `class Note`:

```python
    etag: str | None = None  # sha256(file bytes)[:16]; send back as If-Match
```

- [ ] **Step 5: Run the tests to verify they pass, plus the existing note and MCP suites**

Run: `python -m pytest ghostbrain/api/tests/test_vault_http.py ghostbrain/api/tests/ tests/test_mcp_tools.py tests/test_mcp_client.py tests/test_llm_providers_vault_tools.py -q`
Expected: all pass. Existing callers of `get_note` only read keys, so the extra `etag` key is harmless.

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/api/vault_http.py ghostbrain/api/main.py ghostbrain/api/repo/note.py ghostbrain/api/models/note.py ghostbrain/api/tests/test_vault_http.py
git commit -m "feat(api): etag on note reads and 409/404/422/400 mapping for vault writes"
```

---

### Task 4: Migrate `note.py` writers (`PATCH /v1/notes/body`, `PUT /v1/notes`)

**Files:**
- Modify: `ghostbrain/api/repo/note.py` (`save_note_body`, `save_note_at_path`; drop `import frontmatter` and `_now_iso`)
- Modify: `ghostbrain/api/routes/notes.py` (`upsert_note`, `patch_note_body`)
- Modify: `ghostbrain/api/tests/test_routes_notes_upsert.py:11`
- Create: `ghostbrain/api/tests/test_note_write_path.py`

**Interfaces:**
- Consumes: `vault_write.write`, `USER`, `plugin_actor`, `if_match` (Task 3).
- Produces:
  - `save_note_body(rel_path: str, body: str, *, actor: Actor = USER, base_etag: str | None = None) -> {"path", "updated", "etag"}`
  - `save_note_at_path(rel_path: str, content: str, *, actor: Actor = USER, base_etag: str | None = None) -> {"path", "created", "etag"}`

- [ ] **Step 1: Write the failing tests**

Create `ghostbrain/api/tests/test_note_write_path.py`:

```python
"""note.py writers on the vault write path: byte preservation, golden parity
with the legacy writer for canonical files, If-Match on the routes."""
from __future__ import annotations

import frontmatter
import pytest

from ghostbrain.api.repo.note import save_note_at_path, save_note_body
from ghostbrain.api.tests.conftest import write_note
from ghostbrain.vault_write import compute_etag, writer

NOW = "2026-10-09T10:00:00+00:00"
REL = "20-contexts/work/notes/n.md"
HAND_EDITED = (
    "---\n"
    "# synced from mail — do not edit by hand\n"
    "source: gmail\n"
    "title: \"Re: Q3 plan\"\n"
    "context:   work\n"
    "updated: '2026-01-01T00:00:00+00:00'\n"
    "---\n"
    "\n"
    "old body\n"
)


@pytest.fixture(autouse=True)
def _frozen_now(monkeypatch):
    monkeypatch.setattr(writer, "_now_iso", lambda: NOW)


def _legacy_save_body(text: str, body: str, now: str) -> str:
    """The pre-B1 save_note_body algorithm, kept here as the golden oracle."""
    post = frontmatter.loads(text)
    post.content = body
    if "updated" in post.metadata:
        post["updated"] = now
    if post.metadata:
        return frontmatter.dumps(post) + "\n"
    return body if body.endswith("\n") else body + "\n"


def test_hand_edited_frontmatter_survives_byte_for_byte(tmp_vault):
    p = write_note(tmp_vault, REL, HAND_EDITED)
    res = save_note_body(REL, "# edited\n\nnew body")
    assert p.read_text() == HAND_EDITED.replace(
        "2026-01-01T00:00:00+00:00", NOW
    ).replace("old body\n", "# edited\n\nnew body\n")
    assert res == {"path": REL, "updated": NOW, "etag": compute_etag(p.read_bytes())}


def test_golden_canonical_file_matches_legacy_bytes(tmp_vault):
    canonical = frontmatter.dumps(frontmatter.Post(
        "old body", source="gmail", context="work", updated="2026-01-01T00:00:00+00:00",
    )) + "\n"
    p = write_note(tmp_vault, REL, canonical)
    save_note_body(REL, "new body")
    assert p.read_text() == _legacy_save_body(canonical, "new body", NOW)


def test_golden_plain_file_matches_legacy_bytes(tmp_vault):
    p = write_note(tmp_vault, "10-daily/2026-06-09.md", "plain\n")
    save_note_body("10-daily/2026-06-09.md", "rewritten")
    assert p.read_text() == _legacy_save_body("plain\n", "rewritten", NOW)


def test_bom_note_round_trip_does_not_duplicate_frontmatter(client, tmp_vault, auth_headers):
    p = tmp_vault / REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes("﻿---\ntitle: Bom\n---\n\nbody\n".encode("utf-8"))
    got = client.get("/v1/notes", params={"path": REL}, headers=auth_headers).json()
    r = client.patch(
        "/v1/notes/body",
        json={"path": REL, "body": got["body"] + "\n\nmore"},
        headers={**auth_headers, "If-Match": f'"{got["etag"]}"'},
    )
    assert r.status_code == 200
    assert p.read_bytes().decode("utf-8") == "﻿---\ntitle: Bom\n---\n\nbody\n\nmore\n"


def test_patch_body_with_current_if_match_applies(client, tmp_vault, auth_headers):
    p = write_note(tmp_vault, REL, HAND_EDITED)
    etag = compute_etag(p.read_bytes())
    r = client.patch(
        "/v1/notes/body", json={"path": REL, "body": "x"},
        headers={**auth_headers, "If-Match": f'"{etag}"'},
    )
    assert r.status_code == 200
    assert r.json()["etag"] == compute_etag(p.read_bytes())


def test_patch_body_with_stale_if_match_is_409_and_untouched(client, tmp_vault, auth_headers):
    p = write_note(tmp_vault, REL, HAND_EDITED)
    r = client.patch(
        "/v1/notes/body", json={"path": REL, "body": "x"},
        headers={**auth_headers, "If-Match": '"0000000000000000"'},
    )
    assert r.status_code == 409
    assert r.json()["currentEtag"] == compute_etag(p.read_bytes())
    assert p.read_text() == HAND_EDITED


def test_patch_body_without_if_match_still_saves(client, tmp_vault, auth_headers):
    write_note(tmp_vault, REL, HAND_EDITED)
    r = client.patch("/v1/notes/body", json={"path": REL, "body": "x"}, headers=auth_headers)
    assert r.status_code == 200


def test_upsert_returns_etag_and_honours_if_match(client, tmp_vault, auth_headers):
    r = client.put("/v1/notes", json={"path": "Familiar/m.md", "content": "v1"}, headers=auth_headers)
    assert r.status_code == 200
    first = r.json()
    assert first["created"] is True
    assert first["etag"] == compute_etag(b"v1\n")
    stale = client.put(
        "/v1/notes", json={"path": "Familiar/m.md", "content": "v2"},
        headers={**auth_headers, "If-Match": '"0000000000000000"'},
    )
    assert stale.status_code == 409
    ok = client.put(
        "/v1/notes", json={"path": "Familiar/m.md", "content": "v2"},
        headers={**auth_headers, "If-Match": f'"{first["etag"]}"'},
    )
    assert ok.status_code == 200 and ok.json()["created"] is False
    assert (tmp_vault / "Familiar/m.md").read_text() == "v2\n"


def test_save_note_at_path_repo_contract(tmp_vault):
    res = save_note_at_path("Familiar/x.md", "body")
    assert res == {"path": "Familiar/x.md", "created": True, "etag": compute_etag(b"body\n")}
```

Edit `ghostbrain/api/tests/test_routes_notes_upsert.py` line 11. The exact-dict assertion becomes:

```python
    assert {k: v for k, v in r.json().items() if k != "etag"} == {"path": "Familiar/briefings/2026-07-08.md", "created": True}
    assert len(r.json()["etag"]) == 16
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest ghostbrain/api/tests/test_note_write_path.py ghostbrain/api/tests/test_routes_notes_upsert.py -q`
Expected: FAIL. `test_hand_edited_frontmatter_survives_byte_for_byte` fails because the legacy writer re-sorts keys and drops the comment. `test_patch_body_with_stale_if_match_is_409_and_untouched` gets 200 instead of 409. There is a `KeyError: 'etag'`.

- [ ] **Step 3: Migrate the repo functions**

In `ghostbrain/api/repo/note.py`:
- Remove `import frontmatter`, `from datetime import datetime, timezone` and `_now_iso`.
- Change the `ghostbrain.vault_write` import to `from ghostbrain import vault_write` plus `from ghostbrain.vault_write import USER, Actor`.
- Replace both writers with:

```python
def save_note_body(
    rel_path: str, body: str, *, actor: Actor = USER, base_etag: str | None = None
) -> dict:
    """Rewrite only the markdown body; the frontmatter block's bytes are kept
    exactly (spec B1). ``updated`` is bumped only when the key already exists.
    A stale ``base_etag`` raises WriteConflict (→ 409)."""
    target = _resolve_safe(rel_path)
    if not target.exists() or not target.is_file():
        raise NoteNotFound(rel_path)
    res = vault_write.write(
        rel_path, body=body, actor=actor, base_etag=base_etag, reason="edited in the editor",
    )
    return {"path": rel_path, "updated": res.updated, "etag": res.etag}


def save_note_at_path(
    rel_path: str, content: str, *, actor: Actor = USER, base_etag: str | None = None
) -> dict:
    """Create or fully replace a note (plugin write-back). The caller owns the
    whole file; a trailing newline is ensured."""
    target = _resolve_safe(rel_path)
    created = not target.exists()
    res = vault_write.write(
        rel_path,
        content=content,
        op="create" if created else "modify",
        actor=actor,
        base_etag=base_etag,
        reason="plugin write-back",
    )
    return {"path": rel_path, "created": created, "etag": res.etag}
```

- [ ] **Step 4: Pass If-Match and actor through the routes**

In `ghostbrain/api/routes/notes.py`:
- Change `from fastapi import APIRouter, HTTPException, Query, status` to also import `Depends`.
- Add these imports:

```python
from ghostbrain.api.vault_http import if_match
from ghostbrain.vault_write import USER, plugin_actor

# PUT /v1/notes is the plugin write-back route. B2 replaces this with the id
# the main process stamps on the request; until then plugin writes are
# attributed generically.
_PLUGIN_WRITER = plugin_actor("unattributed")
```

Replace `upsert_note` and `patch_note_body` with the following. Keep the order-sensitivity comment above `/body` unchanged.

```python
@router.put("", status_code=status.HTTP_200_OK)
def upsert_note(req: UpsertNoteRequest, base_etag: str | None = Depends(if_match)) -> dict:
    """Create or replace a vault note at an explicit path (plugin write-back)."""
    if not req.content.strip():
        raise HTTPException(status_code=422, detail="content must not be empty")
    try:
        return save_note_at_path(req.path, req.content, actor=_PLUGIN_WRITER, base_etag=base_etag)
    except NoteInvalidPath as e:
        raise HTTPException(status_code=400, detail=str(e))
```

```python
@router.patch("/body")
def patch_note_body(req: UpdateNoteBodyRequest, base_etag: str | None = Depends(if_match)) -> dict:
    """Rewrite the markdown body of any vault note by path.

    Frontmatter bytes are preserved; `updated` bumped when the key exists.
    `If-Match` (from the GET's etag) → 409 when the file changed since.
    """
    if not req.body.strip():
        raise HTTPException(status_code=422, detail="body must not be empty")
    try:
        return save_note_body(req.path, req.body, actor=USER, base_etag=base_etag)
    except NoteInvalidPath as e:
        raise HTTPException(status_code=400, detail=str(e))
    except NoteNotFound:
        raise HTTPException(status_code=404, detail=f"Note not found: {req.path}")
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `python -m pytest ghostbrain/api/tests/test_note_write_path.py ghostbrain/api/tests/test_routes_notes_upsert.py ghostbrain/api/tests/test_repo_note_save.py ghostbrain/api/tests/test_routes_notes_body.py -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/api/repo/note.py ghostbrain/api/routes/notes.py ghostbrain/api/tests/test_note_write_path.py ghostbrain/api/tests/test_routes_notes_upsert.py
git commit -m "feat(api): note body/upsert saves go through vault_write with If-Match"
```

---

### Task 5: Migrate `notes_manual` jot writers and jot routes

**Files:**
- Modify: `ghostbrain/api/repo/notes_manual.py` (`write_inbox_jot`, `read_jot`, `update_jot_body`, `move_jot`, `mark_manual_review`, `set_frontmatter_fields`, `delete_jot`, `extract_photo_into_jot`, `_route_jot_core`)
- Modify: `ghostbrain/api/routes/notes.py` (`patch_note`, `route_note`, `delete_note`)
- Create: `ghostbrain/api/tests/test_notes_manual_write_path.py`

**Interfaces:**
- Consumes: `vault_write.write`, `vault_write.read`, `DELETE_FIELD`, `USER`, `ASSISTANT`, `worker_actor`, `if_match`.
- Produces:
  - `ROUTER_ACTOR: Actor = "worker:jot-router"`.
  - `write_inbox_jot(body, *, captured_at=None, extra=None, actor=USER) -> {"id", "path"}`.
  - `read_jot(jot_id) -> {..., "etag"}`.
  - `update_jot_body(jot_id, new_body, *, actor=USER, base_etag=None) -> {"id", "path", "updated", "etag"}`.
  - `move_jot(..., actor=USER) -> {"id", "path", "context", "project", "etag"}`.
  - `mark_manual_review(jot_id, reasoning, *, actor=ROUTER_ACTOR)`.
  - `set_frontmatter_fields(jot_id, fields, *, actor=USER) -> {"id", "path", "etag"}`.
  - `delete_jot(jot_id, *, actor=USER)`.
  - `extract_photo_into_jot` adds `"etag"` on success.

- [ ] **Step 1: Write the failing tests**

Create `ghostbrain/api/tests/test_notes_manual_write_path.py`:

```python
"""Jot writers on the vault write path: golden parity with the legacy
frontmatter.dumps writers, hand-edit preservation, If-Match, actors."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import frontmatter
import pytest

from ghostbrain import vault_write
from ghostbrain.api.repo import notes_manual
from ghostbrain.api.repo.notes_manual import (
    extract_tags,
    mark_manual_review,
    move_jot,
    read_jot,
    set_frontmatter_fields,
    update_jot_body,
    write_inbox_jot,
)
from ghostbrain.vault_write import compute_etag

NOW = "2026-10-09T10:00:00+00:00"
WHEN = datetime(2026, 5, 14, 9, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _frozen(monkeypatch, tmp_vault):
    monkeypatch.setattr(notes_manual, "_now_iso", lambda: NOW)
    monkeypatch.setattr(vault_write.writer, "_now_iso", lambda: NOW)
    (tmp_vault / "00-inbox" / "raw" / "manual").mkdir(parents=True, exist_ok=True)


def _legacy(text: str, mutate) -> str:
    post = frontmatter.loads(text)
    mutate(post)
    return frontmatter.dumps(post) + "\n"


def test_write_inbox_jot_bytes_unchanged(tmp_vault):
    rec = write_inbox_jot("hello #a", captured_at=WHEN)
    text = (tmp_vault / rec["path"]).read_text()
    expected = frontmatter.dumps(frontmatter.Post(
        "hello #a", id=rec["id"], type="note", source="manual", context=None,
        created=WHEN.isoformat(), updated=WHEN.isoformat(), ingestedAt=NOW,
        routingStatus="pending", routingConfidence=None, routingMethod=None,
        routingReasoning=None, tags=["a"],
    )) + "\n"
    assert text == expected


def test_update_jot_body_golden(tmp_vault):
    rec = write_inbox_jot("original", captured_at=WHEN)
    p = tmp_vault / rec["path"]
    before = p.read_text()

    def legacy(post):
        post.content = "new body #x"
        post["updated"] = NOW
        post["tags"] = extract_tags("new body #x")

    res = update_jot_body(rec["id"], "new body #x")
    assert p.read_text() == _legacy(before, legacy)
    assert res["etag"] == compute_etag(p.read_bytes())
    assert res["updated"] == NOW


def test_mark_manual_review_golden(tmp_vault):
    rec = write_inbox_jot("ambiguous", captured_at=WHEN)
    p = tmp_vault / rec["path"]
    before = p.read_text()

    def legacy(post):
        post["routingStatus"] = "manual_review"
        post["routingReasoning"] = "too vague"
        post["updated"] = NOW

    mark_manual_review(rec["id"], "too vague")
    assert p.read_text() == _legacy(before, legacy)


def test_move_jot_without_project_golden(tmp_vault):
    rec = write_inbox_jot("file me", captured_at=WHEN)
    before = (tmp_vault / rec["path"]).read_text()

    def legacy(post):
        post["context"] = "work"
        post["routingStatus"] = "routed"
        post["routingConfidence"] = 0.9
        post["routingMethod"] = "llm"
        post["routingReasoning"] = "matches work"
        post["updated"] = NOW

    res = move_jot(rec["id"], to_context="work", confidence=0.9, method="llm", reasoning="matches work")
    assert not (tmp_vault / rec["path"]).exists()
    assert (tmp_vault / res["path"]).read_text() == _legacy(before, legacy)
    assert res["etag"] == compute_etag((tmp_vault / res["path"]).read_bytes())


def test_move_jot_with_project_appends_key_and_keeps_other_lines(tmp_vault):
    rec = write_inbox_jot("project jot", captured_at=WHEN)
    res = move_jot(rec["id"], to_context="work", to_project="alpha", confidence=1.0,
                   method="user", reasoning="manual re-route by user")
    text = (tmp_vault / res["path"]).read_text()
    assert res["path"] == f"20-contexts/work/projects/alpha/{rec['id']}.md"
    assert text.split("---\n")[1].endswith("project: alpha\n")
    assert frontmatter.loads(text)["project"] == "alpha"


def test_set_frontmatter_fields_appends_new_keys_and_keeps_existing_lines(tmp_vault):
    rec = write_inbox_jot("export me", captured_at=WHEN)
    p = tmp_vault / rec["path"]
    before_lines = p.read_text().split("---\n")[1].splitlines()
    set_frontmatter_fields(rec["id"], {"confluence_page_id": "123", "confluence_space": "ENG"})
    after_lines = p.read_text().split("---\n")[1].splitlines()
    assert after_lines[-2:] == ["confluence_page_id: '123'", "confluence_space: ENG"]
    unchanged = [l for l in before_lines if not l.startswith("updated:")]
    assert all(l in after_lines for l in unchanged)
    assert f"updated: '{NOW}'" in after_lines


def test_hand_edited_jot_keeps_comment_and_key_order(tmp_vault):
    jot_id = "manual-20260101T000000-hand"
    p = tmp_vault / "00-inbox/raw/manual" / f"{jot_id}.md"
    original = (
        "---\n"
        "# my jot\n"
        f"id: {jot_id}\n"
        "source: manual\n"
        'title: "Hand: written"\n'
        "updated: '2026-01-01T00:00:00+00:00'\n"
        "tags: []\n"
        "---\n"
        "\n"
        "hello\n"
    )
    p.write_text(original)
    update_jot_body(jot_id, "hello #y")
    assert p.read_text() == original.replace(
        "'2026-01-01T00:00:00+00:00'", f"'{NOW}'"
    ).replace("tags: []\n", "tags:\n- y\n").replace("\nhello\n", "\nhello #y\n")


def test_read_jot_returns_etag(tmp_vault):
    rec = write_inbox_jot("read me", captured_at=WHEN)
    assert read_jot(rec["id"])["etag"] == compute_etag((tmp_vault / rec["path"]).read_bytes())


def test_patch_jot_if_match(client, tmp_vault, auth_headers):
    rec = write_inbox_jot("original", captured_at=WHEN)
    etag = compute_etag((tmp_vault / rec["path"]).read_bytes())
    stale = client.patch(
        f"/v1/notes/{rec['id']}", json={"body": "x"},
        headers={**auth_headers, "If-Match": '"0000000000000000"'},
    )
    assert stale.status_code == 409
    ok = client.patch(
        f"/v1/notes/{rec['id']}", json={"body": "x"},
        headers={**auth_headers, "If-Match": f'"{etag}"'},
    )
    assert ok.status_code == 200
    assert ok.json()["etag"] == compute_etag((tmp_vault / ok.json()["path"]).read_bytes())


def test_route_response_has_etag(client, tmp_vault, auth_headers):
    rec = write_inbox_jot("route me", captured_at=WHEN)
    r = client.post(f"/v1/notes/{rec['id']}/route", json={"context": "work"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["etag"] == compute_etag((tmp_vault / r.json()["path"]).read_bytes())


def test_actors_threaded(monkeypatch, tmp_vault):
    seen: list[tuple[str, str]] = []
    real = vault_write.write

    def spy(rel_path, **kw):
        seen.append((kw.get("op", "modify"), kw["actor"]))
        return real(rel_path, **kw)

    monkeypatch.setattr(vault_write, "write", spy)
    from ghostbrain.worker.router import RoutingDecision

    monkeypatch.setattr(
        notes_manual, "route_event",
        lambda event, **kw: RoutingDecision(context="work", confidence=0.9, reasoning="r",
                                            method="llm", secondary_contexts=[]),
    )
    rec = write_inbox_jot("auto", captured_at=WHEN)
    notes_manual.route_existing_jot(rec["id"])
    assert seen == [("create", "user"), ("move", "worker:jot-router")]


def test_extract_photo_uses_assistant_actor_and_returns_etag(monkeypatch, tmp_vault):
    rec = write_inbox_jot("shot", captured_at=WHEN)
    monkeypatch.setattr(notes_manual, "llm_run", lambda *a, **kw: SimpleNamespace(text="board text"))
    actors: list[str] = []
    real = vault_write.write
    monkeypatch.setattr(vault_write, "write", lambda rel, **kw: actors.append(kw["actor"]) or real(rel, **kw))
    out = notes_manual.extract_photo_into_jot(rec["id"], "90-meta/assets/jots/x.jpg")
    assert out["extracted"] is True
    assert actors == ["assistant"]
    assert out["etag"] == compute_etag((tmp_vault / out["path"]).read_bytes())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest ghostbrain/api/tests/test_notes_manual_write_path.py -q`
Expected: FAIL with `KeyError: 'etag'`, and `test_hand_edited_jot_keeps_comment_and_key_order` fails because legacy re-sorts and drops the comment. The spy tests also fail because `vault_write.write` is never called.

- [ ] **Step 3: Migrate the writers**

In `ghostbrain/api/repo/notes_manual.py`, directly after the line `from ghostbrain.llm.client import LLMError  # noqa: E402`, add:

```python
from ghostbrain import vault_write  # noqa: E402
from ghostbrain.vault_write import ASSISTANT, DELETE_FIELD, USER, Actor, worker_actor  # noqa: E402

# LLM auto-routing files jots on the user's behalf. B2 decides whether this
# actor is listed on the Changes screen.
ROUTER_ACTOR: Actor = worker_actor("jot-router")
```

Replace the following functions entirely:

```python
def write_inbox_jot(
    body: str, *, captured_at: "datetime | None" = None, extra: dict | None = None,
    actor: Actor = USER,
) -> dict:
    """Write a new jot to the inbox folder. Returns {id, path}."""
    captured_at = captured_at or datetime.now(timezone.utc)
    first_line = title_from_body(body)
    jot_id = make_jot_id(first_line, when=captured_at)
    target = _inbox_dir() / f"{jot_id}.md"
    if target.exists():
        jot_id = f"{jot_id}-{_random_suffix()}"
        target = _inbox_dir() / f"{jot_id}.md"
        if target.exists():
            raise JotIdConflict(jot_id)
    post = frontmatter.Post(
        body,
        id=jot_id,
        type="note",
        source="manual",
        context=None,
        created=captured_at.isoformat(),
        updated=captured_at.isoformat(),
        ingestedAt=_now_iso(),
        routingStatus="pending",
        routingConfidence=None,
        routingMethod=None,
        routingReasoning=None,
        tags=extract_tags(body),
    )
    if extra:
        for k, v in extra.items():
            post[k] = v
    try:
        vault_write.write(
            _vault_rel(target), content=frontmatter.dumps(post) + "\n", op="create",
            actor=actor, reason="new jot",
        )
    except vault_write.WriteConflict:
        raise JotIdConflict(jot_id) from None
    log.info("wrote inbox jot id=%s", jot_id)
    return {"id": jot_id, "path": _vault_rel(target)}


def read_jot(jot_id: str) -> dict:
    path = _find_file(jot_id)
    snap = vault_write.read(_vault_rel(path), suffixes=(".md",))
    fm = {str(k): _jsonable(v) for k, v in snap.metadata().items()}
    return {
        "path": _vault_rel(path),
        "title": title_from_body(snap.body or fm.get("id") or ""),
        "body": snap.body,
        "frontmatter": fm,
        "etag": snap.etag,
    }


def update_jot_body(
    jot_id: str, new_body: str, *, actor: Actor = USER, base_etag: str | None = None
) -> dict:
    path = _find_file(jot_id)
    now = _now_iso()
    res = vault_write.write(
        _vault_rel(path),
        body=new_body,
        fields={"updated": now, "tags": extract_tags(new_body)},
        actor=actor,
        base_etag=base_etag,
        reason="edited jot",
    )
    return {"id": jot_id, "path": res.path, "updated": now, "etag": res.etag}


def move_jot(
    jot_id: str,
    *,
    to_context: str,
    to_project: str | None = None,
    confidence: float,
    method: str,
    reasoning: str,
    actor: Actor = USER,
) -> dict:
    src = _find_file(jot_id)
    if to_project:
        _safe_component(to_context)
        _safe_component(to_project)
        dst_dir = _guard_inside_vault(
            _vault() / PROJECT_NOTES_TEMPLATE.format(context=to_context, project=to_project)
        )
        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / f"{jot_id}.md"
    else:
        dst = _guard_inside_vault(_context_dir(to_context) / f"{jot_id}.md")
    if src.resolve() == dst:
        return {"id": jot_id, "path": _vault_rel(dst), "context": to_context, "project": to_project}
    fields: dict[str, Any] = {
        "context": to_context,
        "routingStatus": "routed",
        "routingConfidence": confidence,
        "routingMethod": method,
        "routingReasoning": reasoning,
        "updated": _now_iso(),
        "project": to_project if to_project else DELETE_FIELD,
    }
    log.info("moving jot id=%s: %s -> %s", jot_id, src, dst)
    res = vault_write.write(
        _vault_rel(src), op="move", dest=_vault_rel(dst), fields=fields,
        actor=actor, reason=f"filed to {to_context}",
    )
    log.info("moved jot id=%s -> %s (project=%s)", jot_id, to_context, to_project)
    return {
        "id": jot_id, "path": res.path, "context": to_context, "project": to_project,
        "etag": res.etag,
    }


def mark_manual_review(jot_id: str, reasoning: str, *, actor: Actor = ROUTER_ACTOR) -> dict:
    """Keep the file at inbox path; set routingStatus=manual_review."""
    path = _find_file(jot_id)
    res = vault_write.write(
        _vault_rel(path),
        fields={"routingStatus": "manual_review", "routingReasoning": reasoning, "updated": _now_iso()},
        actor=actor,
        reason="kept for manual review",
    )
    return {"id": jot_id, "path": res.path, "routingStatus": "manual_review"}


def set_frontmatter_fields(jot_id: str, fields: dict[str, Any], *, actor: Actor = USER) -> dict:
    """Stamp frontmatter fields without touching the body (line-level edits)."""
    path = _find_file(jot_id)
    res = vault_write.write(
        _vault_rel(path), fields={**fields, "updated": _now_iso()}, actor=actor,
        reason="updated jot fields",
    )
    return {"id": jot_id, "path": res.path, "etag": res.etag}


def delete_jot(jot_id: str, *, actor: Actor = USER) -> None:
    path = _find_file(jot_id)
    vault_write.write(_vault_rel(path), op="delete", actor=actor, reason="deleted jot")
```

In `extract_photo_into_jot`, replace the last two lines:

```python
    saved = update_jot_body(jot_id, new_body, actor=ASSISTANT)
    return {"id": jot_id, "path": saved["path"], "body": new_body, "extracted": True, "etag": saved["etag"]}
```

In `_route_jot_core`, change the `move_jot(` call to pass `actor=ROUTER_ACTOR`:

```python
        moved = move_jot(
            jot_id,
            to_context=decision.context,
            to_project=decision.project,
            confidence=decision.confidence,
            method=decision.method,
            reasoning=decision.reasoning,
            actor=ROUTER_ACTOR,
        )
```

`_mark_review_safe` needs no change because `mark_manual_review` already defaults to `ROUTER_ACTOR`. `chat_export.py` and `export_confluence.py` also need no change, because the defaults (`USER`) are right for user-triggered exports.

- [ ] **Step 4: Routes: If-Match on the jot PATCH, actors on route and delete**

In `ghostbrain/api/routes/notes.py`, replace `patch_note`:

```python
@router.patch("/{jot_id}")
def patch_note(
    req: UpdateNoteRequest,
    jot_id: str = PathParam(..., min_length=8, max_length=128),
    base_etag: str | None = Depends(if_match),
) -> dict:
    """Update the body (and re-derive tags) of an existing jot. `If-Match` →
    409 when the jot changed since the editor read it."""
    body = req.body
    if not body.strip():
        raise HTTPException(status_code=422, detail="body must not be empty")
    try:
        return update_jot_body(jot_id, body, actor=USER, base_etag=base_etag)
    except JotNotFound:
        raise HTTPException(status_code=404, detail=f"Jot not found: {jot_id}")
```

In `route_note`, add `actor=USER,` as the last keyword in the `move_jot(...)` call. In `delete_note`, change `delete_jot(jot_id)` to `delete_jot(jot_id, actor=USER)`.

- [ ] **Step 5: Run the tests to verify they pass, plus every jot suite**

Run: `python -m pytest ghostbrain/api/tests/test_notes_manual_write_path.py ghostbrain/api/tests/ tests/test_chat_export.py -q`
Expected: all pass. If a golden test differs only in YAML wrapping, check that `text._dump` uses PyYAML defaults with the real key (Task 1). Don't loosen the test.

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/api/repo/notes_manual.py ghostbrain/api/routes/notes.py ghostbrain/api/tests/test_notes_manual_write_path.py
git commit -m "feat(api): jot create/edit/route/review/stamp/delete go through vault_write"
```

---

### Task 6: Migrate the create-only writers (generated docs via MCP, chat attachments)

**Files:**
- Modify: `ghostbrain/api/repo/generated_docs.py` (`write_doc`)
- Modify: `ghostbrain/api/repo/chat_attachments.py` (`save_attachment`, note write only)
- Create: `ghostbrain/api/tests/test_create_writers_write_path.py`

**Interfaces:**
- Consumes: `vault_write.write_new`, `MCP`, `USER`.
- Produces: unchanged return shapes. `write_doc` returns `{"path", "title"}` and `save_attachment` returns `{"path", "title", "kind"}`. The only difference is that a name collision now gets a `-2` suffix instead of overwriting.

- [ ] **Step 1: Write the failing tests**

Create `ghostbrain/api/tests/test_create_writers_write_path.py`:

```python
"""Create-only writers on the vault write path: never overwrite, actors."""
from __future__ import annotations

from datetime import datetime, timezone

from ghostbrain import vault_write
from ghostbrain.api.repo import chat_attachments, generated_docs

HTML = "<!doctype html><html><body><h1>Q3</h1></body></html>"


class _Frozen(datetime):
    @classmethod
    def now(cls, tz=None):  # noqa: D401 — fixed clock
        return datetime(2026, 10, 9, 10, 0, 0, tzinfo=timezone.utc)


def test_same_second_same_title_docs_do_not_overwrite(tmp_vault, monkeypatch):
    monkeypatch.setattr(generated_docs, "datetime", _Frozen)
    a = generated_docs.write_doc("Q3 One-Pager", HTML)
    b = generated_docs.write_doc("Q3 One-Pager", HTML.replace("Q3", "Q4"))
    assert a["path"] == "20-contexts/generated-docs/20261009T100000-q3-one-pager.html"
    assert b["path"] == "20-contexts/generated-docs/20261009T100000-q3-one-pager-2.html"
    assert (tmp_vault / a["path"]).read_text() == HTML  # verbatim, untouched


def test_write_doc_is_attributed_to_mcp(tmp_vault, monkeypatch):
    actors: list[str] = []
    real = vault_write.write_new
    monkeypatch.setattr(
        vault_write, "write_new",
        lambda rel, content, **kw: actors.append(kw["actor"]) or real(rel, content, **kw),
    )
    generated_docs.write_doc("t", HTML)
    assert actors == ["mcp"]


def test_attachment_note_collision_does_not_overwrite(tmp_vault, monkeypatch):
    monkeypatch.setattr(chat_attachments, "datetime", _Frozen)
    a = chat_attachments.save_attachment("c1", "notes.txt", "text/plain", b"first file")
    b = chat_attachments.save_attachment("c1", "notes.txt", "text/plain", b"second file")
    assert a["path"] != b["path"]
    assert b["path"].endswith("-notes-2.md")
    assert "first file" in (tmp_vault / a["path"]).read_text()


def test_attachment_note_bytes_and_actor(tmp_vault, monkeypatch):
    actors: list[str] = []
    real = vault_write.write_new
    monkeypatch.setattr(
        vault_write, "write_new",
        lambda rel, content, **kw: actors.append(kw["actor"]) or real(rel, content, **kw),
    )
    res = chat_attachments.save_attachment("c1", "plan.md", "text/markdown", b"# Plan\n")
    text = (tmp_vault / res["path"]).read_text()
    assert text.startswith("---\nid: ") and text.endswith("\n\n# Plan\n")
    assert actors == ["user"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python -m pytest ghostbrain/api/tests/test_create_writers_write_path.py -q`
Expected: FAIL. `b["path"]` equals `a["path"]` (an overwrite), and the actor spies record nothing.

- [ ] **Step 3: Migrate**

In `ghostbrain/api/repo/generated_docs.py`, add `from ghostbrain import vault_write` and `from ghostbrain.vault_write import MCP`. Then replace the body of `write_doc` after the validation checks:

```python
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    res = vault_write.write_new(
        f"{GENERATED_DOCS_DIR_REL}/{stamp}-{_slug(title)}.html",
        html,
        actor=MCP,
        reason=f"generated doc: {title}",
    )
    return {"path": res.path, "title": title}
```

`from ghostbrain.paths import vault_path` is now unused in `generated_docs.py`, so remove it.

In `ghostbrain/api/repo/chat_attachments.py`, add `from ghostbrain import vault_write` and `from ghostbrain.vault_write import USER`. Then, in `save_attachment`, replace these two lines:

```python
    note_path = target_dir / f"{stamp}-{_slug(filename)}.md"
    note_path.write_text(_render(front, body), encoding="utf-8")
```

with:

```python
    res = vault_write.write_new(
        f"{ATTACHMENTS_DIR_REL}/{stamp}-{_slug(filename)}.md",
        _render(front, body),
        actor=USER,
        reason=f"chat attachment: {filename}",
    )
    note_path = vault_path() / res.path
```

The image asset `write_bytes` in `_image_body` stays as it is. It is binary and content-addressed, and is listed as deferred.

- [ ] **Step 4: Run the tests to verify they pass, plus the existing suites**

Run: `python -m pytest ghostbrain/api/tests/test_create_writers_write_path.py ghostbrain/api/tests/test_generated_docs.py ghostbrain/api/tests/test_chat_attachments.py tests/test_mcp_tools.py tests/test_docs_routes.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/generated_docs.py ghostbrain/api/repo/chat_attachments.py ghostbrain/api/tests/test_create_writers_write_path.py
git commit -m "feat(api): generated docs (mcp) and chat attachments create via vault_write, never overwrite"
```

---

### Task 7: Desktop transport: If-Match through IPC, forwarder, client and hooks

**Files:**
- Modify: `desktop/src/main/api-forwarder.ts`
- Modify: `desktop/src/main/index.ts:357-372` (`gb:api:request` handler) and its import at line 11
- Modify: `desktop/src/preload/index.ts:20-23`
- Modify: `desktop/src/shared/types.ts` (`api.request` signature, ~line 62)
- Modify: `desktop/src/shared/api-types.ts` (`Note`, `UpdateNoteBodyResponse`, new `UpdateJotResponse`, `ExtractPhotoResponse`)
- Modify: `desktop/src/renderer/lib/api/client.ts` (`patch`)
- Modify: `desktop/src/renderer/lib/api/hooks.ts` (`useUpdateJot`, `useUpdateNoteByPath`)
- Modify: `desktop/src/main/__tests__/api-forwarder.test.ts`
- Create: `desktop/src/renderer/__tests__/api-client.test.ts`

**Interfaces:**
- Consumes: the server contract from Tasks 3–5: a 16-hex `etag` and 409 on a stale `If-Match`.
- Produces:
  - `requestHeadersFrom(opts: unknown): Record<string, string>`
  - `forward(sidecar, method, path, body?, timeoutMs = 300_000, extraHeaders: Record<string, string> = {})`
  - `window.gb.api.request(method, path, body?, opts?: { ifMatch?: string })`
  - `patch<T>(path, body?, opts?: { ifMatch?: string | null }): Promise<T>`, which throws `ApiError` with `.status`
  - `useUpdateJot()` with vars `{ id, body, ifMatch? }` returning `UpdateJotResponse`
  - `useUpdateNoteByPath()` with vars `{ path, body, ifMatch? }` returning `UpdateNoteBodyResponse`
  - `Note.etag?: string | null`

- [ ] **Step 1: Write the failing tests**

Append to `desktop/src/main/__tests__/api-forwarder.test.ts`. Extend the import to `import { forward, isAllowedMethod, isSafeApiPath, requestHeadersFrom } from '../api-forwarder';`, then add:

```ts
describe('If-Match passthrough', () => {
  it('sends extra headers', async () => {
    await forward(sidecar(), 'PATCH', '/v1/notes/body', { path: 'a.md', body: 'x' }, undefined, {
      'If-Match': '"0123456789abcdef"',
    });
    expect(lastReq.headers['if-match']).toBe('"0123456789abcdef"');
  });

  it('extra headers can never override Authorization', async () => {
    await forward(sidecar(), 'GET', '/v1/echo', undefined, undefined, { Authorization: 'Bearer evil' });
    expect(lastReq.headers.authorization).toBe('Bearer test-token');
  });

  it('requestHeadersFrom maps a 16-hex etag to a quoted If-Match', () => {
    expect(requestHeadersFrom({ ifMatch: '0123456789abcdef' })).toEqual({
      'If-Match': '"0123456789abcdef"',
    });
  });

  it('requestHeadersFrom drops everything else', () => {
    expect(requestHeadersFrom(undefined)).toEqual({});
    expect(requestHeadersFrom(null)).toEqual({});
    expect(requestHeadersFrom({ ifMatch: 'x\r\nX-Evil: 1' })).toEqual({});
    expect(requestHeadersFrom({ ifMatch: 'ABCDEF0123456789' })).toEqual({});
    expect(requestHeadersFrom({ authorization: 'Bearer x' })).toEqual({});
  });
});
```

Create `desktop/src/renderer/__tests__/api-client.test.ts`:

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { ApiError, patch } from '../lib/api/client';

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  window.gb = { ...window.gb, api: { request: apiRequest } } as typeof window.gb;
});

describe('patch', () => {
  it('passes ifMatch as the 4th bridge argument', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: { etag: 'bbbbbbbbbbbbbbbb' } });
    await patch('/v1/notes/body', { path: 'a.md', body: 'x' }, { ifMatch: 'aaaaaaaaaaaaaaaa' });
    expect(apiRequest).toHaveBeenCalledWith(
      'PATCH',
      '/v1/notes/body',
      { path: 'a.md', body: 'x' },
      { ifMatch: 'aaaaaaaaaaaaaaaa' },
    );
  });

  it('omits the 4th argument when there is no etag', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: {} });
    await patch('/v1/notes/body', { path: 'a.md', body: 'x' }, { ifMatch: null });
    expect(apiRequest.mock.calls[0]).toHaveLength(3);
  });

  it('throws ApiError carrying the status', async () => {
    apiRequest.mockResolvedValue({ ok: false, error: 'note changed', status: 409 });
    const err = await patch('/v1/notes/x', { body: 'x' }).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd desktop && npx vitest run src/main/__tests__/api-forwarder.test.ts src/renderer/__tests__/api-client.test.ts`
Expected: FAIL. `requestHeadersFrom` is not exported, the `if-match` header is undefined, and `patch` throws a plain `Error`.

- [ ] **Step 3: Implement the forwarder and the IPC plumbing**

In `desktop/src/main/api-forwarder.ts`, add above `forward`:

```ts
const ETAG_RE = /^[0-9a-f]{16}$/;

/** Headers the renderer may ask the forwarder to set. B1: only If-Match
 * (spec B §7), and only a well-formed 16-hex etag. B2 adds the actor
 * header here. Anything else is dropped. */
export function requestHeadersFrom(opts: unknown): Record<string, string> {
  if (!opts || typeof opts !== 'object') return {};
  const ifMatch = (opts as { ifMatch?: unknown }).ifMatch;
  if (typeof ifMatch === 'string' && ETAG_RE.test(ifMatch)) {
    return { 'If-Match': `"${ifMatch}"` };
  }
  return {};
}
```

Change the `forward` signature and its headers object:

```ts
export async function forward<T = unknown>(
  sidecar: Sidecar,
  method: HttpMethod,
  path: string,
  body?: unknown,
  timeoutMs = 300_000,
  extraHeaders: Record<string, string> = {},
): Promise<ApiResult<T>> {
```

```ts
        headers: {
          ...extraHeaders,
          ...(hasBody ? { 'Content-Type': 'application/json' } : {}),
          Authorization: `Bearer ${info.token}`,
        },
```

In `desktop/src/main/index.ts`, change line 11 to `import { forward, isAllowedMethod, requestHeadersFrom } from './api-forwarder';`. Then replace the `gb:api:request` handler:

```ts
ipcMain.handle(
  'gb:api:request',
  async (_e, method: unknown, path: unknown, body: unknown, opts: unknown) => {
    if (typeof method !== 'string' || typeof path !== 'string') {
      return { ok: false, error: 'Invalid request shape' };
    }
    const m = method.toUpperCase();
    if (!isAllowedMethod(m)) {
      return { ok: false, error: 'Method not allowed' };
    }
    if (!path.startsWith('/v1/')) {
      return { ok: false, error: 'Path not allowed (must start with /v1/)' };
    }
    if (DEMO) return handleDemoApi(m, path, body);
    return forward(sidecar, m, path, body, undefined, requestHeadersFrom(opts));
  },
);
```

In `desktop/src/preload/index.ts`:

```ts
  api: {
    request: (method, path, body, opts) =>
      ipcRenderer.invoke('gb:api:request', method, path, body, opts),
  },
```

In `desktop/src/shared/types.ts`, change the `api.request` signature to:

```ts
  api: {
    request<T = unknown>(
      method: HttpMethod,
      path: string,
      body?: unknown,
      opts?: { ifMatch?: string },
    ): Promise<
      | { ok: true; data: T }
      | { ok: false; error: string; status?: number }
    >;
  };
```

In `desktop/src/shared/api-types.ts`, make these changes:

```ts
export interface Note {
  path: string;
  title: string;
  body: string;
  frontmatter: Record<string, unknown>;
  /** sha256(file bytes)[:16] — send back as If-Match on the next save. */
  etag?: string | null;
}

export interface UpdateNoteBodyResponse {
  path: string;
  updated: string | null;
  etag: string;
}

export interface UpdateJotResponse {
  id: string;
  path: string;
  updated: string;
  etag: string;
}
```

Add `etag?: string;` to `ExtractPhotoResponse`.

- [ ] **Step 4: Update the client and hooks**

In `desktop/src/renderer/lib/api/client.ts`, replace `patch`:

```ts
export async function patch<T>(
  path: string,
  body?: unknown,
  opts?: { ifMatch?: string | null },
): Promise<T> {
  // Only send the 4th bridge arg when there is an etag — keeps the common
  // call shape (and existing assertions on it) unchanged.
  const result = opts?.ifMatch
    ? await window.gb.api.request<T>('PATCH', path, body, { ifMatch: opts.ifMatch })
    : await window.gb.api.request<T>('PATCH', path, body);
  if (!result.ok) throw new ApiError(result.error, result.status);
  return result.data;
}
```

In `desktop/src/renderer/lib/api/hooks.ts`, add `UpdateJotResponse` to the `api-types` import and replace the two mutations:

```ts
export function useUpdateJot() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { id: string; body: string; ifMatch?: string | null }) =>
      patch<UpdateJotResponse>(
        `/v1/notes/${encodeURIComponent(vars.id)}`,
        { body: vars.body },
        { ifMatch: vars.ifMatch },
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: JOTS_KEY });
      qc.invalidateQueries({ queryKey: ['note-by-path'] });
    },
  });
}
```

```ts
export function useUpdateNoteByPath() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: UpdateNoteBodyRequest & { ifMatch?: string | null }) =>
      patch<UpdateNoteBodyResponse>(
        '/v1/notes/body',
        { path: vars.path, body: vars.body },
        { ifMatch: vars.ifMatch },
      ),
    onSuccess: () => {
      // Both caches read GET /v1/notes?path= — ['note'] (useNote/NoteView)
      // and ['note-by-path'] (useJot/jots screen).
      qc.invalidateQueries({ queryKey: ['note'] });
      qc.invalidateQueries({ queryKey: ['note-by-path'] });
    },
  });
}
```

- [ ] **Step 5: Run the tests and gates**

Run: `cd desktop && npx vitest run src/main/__tests__/api-forwarder.test.ts src/renderer/__tests__/api-client.test.ts src/renderer/__tests__/NoteView.test.tsx src/renderer/__tests__/jots.test.tsx && npm run typecheck && npx eslint --max-warnings 0 src/main/api-forwarder.ts src/main/index.ts src/preload/index.ts src/shared/types.ts src/shared/api-types.ts src/renderer/lib/api/client.ts src/renderer/lib/api/hooks.ts src/renderer/__tests__/api-client.test.ts src/main/__tests__/api-forwarder.test.ts`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add desktop/src/main/api-forwarder.ts desktop/src/main/index.ts desktop/src/preload/index.ts desktop/src/shared/types.ts desktop/src/shared/api-types.ts desktop/src/renderer/lib/api/client.ts desktop/src/renderer/lib/api/hooks.ts desktop/src/main/__tests__/api-forwarder.test.ts desktop/src/renderer/__tests__/api-client.test.ts
git commit -m "feat(desktop): carry If-Match from renderer through IPC to the sidecar"
```

---

### Task 8: Desktop logic: line diff and the `useGuardedSave` state machine

**Files:**
- Create: `desktop/src/renderer/lib/line-diff.ts`
- Create: `desktop/src/renderer/lib/use-guarded-save.ts`
- Create: `desktop/src/renderer/__tests__/line-diff.test.ts`
- Create: `desktop/src/renderer/__tests__/use-guarded-save.test.tsx`

**Interfaces:**
- Consumes: `ApiError` from `lib/api/client` (Task 7).
- Produces:

```ts
// line-diff.ts
export type DiffLine = { kind: 'same' | 'add' | 'del'; text: string };
export function lineDiff(oldText: string, newText: string): DiffLine[];

// use-guarded-save.ts
export interface SaveTarget {
  send: (body: string, ifMatch: string | null) => Promise<{ etag?: string | null }>;
  fetchLatest: () => Promise<{ body: string; etag?: string | null }>;
}
export interface Conflict { mine: string; theirs: string; theirsEtag: string | null }
export interface GuardedSave {
  save: (body: string) => void;
  conflict: Conflict | null;
  resolving: boolean;
  keepMine: () => Promise<void>;
  keepTheirs: () => Conflict | null;
  adopt: (etag: string | null, body: string) => void;
}
export function sameBody(a: string, b: string): boolean;
export function useGuardedSave(
  initial: { body: string; etag: string | null },
  target: SaveTarget,
  onError?: (err: Error) => void,
): GuardedSave;
```

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/renderer/__tests__/line-diff.test.ts`:

```ts
import { describe, it, expect } from 'vitest';
import { lineDiff } from '../lib/line-diff';

describe('lineDiff', () => {
  it('marks unchanged, removed and added lines', () => {
    expect(lineDiff('a\nb\nc', 'a\nx\nc')).toEqual([
      { kind: 'same', text: 'a' },
      { kind: 'del', text: 'b' },
      { kind: 'add', text: 'x' },
      { kind: 'same', text: 'c' },
    ]);
  });

  it('treats CRLF like LF', () => {
    expect(lineDiff('a\r\nb', 'a\nb').every((l) => l.kind === 'same')).toBe(true);
  });

  it('handles empty sides', () => {
    expect(lineDiff('', 'x')).toEqual([
      { kind: 'del', text: '' },
      { kind: 'add', text: 'x' },
    ]);
  });

  it('falls back to block replace for huge inputs instead of freezing', () => {
    const big = Array.from({ length: 3000 }, (_, i) => `line ${i}`).join('\n');
    const out = lineDiff(big, big + '\nmore');
    expect(out.length).toBeGreaterThan(0);
  });
});
```

Create `desktop/src/renderer/__tests__/use-guarded-save.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useGuardedSave } from '../lib/use-guarded-save';
import { ApiError } from '../lib/api/client';

const conflict = () => new ApiError('note changed since you read it — re-read and retry', 409);

function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
}

describe('useGuardedSave', () => {
  it('sends the initial etag and chains the returned etag', async () => {
    const send = vi.fn().mockResolvedValueOnce({ etag: 'e2' }).mockResolvedValueOnce({ etag: 'e3' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest: vi.fn() }),
    );
    act(() => result.current.save('b'));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(1));
    await act(async () => {});
    act(() => result.current.save('c'));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls).toEqual([['b', 'e1'], ['c', 'e2']]);
  });

  it('queues overlapping saves and chains etags', async () => {
    const first = deferred<{ etag: string }>();
    const send = vi.fn().mockReturnValueOnce(first.promise).mockResolvedValueOnce({ etag: 'e3' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest: vi.fn() }),
    );
    act(() => {
      result.current.save('b');
      result.current.save('c');
      result.current.save('d');
    });
    expect(send).toHaveBeenCalledTimes(1);
    await act(async () => first.resolve({ etag: 'e2' }));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls).toEqual([['b', 'e1'], ['d', 'e2']]);
  });

  it('a body conflict pauses autosave and keeps the latest text as mine', async () => {
    const send = vi.fn().mockRejectedValueOnce(conflict());
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'theirs', etag: 'e9' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest }),
    );
    act(() => result.current.save('b'));
    await waitFor(() => expect(result.current.conflict).not.toBeNull());
    expect(result.current.conflict).toEqual({ mine: 'b', theirs: 'theirs', theirsEtag: 'e9' });
    act(() => result.current.save('b2'));
    expect(send).toHaveBeenCalledTimes(1);
    expect(result.current.conflict?.mine).toBe('b2');
  });

  it('auto-resolves a frontmatter-only change (body unchanged on disk)', async () => {
    const send = vi.fn().mockRejectedValueOnce(conflict()).mockResolvedValueOnce({ etag: 'e6' });
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'a', etag: 'e5' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a\n', etag: 'e1' }, { send, fetchLatest }),
    );
    act(() => result.current.save('b'));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send.mock.calls).toEqual([['b', 'e1'], ['b', 'e5']]);
    expect(result.current.conflict).toBeNull();
  });

  it('keep mine saves the latest text typed during the conflict', async () => {
    const send = vi
      .fn()
      .mockRejectedValueOnce(conflict())
      .mockResolvedValueOnce({ etag: 'e12' });
    const fetchLatest = vi
      .fn()
      .mockResolvedValueOnce({ body: 'theirs', etag: 'e9' })
      .mockResolvedValueOnce({ body: 'theirs', etag: 'e11' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest }),
    );
    act(() => result.current.save('b'));
    await waitFor(() => expect(result.current.conflict).not.toBeNull());
    act(() => result.current.save('b-latest'));
    await act(async () => result.current.keepMine());
    expect(send).toHaveBeenLastCalledWith('b-latest', 'e11');
    expect(result.current.conflict).toBeNull();
  });

  it('keep theirs returns their text and bases the next save on their etag', async () => {
    const send = vi.fn().mockRejectedValueOnce(conflict()).mockResolvedValueOnce({ etag: 'e20' });
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'theirs', etag: 'e9' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest }),
    );
    act(() => result.current.save('b'));
    await waitFor(() => expect(result.current.conflict).not.toBeNull());
    let kept: ReturnType<typeof result.current.keepTheirs> = null;
    act(() => {
      kept = result.current.keepTheirs();
    });
    expect(kept).toEqual({ mine: 'b', theirs: 'theirs', theirsEtag: 'e9' });
    expect(result.current.conflict).toBeNull();
    act(() => result.current.save('theirs edited'));
    await waitFor(() => expect(send).toHaveBeenLastCalledWith('theirs edited', 'e9'));
  });

  it('non-409 errors go to onError without a conflict', async () => {
    const onError = vi.fn();
    const send = vi.fn().mockRejectedValueOnce(new ApiError('boom', 500));
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest: vi.fn() }, onError),
    );
    act(() => result.current.save('b'));
    await waitFor(() => expect(onError).toHaveBeenCalled());
    expect((onError.mock.calls[0]![0] as Error).message).toBe('boom');
    expect(result.current.conflict).toBeNull();
  });

  it('adopt() takes an etag produced outside the editor (extract-photo)', async () => {
    const send = vi.fn().mockResolvedValue({ etag: 'e3' });
    const { result } = renderHook(() =>
      useGuardedSave({ body: 'a', etag: 'e1' }, { send, fetchLatest: vi.fn() }),
    );
    act(() => result.current.adopt('e2', 'a + photo text'));
    act(() => result.current.save('a + photo text'));
    await waitFor(() => expect(send).toHaveBeenCalledWith('a + photo text', 'e2'));
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd desktop && npx vitest run src/renderer/__tests__/line-diff.test.ts src/renderer/__tests__/use-guarded-save.test.tsx`
Expected: FAIL with "Failed to resolve import '../lib/line-diff'" and "'../lib/use-guarded-save'".

- [ ] **Step 3: Implement the line diff**

Create `desktop/src/renderer/lib/line-diff.ts`:

```ts
export type DiffLine = { kind: 'same' | 'add' | 'del'; text: string };

// LCS table is n·m cells; a 2,000×2,000-line pair is 4M Uint32 cells (16 MB).
// Above that, show a whole-block replace rather than freeze the renderer.
const MAX_CELLS = 4_000_000;

/** Line-level diff of `oldText` → `newText` (LCS). CRLF is treated as LF. */
export function lineDiff(oldText: string, newText: string): DiffLine[] {
  const a = oldText.split(/\r?\n/);
  const b = newText.split(/\r?\n/);
  const n = a.length;
  const m = b.length;
  if (n * m > MAX_CELLS) {
    return [
      ...a.map((text): DiffLine => ({ kind: 'del', text })),
      ...b.map((text): DiffLine => ({ kind: 'add', text })),
    ];
  }
  const w = m + 1;
  const dp = new Uint32Array((n + 1) * w);
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i * w + j] =
        a[i] === b[j]
          ? dp[(i + 1) * w + j + 1]! + 1
          : Math.max(dp[(i + 1) * w + j]!, dp[i * w + j + 1]!);
    }
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      out.push({ kind: 'same', text: a[i]! });
      i++;
      j++;
    } else if (dp[(i + 1) * w + j]! >= dp[i * w + j + 1]!) {
      out.push({ kind: 'del', text: a[i]! });
      i++;
    } else {
      out.push({ kind: 'add', text: b[j]! });
      j++;
    }
  }
  while (i < n) out.push({ kind: 'del', text: a[i++]! });
  while (j < m) out.push({ kind: 'add', text: b[j++]! });
  return out;
}
```

- [ ] **Step 4: Implement the hook**

Create `desktop/src/renderer/lib/use-guarded-save.ts`:

```ts
import { useCallback, useRef, useState } from 'react';
import { ApiError } from './api/client';

export interface SaveTarget {
  /** Persist `body`; `ifMatch` is the etag the save is based on (null = unconditional). */
  send: (body: string, ifMatch: string | null) => Promise<{ etag?: string | null }>;
  /** Re-read the note as it is on disk now. */
  fetchLatest: () => Promise<{ body: string; etag?: string | null }>;
}

export interface Conflict {
  /** The user's latest text — keeps updating while autosave is paused. */
  mine: string;
  theirs: string;
  theirsEtag: string | null;
}

export interface GuardedSave {
  save: (body: string) => void;
  conflict: Conflict | null;
  resolving: boolean;
  keepMine: () => Promise<void>;
  keepTheirs: () => Conflict | null;
  adopt: (etag: string | null, body: string) => void;
}

/** GET bodies come back trimmed by the server; editor output may carry a
 * trailing newline. Compare without trailing whitespace. */
export function sameBody(a: string, b: string): boolean {
  return a.replace(/\s+$/, '') === b.replace(/\s+$/, '');
}

const isConflict = (err: unknown): boolean => err instanceof ApiError && err.status === 409;
const asError = (err: unknown): Error => (err instanceof Error ? err : new Error(String(err)));

/**
 * Etag-chained autosave (spec B §7). Saves are serialised so a save never
 * 409s against our own previous write. On 409 the note is re-read: if only
 * its frontmatter changed (re-route, export stamp), the save is resent once
 * on the fresh etag; otherwise autosave pauses and `conflict` is set. While
 * paused, `save()` only records the latest text as `mine` — nothing is lost.
 */
export function useGuardedSave(
  initial: { body: string; etag: string | null },
  target: SaveTarget,
  onError?: (err: Error) => void,
): GuardedSave {
  const etagRef = useRef<string | null>(initial.etag);
  const baseBodyRef = useRef(initial.body);
  const inFlightRef = useRef(false);
  const queuedRef = useRef<string | null>(null);
  const conflictRef = useRef<Conflict | null>(null);
  const [conflict, setConflictState] = useState<Conflict | null>(null);
  const [resolving, setResolving] = useState(false);
  const targetRef = useRef(target);
  targetRef.current = target;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  const setConflict = useCallback((c: Conflict | null) => {
    conflictRef.current = c;
    setConflictState(c);
  }, []);

  const markSaved = (body: string, etag: string | null | undefined) => {
    etagRef.current = etag ?? null;
    baseBodyRef.current = body;
  };

  const handleConflict = async (mine: string, allowAutoResolve: boolean): Promise<void> => {
    let latest: { body: string; etag?: string | null };
    try {
      latest = await targetRef.current.fetchLatest();
    } catch (err) {
      onErrorRef.current?.(asError(err));
      setConflict({ mine, theirs: '', theirsEtag: null });
      return;
    }
    if (allowAutoResolve && sameBody(latest.body, baseBodyRef.current)) {
      try {
        const res = await targetRef.current.send(mine, latest.etag ?? null);
        markSaved(mine, res.etag);
      } catch (err) {
        if (isConflict(err)) await handleConflict(mine, false);
        else onErrorRef.current?.(asError(err));
      }
      return;
    }
    setConflict({ mine, theirs: latest.body, theirsEtag: latest.etag ?? null });
  };

  const run = async (body: string): Promise<void> => {
    inFlightRef.current = true;
    try {
      const res = await targetRef.current.send(body, etagRef.current);
      markSaved(body, res.etag);
    } catch (err) {
      if (isConflict(err)) await handleConflict(body, true);
      else onErrorRef.current?.(asError(err));
    } finally {
      inFlightRef.current = false;
    }
    const next = queuedRef.current;
    queuedRef.current = null;
    if (next === null) return;
    if (conflictRef.current) setConflict({ ...conflictRef.current, mine: next });
    else await run(next);
  };

  const save = (body: string) => {
    if (conflictRef.current) {
      setConflict({ ...conflictRef.current, mine: body });
      return;
    }
    if (inFlightRef.current) {
      queuedRef.current = body;
      return;
    }
    void run(body);
  };

  const keepMine = async (): Promise<void> => {
    const start = conflictRef.current;
    if (!start) return;
    setResolving(true);
    inFlightRef.current = true;
    let followUp: string | null = null;
    try {
      const latest = await targetRef.current.fetchLatest();
      const mine = conflictRef.current?.mine ?? start.mine;
      const res = await targetRef.current.send(mine, latest.etag ?? null);
      markSaved(mine, res.etag);
      const newest = conflictRef.current?.mine;
      setConflict(null);
      if (newest !== undefined && newest !== mine) followUp = newest;
    } catch (err) {
      if (isConflict(err)) await handleConflict(conflictRef.current?.mine ?? start.mine, false);
      else onErrorRef.current?.(asError(err));
    } finally {
      inFlightRef.current = false;
      setResolving(false);
    }
    if (followUp !== null) await run(followUp);
  };

  const keepTheirs = (): Conflict | null => {
    const c = conflictRef.current;
    if (!c) return null;
    markSaved(c.theirs, c.theirsEtag);
    setConflict(null);
    return c;
  };

  const adopt = (etag: string | null, body: string) => markSaved(body, etag);

  return { save, conflict, resolving, keepMine, keepTheirs, adopt };
}
```

- [ ] **Step 5: Run the tests and gates**

Run: `cd desktop && npx vitest run src/renderer/__tests__/line-diff.test.ts src/renderer/__tests__/use-guarded-save.test.tsx && npm run typecheck && npx eslint --max-warnings 0 src/renderer/lib/line-diff.ts src/renderer/lib/use-guarded-save.ts src/renderer/__tests__/line-diff.test.ts src/renderer/__tests__/use-guarded-save.test.tsx`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add desktop/src/renderer/lib/line-diff.ts desktop/src/renderer/lib/use-guarded-save.ts desktop/src/renderer/__tests__/line-diff.test.ts desktop/src/renderer/__tests__/use-guarded-save.test.tsx
git commit -m "feat(desktop): etag-chained guarded autosave with conflict state and line diff"
```

---

### Task 9: Desktop UI: conflict banner, `GuardedNoteEditor`, wiring into Jots and NoteView

**Files:**
- Create: `desktop/src/renderer/components/ConflictBanner.tsx`
- Create: `desktop/src/renderer/components/GuardedNoteEditor.tsx`
- Modify: `desktop/src/renderer/components/RichMarkdownEditor.tsx` (`interface Props` becomes `export interface RichMarkdownEditorProps`)
- Modify: `desktop/src/renderer/screens/jots.tsx`
- Modify: `desktop/src/renderer/components/NoteView.tsx`
- Create: `desktop/src/renderer/__tests__/GuardedNoteEditor.test.tsx`
- Modify: `desktop/src/renderer/__tests__/NoteView.test.tsx`

**Interfaces:**
- Consumes: `useGuardedSave`, `Conflict`, `SaveTarget` and `lineDiff` (Task 8). `useUpdateJot`, `useUpdateNoteByPath`, `get` and `Note.etag` (Task 7).
- Produces:

```ts
export interface GuardHandle { adopt: (etag: string | null, body: string) => void }
export interface GuardedNoteEditorProps {
  initialBody: string;
  initialEtag: string | null;
  send: SaveTarget['send'];
  fetchLatest: SaveTarget['fetchLatest'];
  onSaveError?: (err: Error) => void;
  guardRef?: React.MutableRefObject<GuardHandle | null>;
  editorProps: Omit<RichMarkdownEditorProps, 'markdown' | 'onSave'>;
}
export function GuardedNoteEditor(props: GuardedNoteEditorProps): JSX.Element;
export function ConflictBanner(props: { conflict: Conflict; resolving: boolean; onKeepMine: () => void; onKeepTheirs: () => void }): JSX.Element;
```

- [ ] **Step 1: Write the failing tests**

Create `desktop/src/renderer/__tests__/GuardedNoteEditor.test.tsx`:

```tsx
import { describe, it, expect, vi } from 'vitest';
import { render, screen, waitFor, act, fireEvent } from '@testing-library/react';
import type { Editor } from '@tiptap/core';
import { GuardedNoteEditor } from '../components/GuardedNoteEditor';
import { ApiError } from '../lib/api/client';

const E1 = 'aaaaaaaaaaaaaaaa';
const E2 = 'cccccccccccccccc';

function setup(send: ReturnType<typeof vi.fn>, fetchLatest: ReturnType<typeof vi.fn>) {
  let editor: Editor | undefined;
  render(
    <GuardedNoteEditor
      initialBody="original line"
      initialEtag={E1}
      send={send}
      fetchLatest={fetchLatest}
      editorProps={{
        jotId: 'n.md',
        debounceMs: 10,
        onEditorReady: (e) => {
          editor = e;
        },
      }}
    />,
  );
  return () => editor;
}

async function typeTail(getEditor: () => Editor | undefined) {
  await waitFor(() => expect(getEditor()).toBeDefined());
  act(() => {
    const ed = getEditor()!;
    ed.commands.insertContentAt(ed.state.doc.content.size, 'my tail');
  });
}

describe('GuardedNoteEditor', () => {
  it('shows the banner on 409 and the diff of theirs against mine', async () => {
    const send = vi.fn().mockRejectedValueOnce(new ApiError('changed', 409));
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'their edit', etag: E2 });
    const getEditor = setup(send, fetchLatest);
    await typeTail(getEditor);
    await screen.findByRole('alert');
    expect(screen.getByText(/This note changed outside the editor/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'view changes' }));
    const diff = screen.getByTestId('conflict-diff');
    expect(diff).toHaveTextContent('their edit');
    expect(diff).toHaveTextContent('my tail');
  });

  it('keep mine overwrites using the fresh etag and clears the banner', async () => {
    const send = vi
      .fn()
      .mockRejectedValueOnce(new ApiError('changed', 409))
      .mockResolvedValue({ etag: 'dddddddddddddddd' });
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'their edit', etag: E2 });
    const getEditor = setup(send, fetchLatest);
    await typeTail(getEditor);
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: 'keep mine' }));
    await waitFor(() =>
      expect(send).toHaveBeenLastCalledWith(expect.stringContaining('my tail'), E2),
    );
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });

  it('keep theirs reloads the editor with their text', async () => {
    const send = vi.fn().mockRejectedValueOnce(new ApiError('changed', 409));
    const fetchLatest = vi.fn().mockResolvedValue({ body: 'their edit', etag: E2 });
    const getEditor = setup(send, fetchLatest);
    await typeTail(getEditor);
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: 'keep theirs' }));
    await screen.findByText('their edit');
    expect(screen.queryByRole('alert')).toBeNull();
    expect(screen.queryByText(/my tail/)).toBeNull();
  });
});
```

Add this test to `desktop/src/renderer/__tests__/NoteView.test.tsx` inside `describe('NoteView', …)`:

```tsx
  it('sends the note etag as If-Match on autosave', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: { ...syncedNote, etag: '0123456789abcdef' } });
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
    await waitFor(
      () =>
        expect(apiRequest).toHaveBeenCalledWith(
          'PATCH',
          '/v1/notes/body',
          { path: syncedNote.path, body: expect.stringContaining('edited tail') },
          { ifMatch: '0123456789abcdef' },
        ),
      { timeout: 3000 },
    );
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd desktop && npx vitest run src/renderer/__tests__/GuardedNoteEditor.test.tsx src/renderer/__tests__/NoteView.test.tsx`
Expected: FAIL. `../components/GuardedNoteEditor` can't be resolved, and the NoteView PATCH is called with 3 args instead of 4.

- [ ] **Step 3: Export the editor props**

In `desktop/src/renderer/components/RichMarkdownEditor.tsx`, rename `interface Props {` to `export interface RichMarkdownEditorProps {`, and change the component signature's `}: Props) {` to `}: RichMarkdownEditorProps) {`.

- [ ] **Step 4: Build the banner and the guarded editor**

Create `desktop/src/renderer/components/ConflictBanner.tsx`:

```tsx
import { useState } from 'react';
import { lineDiff } from '../lib/line-diff';
import type { Conflict } from '../lib/use-guarded-save';
import { Btn } from './Btn';
import { Lucide } from './Lucide';

interface Props {
  conflict: Conflict;
  resolving: boolean;
  onKeepMine: () => void;
  onKeepTheirs: () => void;
}

const lineClass = {
  same: 'text-ink-2',
  del: 'bg-oxblood/10 text-oxblood',
  add: 'bg-neon/10 text-ink-0',
} as const;
const prefix = { same: '  ', del: '- ', add: '+ ' } as const;

/** Spec B §7: autosave is paused; the user picks how to resolve. */
export function ConflictBanner({ conflict, resolving, onKeepMine, onKeepTheirs }: Props) {
  const [showDiff, setShowDiff] = useState(false);
  return (
    <div role="alert" className="sticky top-0 z-10 border-b border-hairline bg-vellum px-4 py-2 text-12 text-ink-1">
      <div className="flex items-center gap-2">
        <Lucide name="alert-triangle" size={14} color="var(--oxblood)" />
        <span className="flex-1">
          This note changed outside the editor. Autosave is paused — your text is kept.
        </span>
        <Btn variant="ghost" size="sm" onClick={() => setShowDiff((v) => !v)}>
          {showDiff ? 'hide changes' : 'view changes'}
        </Btn>
        <Btn variant="ghost" size="sm" onClick={onKeepTheirs} disabled={resolving}>
          keep theirs
        </Btn>
        <Btn variant="primary" size="sm" onClick={onKeepMine} disabled={resolving}>
          keep mine
        </Btn>
      </div>
      {showDiff && (
        <pre
          data-testid="conflict-diff"
          className="mt-2 max-h-64 overflow-auto rounded-sm border border-hairline bg-paper p-2 font-mono text-11"
        >
          <div className="mb-1 text-ink-3">- theirs (on disk) · + yours (in the editor)</div>
          {lineDiff(conflict.theirs, conflict.mine).map((line, i) => (
            <div key={i} className={lineClass[line.kind]}>
              {prefix[line.kind]}
              {line.text}
            </div>
          ))}
        </pre>
      )}
    </div>
  );
}
```

Create `desktop/src/renderer/components/GuardedNoteEditor.tsx`:

```tsx
import { useState } from 'react';
import { useGuardedSave, type SaveTarget } from '../lib/use-guarded-save';
import { ConflictBanner } from './ConflictBanner';
import { RichMarkdownEditor, type RichMarkdownEditorProps } from './RichMarkdownEditor';

export interface GuardHandle {
  adopt: (etag: string | null, body: string) => void;
}

export interface GuardedNoteEditorProps {
  initialBody: string;
  initialEtag: string | null;
  send: SaveTarget['send'];
  fetchLatest: SaveTarget['fetchLatest'];
  onSaveError?: (err: Error) => void;
  /** Lets the parent hand over an etag produced outside the editor (extract-photo). */
  guardRef?: React.MutableRefObject<GuardHandle | null>;
  editorProps: Omit<RichMarkdownEditorProps, 'markdown' | 'onSave'>;
}

/** RichMarkdownEditor with If-Match autosave and the conflict banner.
 * Parents remount it per note (key=…); initial body/etag are read once. */
export function GuardedNoteEditor({
  initialBody,
  initialEtag,
  send,
  fetchLatest,
  onSaveError,
  guardRef,
  editorProps,
}: GuardedNoteEditorProps) {
  const [doc, setDoc] = useState({ body: initialBody, nonce: 0 });
  const guard = useGuardedSave(
    { body: initialBody, etag: initialEtag },
    { send, fetchLatest },
    onSaveError,
  );
  if (guardRef) guardRef.current = { adopt: guard.adopt };

  const keepTheirs = () => {
    const c = guard.keepTheirs();
    if (c) setDoc((d) => ({ body: c.theirs, nonce: d.nonce + 1 }));
  };

  return (
    <>
      {guard.conflict && (
        <ConflictBanner
          conflict={guard.conflict}
          resolving={guard.resolving}
          onKeepMine={() => void guard.keepMine()}
          onKeepTheirs={keepTheirs}
        />
      )}
      <RichMarkdownEditor key={doc.nonce} markdown={doc.body} onSave={guard.save} {...editorProps} />
    </>
  );
}
```

- [ ] **Step 5: Wire NoteView**

In `desktop/src/renderer/components/NoteView.tsx`:
- Replace `import { RichMarkdownEditor } from './RichMarkdownEditor';` with `import { GuardedNoteEditor } from './GuardedNoteEditor';`.
- Add `import { get } from '../lib/api/client';` and `import type { Note } from '../../shared/api-types';`.
- Replace the frozen-body block:

```tsx
  // Freeze the FIRST fetched body + etag per path (same pattern as JotsScreen):
  // useUpdateNoteByPath invalidates ['note'] after every autosave, and a
  // refetched body flowing back into the editor would reset it mid-typing.
  // The etag is frozen with it: GuardedNoteEditor chains etags itself.
  const initialBodyRef = useRef<{ path: string; body: string; etag: string | null } | null>(null);
  if (
    note.data &&
    path &&
    (initialBodyRef.current === null || initialBodyRef.current.path !== path)
  ) {
    initialBodyRef.current = { path, body: note.data.body, etag: note.data.etag ?? null };
  }
  if (path === null && initialBodyRef.current !== null) {
    initialBodyRef.current = null;
  }
  const initial = initialBodyRef.current?.path === path ? initialBodyRef.current : undefined;
```

Delete the `handleSaveBody` function and its comment block. In its place, keep the trade-off comment as:

```tsx
  // Closing the dialog mid-debounce cancels the pending save (editor unmount
  // clears its timer) — deliberate: a flush-on-close could write a half-edited
  // doc. Edits within the last ~1s of closing are lost.
```

Replace the editor render:

```tsx
          {initial !== undefined && (
            <GuardedNoteEditor
              key={path}
              initialBody={initial.body}
              initialEtag={initial.etag}
              send={(body, ifMatch) => updateNote.mutateAsync({ path, body, ifMatch })}
              fetchLatest={() => get<Note>(`/v1/notes?path=${encodeURIComponent(path)}`)}
              onSaveError={(err) => toast.error(`save failed: ${err.message}`)}
              editorProps={{ jotId: path, onEditorReady, onWikilinkClick: openNote }}
            />
          )}
```

- [ ] **Step 6: Wire the Jots screen**

In `desktop/src/renderer/screens/jots.tsx`:
- Replace the `RichMarkdownEditor` value import with `import { GuardedNoteEditor, type GuardHandle } from '../components/GuardedNoteEditor';`. Keep `import type { EditorHandle } from '../components/RichMarkdownEditor';`.
- Add `import { get } from '../lib/api/client';` and `import type { Note } from '../../shared/api-types';`.
- Change the frozen-body ref so it also carries the etag. Update the comment's last sentence to mention the etag.

```tsx
  const initialBodyRef = useRef<{ id: string; body: string; etag: string | null } | null>(null);
  if (
    detail.data &&
    selectedId &&
    (initialBodyRef.current === null || initialBodyRef.current.id !== selectedId)
  ) {
    initialBodyRef.current = { id: selectedId, body: detail.data.body, etag: detail.data.etag ?? null };
  }
  if (selectedId === null) {
    initialBodyRef.current = null;
  }
  const editorInitial =
    initialBodyRef.current?.id === selectedId ? initialBodyRef.current : undefined;

  // Latest path for conflict re-reads: a re-route moves the file while the
  // editor stays mounted (keyed by id, not path).
  const selectedPathRef = useRef<string | null>(null);
  selectedPathRef.current = selectedItem?.path ?? null;
  const guardRef = useRef<GuardHandle | null>(null);
```

- Delete `function handleSaveBody(...)`.
- Replace `{editorBody !== undefined ? (` with `{editorInitial !== undefined ? (`. Inside `<div className="flex-1 overflow-auto">`, replace the whole `<RichMarkdownEditor … />` element with:

```tsx
                <GuardedNoteEditor
                  key={selectedId!}
                  initialBody={editorInitial.body}
                  initialEtag={editorInitial.etag}
                  send={(body, ifMatch) => updateJot.mutateAsync({ id: selectedId!, body, ifMatch })}
                  fetchLatest={() =>
                    get<Note>(`/v1/notes?path=${encodeURIComponent(selectedPathRef.current ?? '')}`)
                  }
                  onSaveError={(err) => toast.error(`save failed: ${err.message}`)}
                  guardRef={guardRef}
                  editorProps={{
                    onWikilinkClick: openNote,
                    handleRef: editorHandle,
                    jotId: selectedId!,
                    openCameraSignal: cameraSignal,
                    onPhotoInserted: (jotId, assetPath) => {
                      toast.info('reading photo…');
                      extractPhoto.mutate({ jotId, assetPath }, {
                        onSuccess: (res) => {
                          if (res.extracted) {
                            // The server wrote the callout: take its etag before
                            // the editor's own autosave of the same text.
                            guardRef.current?.adopt(res.etag ?? null, res.body);
                            editorHandle.current?.replaceWith(res.body, 'doc');
                            toast.success('photo text extracted');
                          } else {
                            toast.info(`couldn't read photo: ${res.reason ?? ''}`);
                          }
                        },
                        onError: (err) => toast.error(`extract failed: ${err.message}`),
                      });
                    },
                  }}
                />
```

Keep the `{/* key={selectedId} remounts … */}` comment above the element.

- [ ] **Step 7: Run all desktop tests and gates**

Run: `cd desktop && npx vitest run && npm run typecheck && npx eslint --max-warnings 0 src/renderer/components/ConflictBanner.tsx src/renderer/components/GuardedNoteEditor.tsx src/renderer/components/RichMarkdownEditor.tsx src/renderer/components/NoteView.tsx src/renderer/screens/jots.tsx src/renderer/__tests__/GuardedNoteEditor.test.tsx src/renderer/__tests__/NoteView.test.tsx`
Expected: the whole vitest suite is green, including the existing `jots.test.tsx` and NoteView `saves edits through PATCH /v1/notes/body`. Those fixtures have no etag, so the call shape stays 3 args. Typecheck and eslint should be clean.

- [ ] **Step 8: Commit**

```bash
git add desktop/src/renderer/components/ConflictBanner.tsx desktop/src/renderer/components/GuardedNoteEditor.tsx desktop/src/renderer/components/RichMarkdownEditor.tsx desktop/src/renderer/components/NoteView.tsx desktop/src/renderer/screens/jots.tsx desktop/src/renderer/__tests__/GuardedNoteEditor.test.tsx desktop/src/renderer/__tests__/NoteView.test.tsx
git commit -m "feat(desktop): conflict banner with view diff / keep theirs / keep mine in jots and note view"
```

---

### Task 10: Full verification

**Files:** none changed unless a gate fails.

**Interfaces:**
- Consumes: everything above.
- Produces: green CI-equivalent runs plus a manual check script for the human.

- [ ] **Step 1: Python, in the CI order**

Run: `python -m pytest ghostbrain/api/tests/ tests/test_vault_write_text.py tests/test_vault_write_writer.py tests/test_chat_export.py tests/test_mcp_tools.py tests/test_mcp_client.py tests/test_docs_routes.py tests/test_llm_providers_vault_tools.py -q`
Expected: all pass.

Then confirm CI picks up the new files: `grep -n "test_vault_write" .github/workflows/ci.yml` should show both lines.

- [ ] **Step 2: No API writer left outside the write path**

Run: `grep -rn --include='*.py' -E "frontmatter\.dumps|write_text\(|\.unlink\(" ghostbrain/api/repo/note.py ghostbrain/api/repo/notes_manual.py ghostbrain/api/repo/generated_docs.py ghostbrain/api/repo/chat_attachments.py`
Expected: only `frontmatter.dumps(post) + "\n"` inside `write_inbox_jot`, which is the create content handed to `vault_write.write`. No `write_text(` or `.unlink(` should remain in these four files.

- [ ] **Step 3: Desktop**

Run: `cd desktop && npx vitest run && npm run typecheck && npm run lint`
Expected: all green.

- [ ] **Step 4: Manual check (human, against a dev build)**

1. Open a jot and type. It autosaves with no banner.
2. Open the same jot's `.md` in another editor, change a body line and save it there. Type in Poltergeist. After about 1 s the banner "This note changed outside the editor." appears and autosave stops.
3. Click **view changes**. The diff shows their line as `-` and yours as `+`. Click **keep mine**. The file now holds your text and the banner is gone.
4. Repeat step 2 and click **keep theirs**. The editor reloads with their text.
5. While a jot is open, re-route it with the "re-route…" select, then keep typing. There should be **no** banner (frontmatter-only change auto-resolved).
6. Hand-edit a synced note's frontmatter to add a `# comment` and reorder keys. Open it from search in NoteView and edit the body. The frontmatter is byte-identical apart from the `updated:` line.
7. Ask chat to write a doc twice with the same title within one second, or via MCP. You should get two files (`…-2.html`) and no overwrite.

- [ ] **Step 5: Commit any fixes from this task**

```bash
git status --short   # expect clean; commit only if a gate needed a fix
```

---

## Self-review

**Spec coverage (B1 rows):**
- `vault_write` splice, fields, atomic write, lock, etag: Tasks 1–2.
- `_resolve_safe` house guard: Task 2 (`resolve_safe`) and Task 3 (delegation).
- Reads return `etag`: Task 3, plus Task 5 for `read_jot`.
- `If-Match` → `base_etag` → 409: Tasks 3–5.
- Migration of the spec's writer table, B1 subset:
  - `save_note_body` / PATCH body: Task 4.
  - `notes_manual.*`: Task 5.
  - `save_note_at_path` / PUT: Task 4.
  - `generated_docs.write_doc`: Task 6.
  - Worker rows are deferred to B4, as the spec's slices say.
- Editor `If-Match`, the conflict banner with its three choices, paused autosave and no silent discard: Tasks 7–9.
- Spec testing bullets in B1 scope:
  - Splice keeps bytes, including key order, quoting, comments and unknown keys.
  - A field edit touches exactly one line.
  - A multi-line field re-serialises only its own block.
  - Atomic write, the per-path lock under threads, and the etag 409.
  - Golden tests per migrated writer.
  - A missing actor header means `user`: B1 has no header, every route passes `USER` explicitly, and header mapping is B2.
  - The Vitest editor conflict banner.

**Placeholder scan:** There is no TBD, "add validation" or "similar to" anywhere. Every code step shows its code.

**Type consistency:**
- `WriteResult.updated` is used by `save_note_body` (Task 4) and set in `_edit_bytes` (Task 2).
- `ROUTER_ACTOR` is defined before `mark_manual_review`'s default (Task 5).
- `GuardHandle.adopt(etag, body)` matches `useGuardedSave.adopt` (Task 8).
- `SaveTarget['send']` returns `{ etag?: string | null }`, which `UpdateJotResponse` and `UpdateNoteBodyResponse` both satisfy.
- `patch(..., { ifMatch })` accepts `string | null | undefined`.

**Review Focus:** All five lines have a named test in the owning task (Tasks 2, 3, 4 and 8).
