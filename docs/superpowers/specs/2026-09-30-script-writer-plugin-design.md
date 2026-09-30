# Script Writer plugin — design

**Date:** 2026-09-30
**Status:** approved in chat, pending spec review
**Plugin id:** `script-writer` · **Location:** `plugins/script-writer/` · **Icon:** `clapperboard`

## Goal

A full screenplay writing tool inside Poltergeist for film/TV. It must:

1. Feel intuitive to write in — Final Draft-style element flow, no markup knowledge required.
2. Render and export **industry-standard** screenplays (Courier 12pt, standard margins, ~1 page/minute, correct pagination).
3. Include an **AI co-writer** you can ask questions; it looks in the vault (scoped to the script's project, its context, or the whole vault) for anything related and answers with citations, and it can perform writing actions on the script.

Non-goals: collaboration/multi-user, revision colours/locked pages (production drafts), TV multi-cam format, two-column A/V scripts, stage plays. Can be added later.

## Decisions (from brainstorming)

| Decision | Choice | Why |
|---|---|---|
| Editor | CodeMirror 6 over plain **Fountain** text, decorated per line to look like a formatted page | One plain-text source of truth; trivial for the AI to read/write; Fountain import/export for free. Rejected: ProseMirror block model (~2× code, AI edits must round-trip a node tree); textarea+preview (not a "full writing tool"). |
| Storage | Vault notes via `PUT /v1/notes` | Scripts get indexed; AI can see earlier drafts; same write-back contract Familiar uses. |
| Project | A vault folder: `20-contexts/<context>/projects/<project>/` | The script and its research live together; gives a natural AI search scope. |
| Delivery | Two slices of one plugin | Slice 1 is useful on its own; slice 2 adds AI. |

## 1. Data model

### Script file

Path: `20-contexts/<context>/projects/<project-slug>/<script-slug>.screenplay.md`

```markdown
---
type: screenplay
title: The Long Night
credit: Written by
author: Jannik Richter
source: ""
draft_date: 2026-09-30
contact: ""
scene_numbers: false
updated: 2026-09-30T10:12:00+02:00
---
FADE IN:

INT. LIGHTHOUSE - NIGHT

Rain hammers the glass. MARA (40s) ...
```

- Body is **raw Fountain**. The Fountain title page is *not* written in the body — frontmatter is the title page; it's mapped to Fountain title-page keys on export/import.
- `<context>` / `<project-slug>` come from the app's **project registry** (`GET /v1/projects` → `[{id, context, slug, name, description, archived}]`, stored in `90-meta/projects.json`; its folder template is exactly `20-contexts/{context}/projects/{slug}`). New projects are created with `POST /v1/projects {context, name}` (409 = already exists → use the existing one). Contexts come from `GET /v1/vault/contexts` → `{contexts: string[], archived: string[]}` — never hard-coded.
- Script slugs: `^[a-z0-9-]+$`, derived from the title, deduplicated against the plugin's registry with `-2`, `-3`.

### Library registry

No list-by-folder API exists, so the plugin keeps a registry in `ctx.settings` key `scripts`:

```json
[{ "path": "20-contexts/personal/projects/long-night/the-long-night.screenplay.md",
   "title": "The Long Night", "context": "personal", "project": "long-night",
   "updated": "2026-09-30T10:12:00+02:00", "pages": 97 }]
```

- Updated on every successful save.
- On open, if `GET /v1/notes?path=` returns 404 the entry is flagged "missing" with a Remove action (the file was moved or deleted outside the plugin).

### Saving

- Debounced autosave 1.5s after the last keystroke, plus save on unmount and on window blur.
- Save = `PUT /v1/notes {path, content}` with frontmatter re-serialized and `updated` bumped.
- On failure: a persistent "Unsaved — retrying" badge, exponential backoff retry (2s → 30s cap), and the latest text is also mirrored to `dataDir/drafts/<script-slug>.fountain` (via main IPC) so nothing is lost if the backend is down. On next open, if the mirror is newer than the vault note, offer "Restore unsaved draft".

## 2. Fountain engine (pure, no DOM)

`src/fountain/parse.js` — `parse(text) → Element[]`

```ts
type ElementType = 'scene_heading' | 'action' | 'character' | 'parenthetical' | 'dialogue'
  | 'transition' | 'centered' | 'lyric' | 'page_break' | 'section' | 'synopsis'
  | 'note' | 'boneyard' | 'dual_dialogue_marker';
interface Element { type: ElementType; text: string; line: number; lineEnd: number;
  sceneNumber?: string; dual?: 'left' | 'right'; depth?: number /* sections */ }
```

It follows the Fountain 1.1 spec, including forced elements (`.`, `!`, `@`, `>`, `~`, `=`, `#`), `^` dual dialogue, `[[notes]]`, and `/* boneyard */`. Emphasis (`*`, `**`, `_`) is kept in `text` and rendered by the formatter.

The same parser drives the editor decorations, the scene navigator, the character list, pagination, and AI context. It is incremental-friendly: the editor re-parses a window around the change, and a full parse runs on idle.

## 3. Editor

CodeMirror 6 with a custom `ViewPlugin` that applies **line decorations** from the parse:

| Element | On-screen style (matches print geometry at 1:1 zoom) |
|---|---|
| Scene heading | bold, uppercase, flush left, blank line above |
| Action | flush left, full width (6.0") |
| Character | uppercase, indent 3.7" from page left (2.2" from text left) |
| Parenthetical | indent 3.1", width ~2.0" |
| Dialogue | indent 2.5", width 3.5" |
| Transition | uppercase, right aligned |
| Centered | centered |
| Notes / boneyard / sections / synopses | muted, not printed |

- Font: **Courier Prime** (OFL). The woff2 files are bundled in `dist/fonts/` and loaded via `@font-face` relative to `import.meta.url`.
- Page column: a paper-coloured 8.5" sheet on the app's `--paper` background; there's a paper/dark theme toggle.
- Fountain markers that exist only to force a type (`.`, `@`, `!`, `>`) are dimmed but stay editable.

### Keyboard flow (Final Draft conventions)

- **Tab** on a line cycles its element type: Action → Character → Parenthetical (only valid after a character/dialogue) → Transition → Scene heading → Action. It rewrites the line's markers and case, e.g. Character uppercases the line and forces it with `@` if needed.
- **Enter**:
  - After a scene heading → Action.
  - After a character → Dialogue.
  - After dialogue → Character, with a blank line inserted.
  - After a parenthetical → Dialogue.
  - After a transition → Scene heading.
  - Enter on an empty element resets to Action.
- **Shift+Enter** is a soft line break within the element.
- **Autocomplete** (CodeMirror autocomplete):
  - Character names, from the parse, ranked by frequency.
  - Scene prefixes `INT. / EXT. / INT./EXT. / I/E.`
  - Known locations.
  - Times: `DAY / NIGHT / CONTINUOUS / LATER / MOMENTS LATER`.
  - Extensions: `(V.O.) (O.S.) (CONT'D)`.
- **Cmd+1…7** set the element type directly.
- **Cmd+S** saves now.
- **Cmd+Shift+F** toggles focus mode (typewriter scrolling; dims everything but the current paragraph).

### Layout

```
┌ Library ▸ The Long Night ─────── 97 pp · ~97 min · Saved ✓ ─┐
│ Scenes     │  [editor page column]         │ Page view / AI  │
│ 1 INT. …   │                               │ (tabbed panel)  │
│ 2 EXT. …   │                               │                 │
│ Characters │                               │                 │
│ MARA 212   │                               │                 │
└────────────┴───────────────────────────────┴─────────────────┘
```

- **Scene navigator**: numbered scene headings. Click to jump; drag to reorder, which moves the whole scene text block in one transaction and so is undoable. Synopses (`=`) show under each heading.
- **Character list**: names with dialogue-line counts; click cycles through their lines.
- Both side panels are collapsible; the widths are persisted in settings.

## 4. Pagination & rendering (pure)

`src/paginate/paginate.js` — `paginate(elements, opts) → Page[]`.

Geometry (US Letter; A4 option shifts the bottom margin only):

- Courier 12pt: 10 chars/inch, 6 lines/inch.
- Margins: top 1", bottom 1", left 1.5", right 1". This gives 9" × 6 lines/inch = **54 body lines per page** (the page number sits in the top margin at 0.5").
- Column widths in characters: action 60, character cue at col 22, dialogue 35 wide at col 10, parenthetical 25 at col 16, transition right-aligned to col 60.
- Page number top-right (`97.`) from page 2; the title page is unnumbered.

Rules:

- Word-wrap each element to its column width, then flow the lines into pages.
- Never end a page with a scene heading or a lone character cue; move them to the next page.
- Dialogue split across pages must leave ≥2 lines on each side. A split adds `(MORE)` at the bottom and `CHARACTER (CONT'D)` at the top of the next page, and only splits at sentence boundaries when possible.
- Parenthetical-only or 1-line dialogue blocks are not split.
- Action split: ≥2 lines each side, splitting at a sentence boundary when possible; otherwise move the whole block.
- Scene numbers are optional (frontmatter `scene_numbers`) and appear in both margins.
- Dual dialogue: two columns side by side, paginated as a unit.
- The title page is built from frontmatter: title centered at 1/3 height, credit and author below, contact and draft date bottom-left.

`src/render/pageHtml.js` turns `Page[]` into absolutely positioned HTML (inches in CSS). This one renderer feeds both the **Page view** tab and **PDF export**, so what you see is exactly what prints.

Page count and runtime (≈1 min/page) show in the status bar and are recomputed on idle.

## 5. AI co-writer (slice 2)

### Scope

A selector at the top of the AI tab:

- **Project** (default): the script's folder prefix.
- **Context**: `20-contexts/<context>/`.
- **Whole vault**.

### Retrieval — `src/ai/retrieve.js`

1. `POST /v1/search {q, limit: 50}`, then keep the hits whose `path` starts with the scope prefix and drop the script file itself. Keep the top 8.
2. If fewer than 3 hits remain in Project scope, widen to Context automatically and say so in the UI ("Nothing in project — searched context").
3. For the top 4 hits, fetch the full note (`GET /v1/notes?path=`), truncated to 4k chars each. The rest contribute their snippets only.

### Ask

A chat thread per script, persisted in `dataDir/threads/<script-slug>.json` via main IPC.

The prompt to `POST /v1/llm/run` contains:

- A system prompt: screenwriting collaborator; cite sources as `[n]`; answer from the notes and say so when they don't cover the question.
- The script outline: scene headings plus synopses.
- The current scene's full text.
- The numbered sources.
- The last 6 turns.

The call omits `model` (server default, which works with every configured provider), passes `timeoutSeconds: 240` (the renderer's sidecar bridge times out at 300s), and passes an **explicit `budgetUsd`** so the client's $0.50 default cap never truncates it: Ask $1.00, actions $1.00, Polish $0.50 per section.

Answers render as markdown (`marked`). `[n]` citations are clickable and open a source drawer with the note title, path, and content.

### Actions

The actions run on the selection, or on the current scene when nothing is selected. They are available from the AI panel's action bar, and `Cmd+K` opens the AI panel (the right-click menu was dropped as redundant):

| Action | Output |
|---|---|
| Continue scene | Fountain appended after the scene (or selection) |
| Rewrite… (presets: tighter, funnier, darker, more subtext + free text) | replacement Fountain |
| Punch up dialogue | replacement Fountain, dialogue only |
| Scene from beat (selection is a synopsis/beat) | new scene Fountain |
| Continuity check | a list of issues with citations — no edit |

- Each edit action requests `jsonSchema: {fountain: string, notes: string}` and runs the same retrieval (using the selection as the query) so the output respects your bios and research.
- The result appears as an **inline diff widget** in the editor (deleted text struck through, new text highlighted) with **Accept / Reject / Insert below** controls. Accept is a single undoable transaction.
- The returned Fountain is validated with `parse()`. If it contains no dialogue or action elements, the result is shown as text instead of a diff.

### Polish (whole document)

A **Polish** button in the top bar opens a dialog with four passes:

| Pass | Default | Does |
|---|---|---|
| Formatting | on | Makes the Fountain industry-correct: uppercase headings and cues, one blank line between elements, dialogue under its cue, consistent character names and extensions, `(CONT'D)`. No word changes. |
| Language | on | Spelling, grammar and punctuation only; keeps the writer's voice. |
| Tighten prose | off | Trims action lines; dialogue untouched. |
| Punch up dialogue | off | Sharper voice and subtext; keeps what happens. |

- **Execution.** The script is split into sections: the preamble plus one per scene. Sections are polished through `/v1/llm/run`, three at a time, with a progress bar and Cancel. Each section has a $0.50 cap, and the dialog shows the section count and the worst-case total before you run it. Title-page metadata is never sent.
- **Validation.** Each polished section is checked with `parse()` and kept as the original, flagged, when any of these is true:
  - it is empty;
  - it has no screenplay elements;
  - it lost more than 40% of its non-blank lines;
  - a scene lost its heading.
  A failing or erroring section never sinks the rest.
- **Review.** One whole-document review view lists every change, grouped by scene: removed lines struck through, added lines highlighted, word-level highlights for 1:1 line edits. Each change has a keep toggle, defaulting to on.
  - **Accept all / Reject all / Apply.**
  - Apply replaces the document in one transaction, so it is a single ⌘Z.
  - Apply is refused if the script changed while polishing.

### Formatting toolbar and new scenes

- **Formatting toolbar.** A formatting row above the page holds:
  - an **element dropdown** showing the current line's element and setting it, the same as ⌘1–7;
  - **B / I / U** buttons that wrap the selection in `**` / `*` / `_`, or unwrap it if it is already wrapped (⌘B / ⌘I / ⌘U);
  - a **+ Scene** button.
- **+ Scene** (also in the Scenes navigator header). It inserts a blank line and `INT. ` after the scene containing the cursor, puts the cursor after `INT. ` and opens autocomplete.

## 6. Library, import, export

- **Library screen** (the plugin's landing view): cards for the registry entries, sorted by `updated`, showing title, project, pages, and last edited.
- **New script** dialog: title, project (dropdown of `GET /v1/projects`, grouped by context) or "+ New project" (context dropdown from `GET /v1/vault/contexts` + name → `POST /v1/projects`), and title-page fields. It creates the file with `FADE IN:` and one scene heading.
- **Import**: `.fountain` (title page becomes frontmatter) and `.fdx` (slice 2), via a main-process file dialog.
- **Export** (main-process IPC; a save dialog, then write):
  - **PDF**: `pageHtml` goes into a hidden `BrowserWindow`, which calls `webContents.printToPDF({pageSize: 'Letter' | 'A4', margins: {marginType: 'none'}, printBackground: false})` because the HTML already carries the margins. The window is destroyed afterward.
  - **Fountain**: frontmatter becomes the title page, followed by the body.
  - **FDX** (slice 2): Final Draft XML with `<Paragraph Type="Scene Heading|Action|Character|Parenthetical|Dialogue|Transition">` and a title page.

## 7. Plugin structure

```
plugins/script-writer/
  manifest.json          # id script-writer, apiVersion 1, icon clapperboard, main + renderer
  build.mjs              # esbuild: renderer browser/esm, main node/cjs; copies fonts to dist/fonts
  package.json           # react, react-dom, @codemirror/*, marked, lucide-react; vitest, esbuild
  src/main.js            # activate: ipc handlers (export-pdf, export-file, import-file,
                         #   draft-mirror read/write, thread read/write); deactivate: destroy windows
  src/renderer.jsx       # mount(el, api) → React root; returns unmount
  src/fountain/          # parse.js, serialize.js (frontmatter ⇄ title page)
  src/paginate/          # paginate.js, wrap.js
  src/render/            # pageHtml.js
  src/fdx/               # import.js, export.js            (slice 2)
  src/editor/            # cm setup, decorations.js, keymap.js, autocomplete.js, diffWidget.js
  src/ai/                # retrieve.js, prompts.js, actions.js (slice 2)
  src/store/             # scripts registry, save/retry logic
  src/ui/                # Library, EditorScreen, SceneNav, CharacterList, PageView, AiPanel
  dist/                  # committed
  README.md
```

The renderer talks to the backend only through `plugin.sidecar.request`; filesystem and dialogs go through main IPC. IPC channels (all `^[a-z0-9:_-]+$`): `export-pdf`, `export-file`, `import-file`, `draft-read`, `draft-write`, `thread-read`, `thread-write`.

Theming: UI chrome uses `api.theme` values (`--paper`, `--ink-*`, `--neon`, `--hairline`) with fallbacks. The script page itself is always paper-white with black Courier in paper mode, since it's a print representation.

## 8. Error handling

| Failure | Behavior |
|---|---|
| Save fails | badge + backoff retry + local draft mirror (see §1) |
| Script note 404 on open | "Missing" state in the library with a Remove action |
| Search/LLM error (`error` field set, or a fetch rejects) | inline error bubble in the AI panel with Retry; the editor is unaffected |
| AI returns unparseable Fountain | shown as plain text with Copy, not as a diff |
| PDF export fails | toast with the message; the hidden window is always destroyed in `finally` |
| Malformed import | toast naming the file; nothing written |

## 9. Testing

vitest, pure modules first (TDD):

- `parse`: every Fountain element type, forced elements, dual dialogue, notes/boneyard, and edge cases: an all-caps action line vs a character cue, a transition not ending in `TO:`, and a scene heading without a blank line.
- `paginate`: 54-line fill; no orphan scene heading or character cue; `(MORE)`/`(CONT'D)` on a dialogue split with ≥2 lines each side; 1-line dialogue not split; action sentence-boundary split; the title page; scene numbers; and a golden test that a known ~10-page fixture paginates to the expected page breaks.
- `serialize`: frontmatter ⇄ Fountain title page round-trip.
- `keymap` logic (pure functions that compute the next element type and line rewrite): Tab cycle and Enter transitions.
- `retrieve`: scope filtering, excluding the script itself, auto-widening, and truncation.
- `prompts`/`actions`: an explicit `budgetUsd` is always sent (asserted like Familiar's sweep tests), and the schema is requested for edit actions.
- `fdx`: export → import round-trip on the fixture (slice 2).
- Manual: install from folder in the dev app, write a scene with the keyboard only, export a PDF, and compare it side by side with a Final Draft/Highland PDF of the same Fountain fixture.

## 10. Slices

**Slice 1 — Writing tool**

- Manifest and build.
- Fountain parse/serialize.
- CodeMirror editor with decorations, keymap and autocomplete.
- Scene navigator (including drag reorder) and character list.
- Paginator plus Page view.
- Library, New script, save/retry/draft mirror.
- Fountain import/export and PDF export.

**Slice 2 — AI co-writer**

- Retrieval and scope.
- Ask thread with citations and source drawer.
- Actions with the inline diff widget, and continuity check.
- FDX import/export.
- Marketplace README.

Each slice gets its own implementation plan and ships as a working, installable plugin build.
