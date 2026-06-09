# Rich Markdown Editor + Copy-Formatted — Design

**Date:** 2026-06-09
**Status:** Approved (brainstormed with Jannik; visual companion session)
**Depends on:** Poltergeist Jots (`feat/poltergeist-jots`, PR #17) — reuses the jots screen, JotEditor semantics, and `/v1/notes` API family.

## Goal

Upgrade note editing from a bare CodeMirror pane to a WYSIWYG markdown editor, and make any note pasteable into Slack, Confluence, Teams (or anything else that accepts rich text) with one action.

Decisions made during brainstorming:

1. **Paste mechanism:** copy-as-rich-text — one button puts HTML + markdown on the clipboard. No per-target dialect converters, no direct-send integrations (can be added later).
2. **Editing experience:** WYSIWYG (Notion/Typora-like) — markdown shorthand must keep working while typing (`# `, `**bold**`, `- `, backticks render as you type). Files on disk stay plain markdown.
3. **Scope:** jots screen AND the vault note viewer. Vault notes become **fully editable** (user accepted the connector-overwrite caveat).
4. **Copy scope:** selection if one exists, otherwise the whole note.

## Engine choice

**TipTap** (ProseMirror wrapper) with `tiptap-markdown` for (de)serialisation.

- Chosen over Milkdown for ecosystem maturity, first-class React bindings, and ready-made extensions (tables, task lists). Both are ProseMirror-based; Milkdown's markdown-native pipeline was the runner-up.
- Risk: `tiptap-markdown` is a community extension — markdown round-tripping needs fixture tests (see Testing).

## Components

### 1. `RichMarkdownEditor` (new, `desktop/src/renderer/components/`)

- Props: `{ markdown, onSave(markdown), readOnly?, debounceMs = 1000 }`.
- TipTap StarterKit (headings, bold/italic, lists, blockquote, code block, links) + table + task-list extensions + `tiptap-markdown`.
- Markdown shorthand input rules active while typing.
- Frontmatter never enters the editor — the backend already splits frontmatter from body; the editor sees body markdown only.
- Inherits JotEditor's autosave semantics verbatim:
  - 1s debounce, save only when content differs from last-saved;
  - pending timer cancelled when the note prop switches (cross-write guard);
  - parent remounts per note (`key={noteId}`);
  - `lastSaved` advances optimistically (no retry on failed save — documented trade-off).
- **Source toggle:** a small footer toggle swaps to the existing CodeMirror `JotEditor` as an escape hatch for markdown the rich editor mangles. State is per-open-note, defaults to rich.

### 2. Copy formatted

- Footer button + `⌘⇧C` inside the editor.
- Selection-aware: serialise the ProseMirror selection if non-empty, else the whole doc, to HTML.
- New IPC channel `gb:clipboard:write-rich` → Electron main calls `clipboard.write({ html, text })`, where `text` is the markdown equivalent. Rich paste into Slack/Confluence/Teams; plain markdown paste into terminals/editors.
- Toast confirms ("copied — paste anywhere").
- Known fidelity limit (accepted): target apps map rich text slightly differently (e.g. Slack flattens headings to bold).

### 3. Surfaces

- **Jots screen:** `JotsScreen` renders `RichMarkdownEditor` instead of `JotEditor`. Saves keep using `PATCH /v1/notes/{id}`.
- **Vault note viewer:** the read-only markdown viewer renders the same component, editable. Saves use the new by-path endpoint.
- **Connector-managed warning:** when the open note's frontmatter `source` is present and ≠ `manual`, show a chip: "synced note — edits may be overwritten by the next sync". Best-effort edits; no locking.
- **⌥-J overlay:** unchanged (plain textarea — capture speed over formatting).

## Backend

One new endpoint:

```
PATCH /v1/notes/body   { path: string, body: string }
```

- Path validated with the existing house pattern (`_resolve_safe`-style: vault containment + traversal rejection).
- Rewrites only the markdown body; preserves all frontmatter keys; bumps `updated` when the key exists.
- 404 unknown path, 400 invalid path, 422 empty body.
- Jot edits continue through the existing `PATCH /v1/notes/{jot_id}` (which also re-derives tags — by-path PATCH does not touch tags).

## Error handling

- Markdown that fails to parse into the editor → automatic fallback to source mode with a toast (never block opening a note).
- Clipboard write failure → error toast.
- Save failures surface via the existing toast path; optimistic `lastSaved` semantics unchanged.

## Testing

- **Round-trip fixtures:** representative markdown (headings, nested lists, task lists, tables, fenced code with language, links, blockquotes) must survive editor in→out byte-stable (modulo trailing whitespace). Failures here gate the feature.
- Clipboard IPC handler test (html + text flavours written; selection vs whole-doc).
- Backend: PATCH-by-path tests — happy path, frontmatter preservation, `updated` bump, traversal rejection, connector file edit allowed.
- Screen tests updated for the new editor + source toggle + copy button.

## Out of scope (explicitly deferred)

- Per-target dialect converters (Slack mrkdwn, Confluence storage format) — add as a "copy for…" menu later if rich-text fidelity proves insufficient.
- Direct-send integrations (post to Slack/Teams/Confluence via API).
- Image paste/embed into notes.
- Overlay formatting.

## Open questions

None blocking. Implementation plan should confirm:
1. Whether `tiptap-markdown` preserves task-list checkbox state round-trip; if not, add a small serialiser patch.
2. Bundle-size impact of TipTap in the renderer (lazy-load the editor chunk if it is heavy).
