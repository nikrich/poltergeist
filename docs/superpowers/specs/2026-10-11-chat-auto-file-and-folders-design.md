# Chat auto-filing and folders — design

**Date:** 2026-10-11
**Status:** approved in brainstorming, pending spec review

## Goal

Keep the chat sidebar organized without manual work, and give chats the same
folder organization docs already have:

1. A new chat files itself under the context/project it belongs to, using the
   existing event router, once, after the first reply.
2. The chat sidebar becomes a context → project → folder tree with create,
   rename, delete and drag-to-move for chats and folders — behaving exactly
   like the docs tree.

## Non-goals

- A chat's location does not change its prompt, retrieval or tools. Folders
  are organizational only.
- No re-routing of existing chats. Chats that predate this feature are never
  auto-filed (a bulk "sort unfiled" action is a possible follow-up, not in scope).
- Chats stay outside the vault in `~/ghostbrain/chats`; they are not indexed.

## Current state (origin/main)

- `ghostbrain/api/repo/chat_store.py` — one JSON file per chat; fields include
  `project` as `"context/slug"` or null. `update(title=, project=)` files a chat.
- `PATCH /v1/chat/{id}` validates `project` via `projects_repo.get_project`.
- `desktop/src/renderer/screens/chat.tsx` groups chats by project
  (`groupConversations`) with an "unfiled" group; `FileMenu` files a chat by hand.
- `ghostbrain/worker/router.py` `route_event(event, content_excerpt=...)`
  routes free text to a bare context or `context/slug` via fast rules + an
  LLM call (`router_model`, default haiku). Chat export already uses it for
  unfiled chats (`chat_export.export_conversation`).
- Docs folders: `doc_library/folders.py` (real directories), `/v1/library`
  folder routes, and `components/docs/DocTree.tsx` (drag/drop, inline rename,
  folder input, delete) — docs-specific typing, partly generic helpers in
  `components/docs/tree-model.ts`.

## 1. Data model

### Chat JSON

| Field | Type | Notes |
|---|---|---|
| `context` | `str \| null` | New. Null = unfiled. |
| `project` | `str \| null` | Now the bare slug. Requires `context`. |
| `folder` | `str \| null` | New. Path relative to the chat's location (`"q4/planning"`); null = location root. |
| `auto_filed` | `"pending" \| "done" \| "skipped"` | New. Auto-file state. |

**Legacy read:** a stored `project` of `"ctx/slug"` (and no `context`) is
split into `context="ctx"`, `project="slug"` on read. Missing `folder` → null.
Missing `auto_filed` → `"skipped"`. Files are rewritten in the new shape on
their next save; there is no migration pass.

New chats are created with `auto_filed="pending"`. A chat returned by
`create()`'s "reuse newest empty chat" path keeps or is reset to `"pending"`
(it has no messages yet).

### Folder registry

`~/ghostbrain/chats/folders.json`:

```json
{"folders": [{"context": "work", "project": "atlas", "path": "q4/planning"}]}
```

- It exists so empty folders persist. The tree is the union of registry
  entries and every folder referenced by a chat (including implied parents:
  `q4/planning` implies `q4`), so a lost or corrupt registry only loses empty
  folders. Corrupt → log a warning, treat as empty.
- Writes use the same tmp-file + rename pattern as `chat_store`.

### Invariants

- `project` set ⇒ `context` set. `folder` set ⇒ `context` set.
- A folder belongs to exactly one location: `(context, null)` or
  `(context, project)`.
- Folder path segments are validated like docs `scope.clean_rel`: no empty
  segments, no `.`/`..`, no leading `/`, no backslashes.
- **Project rename:** `projects_repo.rename_project` also rewrites chats and
  registry entries for the old slug (same hook point that re-stamps notes).
- **Project archive:** chats and folders stay; the tree shows the project in
  an "Archived" group under its context, as docs do. Moving *into* an archived
  project is rejected (422).
- **Unknown/archived context** (removed from routing.yaml): chats under it
  are shown in the Unfiled section with an "unknown location" badge; their
  stored fields are left untouched.

## 2. Auto-filing

- **Trigger:** in `chat.py` `_stream_turn`, after the assistant message is
  persisted, if the chat has exactly one assistant message and
  `auto_filed == "pending"`.
- **Off the stream path:** routing runs on a background thread so the reply
  is never delayed. The SSE stream does not wait for it.
- **Call:** `router.route_event({"source": "chat", "title": conv["title"]},
  content_excerpt=<first user message + first assistant reply, ~4k chars>)`.
- **Apply:** under the store lock, re-read the chat. If `auto_filed` is no
  longer `"pending"` (user moved it meanwhile) or the chat was deleted,
  discard the decision. Otherwise:
  - decision `needs_review`, confidence < `thresholds.reject_below`, or method
    `fallback` (LLM error) → leave unfiled;
  - else set `context` / `project` from the decision, `folder=null`.
  - Either way set `auto_filed="done"`. Never retried.
- **Notify:** since routing finishes after the stream may have closed, the
  renderer learns about it by polling: after a turn completes, the renderer
  refetches the chat until `auto_filed != "pending"` (short interval, capped
  at ~30s). When the chat moved, it invalidates the tree and shows the filed
  notice.
- **Manual moves win:** every `PATCH` that changes location sets
  `auto_filed="done"`.
- **Export reuse:** `chat_export.export_conversation` uses the chat's
  `context`/`project` when set (already does for `project`; extend to
  context-only chats), so filed chats don't trigger a second router call.

## 3. API (`/v1/chat`)

| Route | Body | Behaviour |
|---|---|---|
| `GET /tree` | — | `{unfiled: ChatSummary[], scopes: [{context, project, name, archived, folders, chats}]}` — a flat scope list (bare context, then its projects) mirroring `LibraryTree.scopes`. Folder node: `{name, path, folders, chats}`. Contexts in routing.yaml order; empty contexts included so they are drop targets; empty archived projects omitted. |
| `PATCH /{id}` | `{title?, context?, project?, folder?}` | Title renames. Location fields move; `context: null` unfiles (clears project + folder). Validates context exists, project active; 422 otherwise. Moving to a folder path that doesn't exist creates it. Location change sets `auto_filed="done"`. Omitted vs explicit null distinguished as today. |
| `POST /folders` | `{context, project?, path}` | Create; 409 if exists, 422 on invalid path/location. |
| `PATCH /folders` | `{from: FolderRef, to: FolderRef}` | Rename and/or move, including across locations. Rewrites contained chats' location + folder prefix and registry entries for the subtree. 409 if destination exists, 422 if moving into itself. |
| `DELETE /folders` | FolderRef (query or body, mirror `/v1/library`) | Only empty folders (no chats, no subfolders); 409 otherwise. |

`FolderRef = {context, project: str | null, path}`.

`GET ""` (list) remains, gaining the new fields, for existing callers.
`ConversationSummary` / `Conversation` gain `context`, `folder`,
`auto_filed`; `project` becomes the bare slug in responses.

**Backend layout:** new `ghostbrain/api/repo/chat_folders.py` (registry,
validation, tree building, folder move/delete); `chat_store` gains
`move(id, context, project, folder)`. A module-level lock in `chat_store`
guards all read-modify-write cycles, shared with `chat_folders` and the
auto-file apply step.

## 4. UI

### Shared tree component

Extract the generic parts of `components/docs/DocTree.tsx` into
`components/tree/`:

- context → project → folder nesting with expand/collapse;
- folder drop targets and folder/leaf drag sources (HTML5 DnD, MIME + payload
  encoding generalized from `tree-model.ts`);
- `FolderInput` (create/rename inline), delete button, `isInside` guard;
- generic over the leaf type: callers provide a leaf renderer and a leaf drag
  payload, plus callbacks (`onMoveLeaf`, `onMoveFolder`, `onCreateFolder`,
  `onRenameFolder`, `onDeleteFolder`).

`DocTree` becomes a thin wrapper. Existing docs tests must pass unchanged.

### Chat sidebar

- New `ChatTree` replaces `groupConversations` + the grouped list in
  `chat.tsx`. "Unfiled" pinned top (drop target that unfiles), then contexts
  → projects → folders.
- Drag chats and folders onto Unfiled / context / project / folder. "+" on a
  location or folder creates a subfolder. Inline rename + delete for folders.
  Chat rows keep their existing rename/delete.
- Active chat highlighted; its ancestors auto-expand.
- `FileMenu` becomes a "Move to…" menu listing locations and folders — the
  non-drag path for keyboard users.
- Filed notice: unobtrusive line under the chat header —
  "Filed under Work / Atlas · Undo". Undo = `PATCH {context: null}`.

### Hooks

`useChatTree`, `useMoveChat`, `useCreateChatFolder`, `useMoveChatFolder`,
`useDeleteChatFolder`; all mutations invalidate the tree and conversation
queries. Existing `useUpdateConversation` callers move to `useMoveChat`
where they set location.

## 5. Testing

**pytest**
- legacy `"ctx/slug"` read → split fields; missing fields defaulted.
- `chat_store.move`, folder create/move/rename/delete, registry rebuild from
  chats when `folders.json` is missing/corrupt, implied parent folders.
- `PATCH /{id}` and folder routes: validation, 409/422 cases, move into
  archived project rejected, folder move rewrites contained chats.
- Auto-file: runs only after first reply on `pending`; manual move before
  apply wins; low confidence / needs_review / LLM error → unfiled + `done`;
  never runs for `skipped` chats. Router is stubbed.
- `rename_project` carries chats and registry entries.

**vitest**
- shared tree with fake leaves: drag/drop payloads, `isInside` guard,
  inline create/rename/delete.
- `ChatTree`: drops call the right mutations; Unfiled drop unfiles.
- Filed notice + Undo.
- Existing `DocTree` tests unchanged and green; `ConversationFolders` tests
  rewritten for the tree.

**Manual smoke:** run the app, start a chat about a known project, confirm it
files itself; drag chats/folders across locations; undo; restart and confirm
empty folders persist.

## Delivery

One PR (the user asked for build + release in one go): backend, API, auto-filing, shared tree extraction, chat tree UI.
