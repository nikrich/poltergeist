# Docs Library — Design

**Status:** Approved in conversation 2026-10-09
**Origin:** The user wants to upload documents into Poltergeist, view them in-app, and organise
them in a folder structure inside projects, moving them around freely. The docs must also feed
the AI: chat, search and MCP answer from their contents.
**Mockups:** `.superpowers/brainstorm/74709-1791564766/content/docs-layout.html` (directions A/B/C)
and `docs-combined.html` (the approved A+B layout and the `/docs` picker in a jot). Not committed.

## Decisions (from the conversation)

- **Purpose:** a **reference library plus AI context**. The originals are kept and viewable, and
  their extracted text is indexed like any other vault note.
- **Separate from jots.** Docs have their own screen and their own folder trees. Jots link to docs
  through a **`/docs` slash picker** that inserts a wikilink. The user is reworking jots on
  another branch, so jot linking ships last.
- **Hierarchy:** each project, plus each context's "unfiled" area, has its own nested folder tree.
  Docs and folders can be moved **within and across projects and contexts**.
- **Storage (approach A):** real files in real vault folders, each with a companion `.md` note next
  to it. The vault is the catalog: no manifest and no database. Rejected alternatives: a
  content-addressed blob store with a JSON manifest (folders invisible outside the app), and
  SQLite (too heavy; the vault is the source of truth everywhere else).
- **Viewable kinds in v1:** PDF, images, DOCX/XLSX (shown as their extracted text/table, not a
  pixel-perfect render), and markdown/text/code.
- **Layout:** the "Reader" layout (tree · document · inspector), plus a per-folder **list/grid
  switch** where grid shows thumbnail cards. The look follows the existing design tokens (ink
  background, neon accent, mono labels) and the mockups.
- **Extras in scope:** an AI summary ("what poltergeist knows"), an "ask about this doc" box, and
  "linked in N jots" backlinks.

## Non-goals

- Importing from Drive, Confluence or other connectors into the library. Those connectors keep
  their own notes.
- Pixel-perfect Office rendering, editing docs in-app, versioning or revision history.
- Sharing, permissions, comments or annotations on docs.
- Deleting projects. The project registry stays archive-only.
- Rewriting existing links when a doc is renamed. Links target the stable note basename, not the
  title (see §2).

## Design

### 1. Vault layout

```
20-contexts/{ctx}/docs/<folders…>                       ← context "unfiled" tree
20-contexts/{ctx}/projects/{slug}/docs/<folders…>       ← one tree per project
    specs/
        Payments API v2.pdf                             ← original, byte for byte
        payments-api-v2-3f9a1c.md                       ← companion note
```

- A **docs root** is any `docs/` directory at one of those two positions. The library never reads
  or writes outside a docs root.
- The **companion note** filename is `<slug(title at upload)>-<doc_id[:6]>.md`. `doc_id` is
  random, so the basename is unique even when the same file sits in two projects. Upload checks
  for a basename collision and redraws the id if one happens. Obsidian-style wikilinks by
  basename therefore keep working after a move.
- Companion note frontmatter:

```yaml
doc_id: 3f9a1c7b20de            # random 12 hex, assigned at upload; stable forever
sha256: 9b2e…                   # content hash, used only for duplicate detection
source: doc-library
title: Payments API v2          # display title; editable (rename)
original: Payments API v2.pdf   # sibling filename of the original
kind: pdf                       # pdf | image | docx | xlsx | text | opaque
mime: application/pdf
size: 2150331
pages: 24                       # pdf only, when known
created: 2026-10-09T10:12:03+00:00
context: sanlam
project: payments-platform      # absent for context-unfiled docs
index_status: ok                # ok | failed | pending
summary: "…"                    # §5, absent until generated
```

- Note body: the extracted text (via `attachment_extract`), the image caption (via
  `attachment_caption`; no embed, because an embed path would break when the doc moves and the
  viewer shows the original anyway), or the text/markdown content for text kinds (code fenced
  with its language). **Opaque** files (any other
  type) are accepted and stored with metadata only and an empty body.
- Folders are plain directories. An empty folder holds a `.keep` file so sync tools keep it.

### 2. Backend module — `ghostbrain/api/repo/doc_library.py`

Separate from `chat_attachments.py`, but reuses `attachment_extract` (PDF/DOCX/XLSX text) and
`attachment_caption` (image captions). The shared kind classification and size limits are pulled
out of `chat_attachments` into a small helper both modules import.

- **Doc index.** An in-memory map `doc_id → (note_path, original_path, frontmatter)`, built by
  walking every docs root for `*.md` with `source: doc-library`. It's rebuilt when any docs root's
  directory mtimes have changed since the last build (checked on each request; rebuilding is
  cheap at personal-vault scale). All API calls address docs by `doc_id`, never by path.
- **Upload** `(context, project|None, folder, filename, mime, content)`:
  1. Check the context exists and, if a project is given, that the project exists and isn't
     archived (reuses `projects.get_project`).
  2. Classify the kind and enforce the limits (§7).
  3. Compute `sha256`. If a doc with the same hash already exists **in the same project
     scope**, return it (`duplicate: true`) and write nothing. A copy in another scope is a new
     doc with its own random `doc_id`.
  4. Resolve the target folder inside the scope's docs root (path guard, §7) and create it.
  5. Write the original. A filename clash in the folder becomes `name (2).ext`, `name (3).ext`, ….
  6. Extract the body. On failure, keep the original, write the note with `index_status: failed`
     and an empty body, and the upload still succeeds.
  7. Write the note atomically (tmp + rename) and update the index.
  8. Enqueue the summary job (§5).
- **Move doc** `(doc_id, context, project|None, folder)`: path-guard the destination and resolve
  name clashes, then **move the original first, then the note**, then rewrite the note's
  `context`/`project`/`original`. If the note move fails, the original is moved back. Cross-scope
  moves are allowed.
- **Rename doc** `(doc_id, title)`: updates the frontmatter `title` and renames the original to
  `<title><ext>` (with clash suffix). The note basename stays the same, so links don't break.
- **Delete doc:** both files go to the OS trash (`send2trash`, a new small pure-Python
  dependency). Nothing is unlinked permanently.
- **Folders:** create, rename/move (a directory move inside or across docs roots), and delete
  (**only empty folders**, apart from `.keep`; otherwise 409).
- **Tree** `(context?, project?)`: returns nested folders and docs per scope, plus a separate
  **needs attention** list:
  - orphan notes (the original is missing)
  - unclaimed originals (a file in a docs root with no note pointing at it, e.g. dropped in by
    Finder)
  - notes with `index_status: failed`

  Each one has a repair action: adopt the unclaimed original (runs the upload pipeline in place),
  remove an orphan note (to the trash; re-uploading the file recreates it), or retry indexing.
- **Backlinks** `(doc_id)`: scan vault `*.md` for `[[<note-basename>` (with or without an alias),
  excluding docs roots, and return title + path + date for each. The result is cached per
  doc_id and invalidated by the same mtime check as the index plus the jot-save signal.
- **Search** `(q, prefer_project?)`: a fuzzy match on title and folder path, with
  `prefer_project` docs ranked first. Feeds the `/docs` picker and the ⌘P finder.

### 3. API — `ghostbrain/api/routes/library.py` (prefix `/v1/library`)

`/v1/docs` is taken by the docs assistant, so the library uses `/v1/library`. Uploads use base64
JSON, one file per request, the same as chat attachments (no multipart dependency). That also
gives each card its own success or failure.

```
GET    /v1/library/tree?context=&project=          scopes → folders/docs + needsAttention
POST   /v1/library/docs                            {context, project?, folder, name, mime, content_b64}
GET    /v1/library/docs/{doc_id}                   metadata + body text + summary
PATCH  /v1/library/docs/{doc_id}                   {title?} | {context, project?, folder}
DELETE /v1/library/docs/{doc_id}                   → OS trash
POST   /v1/library/docs/{doc_id}/reindex           retry extraction + summary
GET    /v1/library/docs/{doc_id}/backlinks
POST   /v1/library/folders                         {context, project?, path}
PATCH  /v1/library/folders                         {from:{context,project?,path}, to:{…}}
DELETE /v1/library/folders?context=&project=&path=   (empty only)
POST   /v1/library/attention/adopt                 {context, project?, folder, name}
POST   /v1/library/attention/remove-orphan         {doc_id}
GET    /v1/library/search?q=&project=
```

Errors: 404 unknown doc/folder/scope · 409 non-empty folder delete, or a project that's archived
or missing · 413 over the size limit · 400 path escape or invalid base64 · 422 validation.

### 4. Desktop — main process

- **`gbdoc://` protocol** (`desktop/src/main/doc-protocol.ts`), modelled on `gbasset://`: it
  serves raw files whose resolved path is inside a docs root under the vault, and returns 403
  otherwise. The renderer uses it for `<img>`, pdf.js and text fetches, with no bearer token.
- Uploads: the renderer reads files (drag-drop or picker) and calls the existing API forwarder
  with base64 JSON. "Open in…" / "reveal in Finder" go through `shell.openPath` /
  `showItemInFolder`.

### 5. AI: summary, ask, indexing

- **Indexing:** companion notes are ordinary `.md` files, so the existing semantic refresh picks
  them up. No indexer changes.
- **Summary:** a background job after upload/reindex. It sends the first ~12k characters of the
  body to `get_provider()` with a "2–3 sentence factual summary" prompt and an **explicit
  budget** (never the claude client's $0.50 default). The result goes into `summary:` in the
  frontmatter. Opaque/empty docs are skipped. A failure is logged and leaves no summary; it
  never changes `index_status`.
- **Ask about this doc:** the inspector's input starts a new chat conversation and sends the
  question with the companion note's path as an attachment (the existing `gb:chat:send`
  `attachmentPaths`), then switches to the Chat screen.

### 6. Desktop — renderer

New `docs` screen in the left rail (book icon), between jots and vault.

- **Tree pane** (`components/docs/DocTree.tsx`): contexts → projects (coloured dot) and
  "unfiled" → folders → docs with kind chips (PDF/IMG/DOCX/XLSX/MD, plus a grey chip for
  opaque). Counts per node. A **needs attention** row appears when the list isn't empty. The
  context menu has new folder / rename / delete / reveal. **Drag and drop:** docs and folders
  onto any folder or project node, including across projects; the drop target gets a dashed neon
  outline. OS files dropped anywhere upload into the target folder.
- **Main pane:**
  - **Folder selected:** list view (sortable name/kind/modified/size) or grid view (thumbnail
    cards). The choice is remembered per folder in `localStorage`.
  - **Doc selected:** the reader. Breadcrumb, `indexed` / `failed` pill, open-in / ⋯ menu, and a
    viewer chosen by kind:
    - PDF → **pdf.js** (`pdfjs-dist`) canvas pages, with a floating pager (page n / N, zoom)
    - image → fit/zoom `<img>`
    - markdown → existing `MarkdownBody`
    - text/code → existing `MarkdownBody` over the note body (code is already fenced with its
      language)
    - docx/xlsx → the extracted text, rendered via `MarkdownBody` (tables keep their markdown
      tables)
    - opaque → a placeholder card with "open in…"
  - Esc from the reader returns to the folder view.
- **Thumbnails:** images use the image itself (CSS-scaled). PDFs render page 1 with pdf.js,
  cached in memory per doc_id for the session. DOCX/XLSX/MD/text get a typographic preview drawn
  from the first lines of the body.
- **Inspector** (`components/docs/DocInspector.tsx`): title (inline rename), kind/size/added/
  project, the **✦ what poltergeist knows** card (summary, or a "summarising…" shimmer, or a
  "retry" when indexing failed), **linked in N jots** (click to open the jot), and the **ask
  about this doc** input.
- **Upload feedback:** each in-flight file shows as a ghost row/card with a neon progress bar
  (indeterminate per file). Errors appear inline on the card with the reason (too large, …), and
  a toast covers the batch.
- **⌘P finder:** a quick-open over `/v1/library/search`.
- Data hooks in `lib/api/hooks.ts` (react-query), following the existing patterns.

### 7. Limits and safety

- Limits match chat attachments: **20 MB** documents/images/opaque, **1 MB** text.
- **Path guard:** every client-supplied folder path is normalised, rejected if it's absolute or
  contains `..` segments, and the resolved path must stay under the scope's docs root (400
  otherwise). `gbdoc://` applies the same check in the main process.
- Writes are atomic (tmp + rename) for notes. Moves use rollback ordering (§2). A crash between
  the two steps leaves an orphan or unclaimed original, which shows up in **needs attention**;
  nothing is deleted silently.

### 8. Jot linking — `/docs`

- A TipTap extension (`lib/editor/doc-link.ts`) on `@tiptap/suggestion` (already a dependency),
  triggered by `/docs`. The popover lists `/v1/library/search` results with the jot's project
  first, plus kind chip and path. ↑↓ / ↵ insert / ⇧↵ insert and open / esc.
- Inserts `[[<note-basename>|<title>]]`, so it round-trips through `tiptap-markdown` and the
  existing wikilink restore, and Obsidian resolves it by basename.
- Rendering: wikilinks whose target matches a library note basename render as a **doc chip**
  (kind chip + title). Hovering shows a card (thumbnail, summary, page count, folder). Clicking
  navigates to the Docs screen with that doc open. Other wikilinks are unchanged.
- If the jots branch adds a general slash menu, `/docs` becomes one entry in it rather than a
  standalone trigger.

## Delivery slices

Each slice is one PR and one release, the same way chat attachments shipped.

1. **Library core:** §1–4, §6 without the AI parts of the inspector, §7. Upload, tree,
   drag-to-move, folders, viewers for every kind, list/grid + thumbnails, needs attention, ⌘P.
2. **Intelligence:** §5. Summary job, the "what poltergeist knows" card, reindex/retry, ask
   about this doc.
3. **Jot linking:** §8 plus backlinks (the API and inspector section). Rebased onto the user's
   jots branch once it merges.

## Error handling

| Situation | Behaviour |
|---|---|
| File over the size limit | 413; card shows "too large (max 20 MB)"; nothing written |
| Unknown file type | Accepted as `opaque`; viewer shows "open in…" |
| Extraction/caption fails | Original kept; `index_status: failed`; amber badge + retry |
| Summary fails | Logged; no summary; doc otherwise fine |
| Duplicate upload, same project | Existing doc returned; toast "already in library", reveals it |
| Name clash in folder | `name (2).ext` |
| Move fails halfway | Original moved back; 500 with reason; if the rollback also fails → needs attention |
| Delete a non-empty folder | 409; UI says to move or delete its contents first |
| Archived/missing project target | 409/404; drop target disabled for archived projects |
| Path escape attempt | 400 (API) / 403 (`gbdoc://`) |
| File changed in Finder | Next index rebuild picks it up; unclaimed originals show under needs attention |

## Testing

- **Backend (pytest):** temporary vault fixture, with `GHOSTBRAIN_STATE_DIR` sandboxed. Covers:
  - upload of each kind, opaque, duplicate in the same scope vs a different scope, and name clash
  - failed extraction still keeps the original
  - moves within a folder, across projects and into a context's unfiled area
  - a forced failure halfway through a move (rollback), rename keeping the note basename, and
    delete to trash (`send2trash` patched)
  - folder CRUD and non-empty delete
  - path-escape attempts on every endpoint that takes a path
  - needs-attention detection and each repair action
  - index rebuild when a mtime changes
  - backlinks parsing (alias / no alias / docs roots excluded)
  - search ranking
  - summary job with the provider stubbed, the budget passed, and failure isolated
  - route tests for status codes
- **Desktop main (Vitest):** the `gbdoc://` path guard (inside/outside/`..`/symlink-free
  resolution).
- **Renderer (Vitest + RTL):**
  - DocTree grouping, counts and drop-target highlighting
  - drag a doc → PATCH payload
  - list/grid switch persisting per folder
  - viewer chosen per kind (pdf.js mocked)
  - inspector states (summary / summarising / failed / backlinks)
  - upload ghost cards and error states
  - `/docs` suggestion: filtering, project-first ordering, keyboard, the inserted markdown
  - doc-chip rendering and click navigation
- **Manual:** the running app (the `run` skill) before each release. Upload a real PDF, image,
  DOCX and XLSX; drag across projects; check the files on disk in Finder; ask in chat about an
  uploaded doc and confirm it's cited.
