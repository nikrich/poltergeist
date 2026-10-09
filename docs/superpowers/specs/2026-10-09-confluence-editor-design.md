# Confluence-Level Jots Editor + Inline AI + Graph — Design

- **Date:** 2026-10-09
- **Status:** Draft — awaiting review
- **Repo:** ghost-brain (poltergeist)
- **Depends on:** Rich Markdown Editor (`2026-06-09-rich-markdown-editor-design.md`), Jot Docs Assistant (`2026-06-10-jot-docs-assistant-design.md`). Its AI-writing slice (A5) depends on **AI Changes + Revert** (`2026-10-09-ai-changes-revert-design.md`).
- **Author:** brainstormed with Jannik

## Goal & intent

**What the user asked for:** "extend the jots to be a full-on editor at the level of Confluence, with AI assist as well". Pull in the useful parts of the Brainstead editor: `[[` and `#` suggestions while typing, resizable images, full-screen diagrams, read-aloud, focus mode (⌘.). Also fold in the Brainstead **Graph**: a focus node, a depth slider, grey rings for pages that are linked but not written yet, colour by kind, size by link count.

**Assumptions (not stated by the user — correct me):**

- "Confluence level" means **authoring parity for one person's notes**: rich blocks, linking, history, AI help. It doesn't mean multi-user collaboration (comments, permissions, real-time co-editing). Poltergeist is single-user, and the vault is a folder of files.
- **Files on disk stay plain markdown** and have to stay readable in Obsidian or any text editor. Every new block needs a markdown form that survives the editor's round trip and degrades readably elsewhere. This rule decides several of the formats below.
- The editor upgrade applies wherever `RichMarkdownEditor` renders: the jots screen and the vault note viewer.

## Scope

In scope:

1. **Linking:** `[[` wikilink autocomplete, `#tag` and `@person` suggestions, and a backlinks panel.
2. **Blocks:** callout panels (info / note / tip / warning / error / success); expand/collapse; status lozenges; table of contents; Mermaid diagrams with full-screen view; resizable images; table controls (add or remove rows and columns, header row toggle, column alignment).
3. **Page history:** snapshots, a diff view, and restore.
4. **Inline AI (⌘J):** continue, summarise, expand, polish, translate (including English ↔ Afrikaans), and "draft from my vault". Output streams into the document as an accept/reject diff at the cursor or selection.
5. **Focus mode (⌘.)** and **read-aloud.**
6. **Graph screen:** an ego-graph around a focus page, with a depth slider and placeholder nodes for pages that don't exist yet.

Non-goals (YAGNI, with reasons):

- **Multi-column layouts.** Markdown has no column construct. Any encoding (raw HTML or a custom fence) breaks the plain-markdown rule or makes the content uneditable elsewhere. See Open question 1.
- **Merged table cells.** GFM tables can't express them, and HTML tables violate `html: false`.
- **Inline comments, @-mentions that notify people, permissions, real-time co-editing.** These need multi-user infrastructure the app doesn't have.
- **Page tree / parent-child hierarchy.** `JotTree` already groups by context → project → month. A true page tree would need a new frontmatter contract. It can be revisited once the linking slices are in use.

## Markdown storage format (per block)

The single source of truth stays `buildEditorExtensions()` in `desktop/src/renderer/lib/editor/extensions.ts`. Every block below gets a fixture in `markdown-roundtrip.test.ts`, and that test gates each slice.

| Block | On-disk form | Why | Degrades to |
|---|---|---|---|
| Callout panel | `> [!info] Optional title` + `> body` lines (types: `info note tip warning error success`) | Obsidian / GitHub alert syntax, widely understood | a blockquote with a `[!info]` marker line |
| Expand / collapse | foldable callout `> [!note]- Title` (`-` = starts collapsed, `+` = starts open) | Same mechanism as callouts. `<details>` would need `html: true`, which the editor deliberately disables | a blockquote |
| Status lozenge | inline code with a `status:` prefix: `` `status:In progress/yellow` `` (colours: `grey blue green yellow red purple`) | Inline code survives every markdown renderer untouched | readable inline code `status:In progress/yellow` |
| Table of contents | empty fenced block ` ```toc ``` ` | The Obsidian TOC-plugin convention. Generated at render time, so nothing to keep in sync on disk | an empty code block |
| Mermaid diagram | ` ```mermaid ` fence | GitHub, Obsidian and Confluence importers all render it | a code block with the source |
| Image size | Obsidian alt-pipe: `![alt\|480](90-meta/assets/…)` | The de-facto markdown width convention | an image (alt text reads `alt\|480` in plain renderers) |
| Wikilink | `[[20-contexts/…/note\|Title]]`: vault-relative path without `.md`, plus an alias | Matches `graph.py::_target_rel` and the existing `restoreWikilinks` / `WIKILINK_RE` handling, so the graph and backlinks resolve it | a link (Obsidian) or literal text |
| `@person` | wikilink to the person note: `[[30-cross-context/people/<slug>\|@Name]]` | People already live in `30-cross-context/people/` (bootstrap). Reusing wikilinks puts them in the graph for free | a link |
| `#tag` | plain `#tag` text | `notes_manual.extract_tags` already reads body hashtags | text |

**Ambiguity guard.** Existing `ExtractCallout` blockquotes ("Extracted from photo") have no `[!type]` marker, so they stay plain blockquotes. Only a first line that matches `^\[!(info|note|tip|warning|error|success)\][+-]?` becomes a callout node. Inline code that happens to start with `status:` is rendered as a lozenge. That collision is accepted and documented.

## Architecture

### Renderer: editor extensions (`desktop/src/renderer/lib/editor/`)

One file per extension, all registered in `extensions.ts`:

- `callout.ts`: a `callout` node (attrs `kind`, `title`, `foldable: none|open|closed`) with a custom tiptap-markdown serialize/parse. It renders as a coloured panel with an icon, and the chevron toggles `foldable`.
- `status.ts`: an inline atom node `status` (attrs `label`, `color`). Clicking it opens a small popover to edit label and colour. The input rule `/status ` comes from the slash menu.
- `toc.ts`: an atom block node. It renders a live list of the document's headings, and clicking one scrolls to it.
- `mermaid.ts`: a code-block NodeView for `language === 'mermaid'`. It renders an SVG via **`mermaid`**, a new dependency loaded lazily with dynamic `import()`, so the cost lands only when a diagram is on screen. Click toggles the source editor; a "⤢" button opens `DiagramModal` full-screen with pan and zoom. Render errors show the source plus the error text instead of throwing.
- `image.ts` (existing `JotImage`): gains a `width` attribute, parsed from and serialised to the alt-pipe form, plus a drag handle on the right edge that snaps to 25 / 50 / 75 / 100 %.
- `wikilink-suggest.ts`, `tag-suggest.ts`, `person-suggest.ts`: three `@tiptap/suggestion` instances, the same mechanism as `slash.ts`, rendered by one `SuggestMenu` component. Each item shows a title plus a muted path or context. Choosing an item inserts the markdown forms from the table above.
- `table-controls.ts`: wires the existing `@tiptap/extension-table` commands (`addRowAfter`, `deleteColumn`, `toggleHeaderRow`, …) to a floating toolbar shown while the cursor is in a table. Alignment is stored in the GFM delimiter row.
- `SLASH_ITEMS` gains: Info / Note / Tip / Warning panels, Expand, Status, Table of contents, Diagram, Quote stays.

### Backend: vault link index (`ghostbrain/vault_index/links.py`, new)

`graph.py::build_graph()` walks every note on each call. Suggestions and backlinks need answers in under 50 ms, so this module keeps an **mtime-keyed incremental index** of `{path → title, tags, type, outgoing link targets}`:

- It's built lazily on first use and refreshed by comparing `stat().st_mtime` per file, so a refresh only re-parses changed files.
- It's in memory only. At this vault size a cold build takes about a second, so it isn't persisted.
- `graph.py` is refactored to build from this index rather than its own walk. The response is unchanged, except for placeholder nodes (see Graph).

New routes on the existing vault router (`ghostbrain/api/routes/vault.py`):

- `GET /v1/vault/suggest?kind=page|tag|person&q=…&limit=20`: prefix-then-substring match on title (pages), tag (tags) or the people folder (persons), ranked by recency.
- `GET /v1/vault/backlinks?path=…`: notes linking to `path`, as `{path, title, context, snippet}`. The snippet is the line containing the link.
- `GET /v1/vault/graph?focus=…&depth=1..3`: an ego subgraph (see Graph). Without `focus` it keeps today's behaviour for `BrainConstellation`.

### Page history (`ghostbrain/history/store.py`, new; shared with spec B)

Not under the vault. The vault isn't a git repo, history files there would show up as notes in other tools, and syncing them would multiply storage. Snapshots live in `~/.ghostbrain/history/` (via `state_dir()`):

- **Content-addressed blobs:** `blobs/<sha256>.md` (whole file including frontmatter). Identical versions cost nothing.
- **Per-note log:** `notes/<sha1(rel_path)>.jsonl`, one line per snapshot: `{ts, rel_path, blob, actor, reason}`. `actor` is one of `user | assistant | mcp | plugin | worker | restore`.
- **When a snapshot is taken:** before any write that changes the note, coalesced for **user** autosaves (at most one per note per 5 minutes of continuous editing). Non-user actors are never coalesced, since every AI write must be revertible.
- **Retention:** keep everything for 30 days, then one per day for a year, then one per month. A daily scheduler job prunes logs and garbage-collects unreferenced blobs.
- `PATCH /v1/notes/{jot_id}` and `PATCH /v1/notes/body` call `history.snapshot(rel, actor="user")` before writing.

Routes:

- `GET /v1/notes/history?path=…` lists snapshots.
- `GET /v1/notes/history/blob?path=…&blob=…` returns the content.
- `POST /v1/notes/history/restore {path, blob}` snapshots the current version as `actor: restore`, then writes the blob.

UI: a "History" item in the editor header opens `HistoryDrawer`, with a timeline, an actor badge, a line diff against the current version (a `diff` npm package, `diffLines`) and a Restore button.

### Inline AI (⌘J)

- **Trigger:** ⌘J or a toolbar "✦" button opens `InlineAssistPopover` at the selection (or the cursor). It has a prompt box plus quick actions: Continue, Polish, Expand, Summarise, Translate → (English / Afrikaans / other…), Draft from vault.
- **Transport:** the existing `POST /v1/docs/assist` SSE route, extended:
  - `mode` gains `continue | translate`;
  - an optional `target_language` field;
  - the request may carry `path` (vault-relative) instead of `jot_id`, so inline AI also works in the vault note viewer.

  `docs_assist.build_prompt` gets the two new canned instructions. **Continue** sends the text before the cursor (capped at 8k chars) as context. **Draft from vault** keeps `DOCS_ALLOWED_TOOLS` (search / get_note).
- **Inline diff rendering:** a ProseMirror decoration plugin, `ai-suggestion.ts`, shows streamed text as an *insertion* (green underline) and the replaced range as a *deletion* (red strike). The document itself isn't modified while streaming.
  - Accept: Tab or ⌘↵ applies one transaction, so the editor's undo stack restores it in one step.
  - Reject: Esc removes the decorations.
  - Stop while streaming discards.
  - This replaces the panel's proposal preview for selection-level actions. The side panel (`DocsAssistPanel`) stays for longer whole-document conversations.
- **Recording the change:** the accepted text is saved through the autosave path with `actor: "assistant"`. That needs spec B's write-path header (`X-Poltergeist-Actor`), so the change appears on the Changes screen and is revertible. **This is why slice A5 ships after B.**

### Focus mode and read-aloud

- **Focus mode ⌘.:** a `focus` flag in `stores/settings` (persisted). It hides the sidebar nav, JotTree, the assist panel and the toolbar, and centres the page at 72ch. Esc or ⌘. exits.
- **Read-aloud:** the Web Speech API (`speechSynthesis`). It works offline on macOS and Windows with system voices and needs no new dependency.
  - A "▶ Read" button reads the selection, or the document from the cursor.
  - The current sentence is highlighted with a decoration.
  - The voice and rate pickers are in Settings › Editor. The default voice matches the note's dominant language, so an Afrikaans note uses an Afrikaans voice when one is installed and falls back to the default otherwise.

### Graph screen

- **Where it lives:** a new `Graph` tab in `screens/vault.tsx`, next to the existing `BrainConstellation`. The constellation is the whole-vault embedding map; this is the link neighbourhood of one page.
- **Data:** `GET /v1/vault/graph?focus=<path>&depth=n` runs a BFS over the link index. Nodes carry:
  - `kind`, derived from frontmatter `artifactType`, `type`, `source` and path: `person | meeting | decision | action | ticket | doc | jot | note`;
  - `degree`;
  - `ghost: true` for a link target with no file (today `graph.py` silently drops those edges).
  - The node cap is 300, nearest first. Over the cap, the response carries `truncated: true` and the UI says so.
- **Rendering:** reuses the canvas drawing helpers in `lib/constellation-engine` and adds **`d3-force`** (small, stable) for the ego layout. Colour comes from a fixed `kind` palette in the app's design tokens; radius from `nodeRadius(degree)` (existing formula); ghosts draw as grey rings.
- **Interaction:** click re-centres the graph (the history stack has a back button); double-click opens the note in `NoteView`; a depth slider sets 1–3; a filter shows or hides kinds. It also opens from the editor: "Show in graph" in the note header.

## Data flow (inline AI, the critical path)

```
⌘J → InlineAssistPopover → window.gb.docs.assist({path|jot_id, mode, selection, instruction, target_language})
  → main/docs-stream.ts → POST /v1/docs/assist (SSE) → docs_assist.run_assist → agent turn
  ← delta events → ai-suggestion decorations update live
Accept → editor transaction → autosave PATCH (header X-Poltergeist-Actor: assistant)
  → write path (spec B): history snapshot + change record → file written
```

## Error handling

- **A block fails to parse** (bad callout header, broken mermaid): the node falls back to its plain markdown form. The note still opens, so the existing "never block opening a note" rule holds.
- **Mermaid render error:** an inline error box with the source; no throw.
- **Suggest endpoints fail or time out (300 ms):** the menu shows "no suggestions"; typing is never blocked.
- **History write fails:** the save **proceeds**, because user edits must never be lost to a history failure. The failure is logged and a once-per-session toast says "history unavailable". For non-user actors the rule reverses; see spec B.
- **Inline AI errors:** an inline error chip in the popover with Retry. Decorations are cleared and the document is untouched.
- **Speech synthesis unavailable:** the Read button is hidden.

## Testing

- **Round-trip fixtures** (gate): one fixture per new block and per degrade case. Callout with and without title, foldable `-` and `+`, the ExtractCallout look-alike staying a blockquote, a status lozenge, toc, mermaid, alt-pipe image width, aliased wikilink, person link.
- **Vitest:** the three suggestion menus (keyboard navigation, insertion forms); table toolbar commands; `ai-suggestion` plugin (decorations don't mutate the document, accept is one transaction, Esc clears); HistoryDrawer (diff and restore call); focus-mode toggling; Graph view (recentre, depth, ghost rings, truncation notice) with a fixture graph.
- **Pytest:** link index (incremental refresh on mtime, removal, ghost targets); suggest ranking; backlinks; ego-graph BFS depth and cap; history store (blob dedupe, coalescing window per actor, retention pruning, restore snapshots first); docs-assist `continue` / `translate` prompts and `path` targeting.
- **Manual:** open real vault notes containing every block in Obsidian to confirm they degrade readably.

## Slices (build order)

1. **A1 Blocks:** callouts, expand, status, TOC, mermaid with full-screen view, image resize, table controls, slash-menu items. Renderer only, no backend.
2. **A2 Linking:** link index, the suggest routes and three suggestion menus, backlinks panel.
3. **A3 History:** history store, user snapshots on save, HistoryDrawer with diff and restore. *(Spec B builds on this store.)*
4. → **Spec B** (Changes + Revert) ships here.
5. **A4 Focus mode + read-aloud.**
6. **A5 Inline AI ⌘J:** popover, decoration diff, the new modes, `path` targeting, saving with the `assistant` actor.
7. **A6 Graph:** ego-graph route with ghost nodes, the Graph tab, "Show in graph".

A1, A2 and A4 can ship in any order. A5 needs B; A6 needs A2's index.

## Decisions (approved by the user 2026-10-09)

1. **Columns.** Skip them, as recommended, or accept a custom ` ```columns ` fence whose cells aren't rich-editable inside Poltergeist? → **Skip.** Callouts and tables cover most Confluence column use.
2. **History location.** App state (`~/.ghostbrain/history`, recommended: lightweight, invisible to other tools, but not synced between machines) or inside the vault (synced, but clutters it)? → **App state.**
3. **Read-aloud voices.** The OS speech voices are free and offline but robotic. A cloud TTS would sound better but sends note text out. → **OS voices.**
