# Jot folders — design

**Date:** 2026-10-12
**Status:** approved in brainstorming, pending spec review

## Goal

Give the Jots sidebar the same organization chats and docs have: a
context → project → folder tree with create, rename, delete and drag-to-move
for jots and folders, rendered by the shared `ScopeTree`.

## Non-goals

- Auto-routing is unchanged: it picks context/project only. A freshly routed
  jot lands at its location root; folders are manual organization.
- Folders do not exist on disk. Jot files stay where they are today; Obsidian
  does not see jot folders.
- No month grouping. It is removed, not kept alongside folders.
- `GET /v1/notes?source=manual` (flat list + search) stays as is.

## Current state (origin/main)

- Jots are vault files at `20-contexts/<ctx>/notes/<id>.md` or
  `20-contexts/<ctx>/projects/<slug>/<id>.md` (inbox:
  `INBOX_REL/<id>.md`). Frontmatter carries `context`, `project`,
  `routingStatus` and routing metadata.
- `notes_manual.move_jot` moves the file via `vault_write` (op `move`) and
  rewrites `context`/`project`/routing fields; it is used by the router, the
  manual `POST /v1/notes/{id}/route` and chat export.
- `components/JotTree.tsx` groups `useJots()` rows by context → project →
  month. `screens/jots.tsx` hosts it alongside a search box.
- Chats (#178): `chat_folders.py` + `folders.json` registry, `GET /v1/chat/tree`,
  `/v1/chat/folders` CRUD, `ChatTree.tsx` over `components/tree/ScopeTree.tsx`.
  `projects_repo.rename_project` calls `chat_folders.repoint_project`.

## 1. Data model

### Jot frontmatter

| Field | Type | Notes |
|---|---|---|
| `folder` | `str \| null` | New. Path relative to the jot's location (`"q4/planning"`). Absent/null = location root. |

- Only meaningful when `routingStatus == "routed"` and `context` is set.
  Pending / manual-review jots never carry a folder.
- Written through `vault_write` (actor `USER` for user moves), so page history
  records folder moves like any other frontmatter change.
- Missing on existing jots → root. No migration pass.

### Folder registry

`state_dir() / "jot-folders.json"`:

```json
{"folders": [{"context": "work", "project": "atlas", "path": "q4/planning"}]}
```

Same semantics as the chat registry:

- It exists only so empty folders persist. The folder set is
  registry ∪ every folder referenced by a jot ∪ their implied parents
  (`q4/planning` implies `q4`). Lost/corrupt registry → log a warning, treat as
  empty; only empty folders are lost.
- Writes use tmp-file + `os.replace`.
- Path segments validated with `doc_library.scope.clean_rel` (no empty
  segments, no `.`/`..`, no leading `/`, no backslashes).
- One module-level `threading.RLock` serializes every registry
  read-modify-write and every multi-jot folder operation.

### Shared helpers

`chat_folders.py` and the new `jot_folders.py` share: path cleaning, location
validation (`check_location`), the error classes, the registry load/save, and
the tree-node builder. These move into `ghostbrain/api/repo/scoped_folders.py`
(parameterized by registry path and leaf summarizer); `chat_folders.py`
re-exports what its callers import so existing imports keep working. No
behaviour change for chats.

### Invariants

- `folder` set ⇒ `context` set and jot routed.
- A folder belongs to exactly one location: `(context, null)` or
  `(context, project)`.
- **Routing clears the folder.** Every `move_jot` call that does not pass a
  folder (router, manual route, route-auto, chat export) writes
  `folder: DELETE_FIELD`. `mark_manual_review` also deletes it. A location
  change makes the old path meaningless.
- **Project rename:** `rename_project` calls `jot_folders.repoint_project`
  (registry entries only — jot files already move and re-stamp `project:`
  through the existing hook; `folder` is relative, so it survives untouched).
  Undo hook mirrors the chat one.
- **Project archive:** jots and folders stay; the tree shows the project in the
  context's archived group as chats/docs do. Moving *into* an archived project
  → 422.
- **Unknown context** (removed from routing.yaml) or unknown project: the jot
  is listed in the Unrouted section with `unknownLocation: true`; its files and
  fields are untouched.

## 2. Backend

### `notes_manual.move_jot`

Gains `folder: str | None = None`. The value is written into the same
`vault_write` call (`folder` or `DELETE_FIELD`). The `src == dst` short-circuit
no longer returns early when only the folder changes: it does a fields-only
write (`set_frontmatter_fields`-style) for `folder` and returns.

### `ghostbrain/api/repo/jot_folders.py`

- `create_folder(context, project, path)` — validate location + path; 409 if it
  exists; add to registry (parents implied).
- `move_folder(src, dst)` — rename or move a folder, including across
  locations. 409 if `dst` exists, 422 if `dst` is inside `src`. For every jot
  under `src` (the folder and its descendants), compute the new folder path and:
  - same location → fields-only write of `folder`;
  - other location → `move_jot(..., to_context, to_project, folder=new,
    method="user", confidence=1.0, reasoning="moved with folder")`.
  Registry entries under `src` are rewritten. Per-jot failures are collected;
  the call raises a `FolderMoveIncomplete` (409) listing the jot ids that did
  not move, after moving the rest (no rollback — each jot move is atomic and
  its own history entry, and the tree reflects reality on next fetch).
- `delete_folder(context, project, path)` — 409 if any jot or subfolder is
  inside (same as chats); otherwise drop it from the registry.
- `move_jot_to(jot_id, context, project, folder)` — validate location + path,
  then `move_jot(..., method="user", folder=folder)`. Moving a pending or
  manual-review jot this way files it (routingStatus → `routed`). If `folder`
  is not yet in the folder set it is added to the registry.
- `repoint_project(context, old_slug, new_slug)`.
- `tree()` — reads jots through the existing listing (`list_jots`, all pages),
  returns:

```json
{
  "inbox":    [JotTreeItem],   // routingStatus == "pending"
  "unrouted": [JotTreeItem],   // manual_review, or unknown context/project
  "scopes":   [{"context","project","name","archived","folders":[...],"jots":[...]}]
}
```

  Jots within each folder/root and in both lists sort by `created` descending.
  Archived project scopes with no jots and no folders are omitted. Scope order
  matches the chat tree (contexts from routing config, bare context first, then
  projects by name).

`JotTreeItem` = existing `NoteListItem` fields + `folder` + `unknownLocation`.
`NoteListItem` gains `folder: str | None = None` so the flat list carries it too.

### Routes (`ghostbrain/api/routes/notes.py`)

Declared **before** the `/{jot_id}` routes so `tree`/`folders` are never read
as a jot id.

```
GET    /v1/notes/tree                          → JotTree
POST   /v1/notes/folders                       {context, project?, path} → FolderRef
PATCH  /v1/notes/folders                       {from: FolderRef, to: FolderRef} → FolderRef
DELETE /v1/notes/folders?context=&project=&path=
PATCH  /v1/notes/{jot_id}/location             {context, project?, folder?} → moved jot
```

Error mapping reuses the chat `_folder_call` pattern (422 invalid location /
path, 404 folder or jot not found, 409 exists / not empty / move incomplete).
Request/response models reuse `FolderRef` / `MoveFolderRequest` from the chat
models; new `JotTreeItem`, `JotFolderNode`, `JotScope`, `JotTree`,
`MoveJotRequest` live in `models/note.py`.

## 3. Desktop

### Types and hooks

- `shared/api-types.ts`: `JotTreeItem`, `JotFolderNode`, `JotScope`,
  `JotTree`; `folder?: string | null` on `JotListItem`.
- `lib/api/hooks.ts`: `useJotTree`, `useCreateJotFolder`, `useMoveJotFolder`,
  `useDeleteJotFolder`, `useMoveJot`. Mutations invalidate the jot tree, the
  jot list and the selected jot. `useJotTree` polls on the same interval as
  `useJots` today (5 s). Existing route/create/delete jot mutations also
  invalidate the tree.

### `components/JotTree.tsx` (rewritten)

Built on `ScopeTree` exactly like `ChatTree`:

- `JOT_CODEC` drag codec with mime `application/x-gb-jot`.
- `renderLeaf` → one button row: title (truncated) + short date
  (`Oct 12`, year added when not the current year); active row uses the
  existing selected styling.
- `onMoveLeaf` → `useMoveJot`; `onMoveFolder` / `onRenameFolder` →
  `useMoveJotFolder`; `onCreateFolder` / `onDeleteFolder` → the folder hooks.
  Errors toast, as in `ChatTree`.
- No `onSelectFolder` (clicking a folder toggles it), no `onUploadFiles`.
- **Inbox** and **Unrouted** render as fixed collapsible sections above the
  scopes, same row component, draggable into the tree (drop = file there).
  Hidden when empty. Unrouted rows with `unknownLocation` show the
  "unknown location" badge chats use.
- Selecting a jot reveals its folder (`revealKeys`), so a jot opened from
  elsewhere (search, link) is visible in the tree.

### `screens/jots.tsx`

- The tree pane uses `useJotTree`; the selected jot is looked up in the tree
  (inbox, unrouted, or any scope) instead of `useJots().items`.
- Non-empty search box → the pane shows a flat result list from
  `useJots({ q })` (newest first, same row component) instead of the tree.
- Creating a new jot is unchanged (it lands in the inbox, then routes).

## 4. Testing

**pytest**
- `jot_folders`: registry round-trip + corrupt file; implied parents; path
  validation; create / rename / nested move / delete-not-empty; move into
  archived project → 422; folder move across locations moves every jot file
  (context/project/folder correct) and reports partial failure; tree shape
  (inbox, unrouted, unknown location, archived-empty omitted, sort order).
- `move_jot`: routing without a folder clears an existing `folder`;
  same-location folder-only change writes `folder` without moving the file.
- `mark_manual_review` clears `folder`.
- `rename_project` repoints jot registry entries (and undo on failure).
- Routes: each endpoint's happy path + error codes; `/v1/notes/tree` and
  `/v1/notes/folders` are not captured by `/{jot_id}`.
- `chat_folders` tests keep passing unchanged after the shared-helper
  extraction.

**Vitest**
- `JotTree`: renders scopes/folders/jots from a fixture; inbox/unrouted
  sections; drag jot → folder calls move; create / rename / delete folder;
  reveal on selection.
- Hooks: invalidation after each mutation.
- `JotsScreen`: search switches to the flat list; selecting from the tree opens
  the jot.
- The month-grouping tests in `JotTree.test.tsx` are replaced.

Verification before merge: `pytest`, `npm run typecheck` (tsc -b), Vitest, and
a demo-mode screenshot of the new tree.
