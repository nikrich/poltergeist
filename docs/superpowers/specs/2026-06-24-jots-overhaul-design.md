# Jots Overhaul — Better UX, Real WYSIWYG, Webcam Photo Capture

**Date:** 2026-06-24
**Status:** Design — awaiting review
**Author:** Jannik + Claude

## Summary

Level up the Jots experience on three fronts:

1. **Polish** the jots screen — keep the familiar three-pane layout (tree sidebar +
   focused editor) but refine list presentation (excerpt previews, photo
   thumbnails), the editor frame, and the status footer.
2. **Real WYSIWYG** — add a formatting toolbar, a `/` slash command menu, live
   markdown input rules, and **inline image rendering** to the existing
   `RichMarkdownEditor` (TipTap), while preserving the lossless markdown
   round-trip the vault depends on.
3. **The killer — webcam capture.** A `📷 capture` flow that takes a photo from
   the webcam, **saves it as a vault asset, embeds it inline** in the jot's
   markdown, **and** runs a background vision pass (`claude -p` with the image)
   that writes an **extracted-text callout** beneath the photo.

Decisions locked during brainstorming:
- Layout direction **A** (three-pane, polished).
- Photo pipeline: **image inline + vision text** (both the picture and its
  extracted content land in the note).
- Editor scope: **toolbar + slash menu + markdown shortcuts + inline images**.
- Extracted text presentation: **neon callout block** (stored as a markdown
  blockquote so it degrades gracefully outside the app).

### On "embedded in the db"

The vault *is* the database — notes are markdown files on disk. So "embedded in
the db" means the photo is written into the vault as an asset file that travels
and syncs alongside the note, and is referenced from the note's markdown. We do
**not** base64-inline the bytes into the `.md` (rejected during brainstorming).

## Architecture

Five components, each independently testable:

```
┌─────────────────────────────────────────────────────────────────┐
│ Renderer (React)                                                  │
│                                                                   │
│  JotsScreen ──> RichMarkdownEditor (TipTap)                       │
│                   ├─ Toolbar          (new)                       │
│                   ├─ SlashMenu        (new)                       │
│                   ├─ markdown input rules (StarterKit + tuning)   │
│                   └─ ImageInline node (new, gbasset:// rendering) │
│                                                                   │
│  WebcamCaptureModal (new) ──getUserMedia──> canvas──JPEG blob     │
│         │                                                         │
│         └─ gb.assets.write(bytes) ──IPC──┐                        │
│         └─ gb.assets.toUrl(path)         │                        │
└──────────────────────────────────────────┼───────────────────────┘
                                            │
┌───────────────────────────────────────── ▼ ──────────────────────┐
│ Main process (Electron)                                           │
│  • gbasset:// custom protocol → vault asset files (path-guarded)  │
│  • ipc gb:assets:write → writes bytes into the vault, returns     │
│    vault-relative path                                            │
│  • camera permission handler + NSCameraUsageDescription           │
└───────────────────────────────────────── │ ──────────────────────┘
                                            │ (existing api forwarder)
┌───────────────────────────────────────── ▼ ──────────────────────┐
│ Sidecar (FastAPI / Python)                                        │
│  • POST /v1/notes/{id}/extract-photo  (new)                       │
│      reads the asset, calls llm.client.run(image=…), returns      │
│      extracted markdown; appended to the jot body as a callout    │
│  • llm/client.run gains optional image input (claude -p)          │
│  • notes_manual: asset dir helper + path guard                    │
└───────────────────────────────────────────────────────────────────┘
```

## Component 1 — Asset infrastructure

### Storage layout
- Assets live in the vault so they commit/sync with notes:
  `90-meta/assets/jots/YYYY/MM/<jotId>-<rand>.jpg`
- Format: JPEG, quality ~0.9, capped at a sane max dimension (e.g. 1600px long
  edge) to keep files small. EXIF stripped (canvas re-encode drops it).
- Markdown references the asset by a **vault-root-relative** path so the link
  survives the jot moving from inbox → context folder on routing:
  `![photo](90-meta/assets/jots/2026/06/<id>.jpg)`

### `gbasset://` custom protocol (main process)
The renderer cannot load `file://` and reaches the sidecar only through IPC, so
on-disk images need a serving path. Register a privileged custom scheme
`gbasset` in `app.whenReady`:
- `gbasset://<vault-relative-path>` resolves to `vaultRoot/<path>`.
- **Path guard**: resolve the final path and verify it stays under the vault
  root (mirrors the Python `_guard_inside_vault`); reject traversal with a 403.
- Implemented with `protocol.handle` (Electron ≥25); registered as a privileged
  scheme via `protocol.registerSchemesAsPrivileged` before `whenReady`.

### `gb:assets:write` IPC + preload bridge
- `gb.assets.write({ jotId, bytes, ext }) → { ok, path } | { ok:false, error }`
  writes the bytes into the asset dir and returns the vault-relative path.
- `gb.assets.toUrl(vaultRelPath) → 'gbasset://…'` — pure string helper for the
  editor to map a stored path to a renderable URL.
- The vault root is already known to main (sidecar/settings); reuse that.

## Component 2 — Editor upgrade (`RichMarkdownEditor`)

The editor already round-trips markdown via `tiptap-markdown` and falls back to
source mode on parse failure. We extend the **single source of truth**,
`buildEditorExtensions()`, so the headless round-trip fixtures keep proving the
exact schema users type into.

### Inline image node
- Add a **custom Image node** (based on `@tiptap/extension-image`) whose:
  - **node attr `src`** holds the *vault-relative path* (so markdown
    serialization stays portable: `![alt](90-meta/assets/…)`).
  - **`renderHTML`** maps `src → gbasset://src` for the DOM `<img>`, so the
    picture renders inline in the editor without rewriting the stored markdown.
  - markdown serializer (tiptap-markdown image rule) emits the plain path.
- Drag-drop / paste of image files is also supported: the drop handler routes
  bytes through `gb.assets.write` then inserts the node (same path as webcam).

### Formatting toolbar
- A slim toolbar above the editor surface (matches mockup A): bold, italic,
  H1/H2, bullet list, task list, blockquote, inline code, link, and a `📷 photo`
  button on the right that opens the webcam modal.
- Buttons reflect active marks (`editor.isActive(...)`) and call existing TipTap
  commands. Hidden in `readOnly`. Lives in its own `EditorToolbar.tsx`.

### Slash menu
- Typing `/` at the start of a node opens a command palette (suggestion
  utility) listing: Heading 1/2/3, Bullet list, Task list, Quote, Code block,
  Divider, **Photo** (opens webcam), Table.
- Built with `@tiptap/suggestion`; keyboard-navigable; filters on typed text.
- Lives in `SlashMenu.tsx` + a small `slash` extension.

### Markdown input rules
- `StarterKit` already provides most (`## ` → heading, `- ` → bullet, `> ` →
  quote, ``` ``` → code). Verify task-list (`[ ] `) and ensure they remain on.
  No new heavy lifting — mostly configuration + tests.

## Component 3 — Webcam capture (`WebcamCaptureModal`)

A renderer-only modal, opened from the toolbar `📷`, the slash menu "Photo", or
the top-bar `capture` button.

States (per mockup):
1. **Live** — `navigator.mediaDevices.getUserMedia({ video })` into a
   `<video>`; a camera `<select>` (enumerateDevices, remembers last via
   settings); shutter button.
2. **Review** — freeze the current frame to a `<canvas>`; "retake" reopens the
   stream, "use photo" confirms.
3. **Insert** — encode canvas → JPEG blob → `gb.assets.write` → insert the
   ImageInline node at the cursor → fire extraction (Component 4).

Lifecycle care (this codebase is rigorous about it):
- Stop all `MediaStreamTrack`s on close/unmount/retake-cancel (no camera-light
  left on).
- Handle permission-denied and no-camera with a clear inline message, not a
  crash.

### Permissions
- macOS: add `NSCameraUsageDescription` via electron-builder
  `mac.extendInfo`.
- Electron: `session.setPermissionRequestHandler` to allow `media` for the app's
  own origin only.

## Component 4 — Vision extraction

### Backend: `POST /v1/notes/{jotId}/extract-photo`
- Request: `{ assetPath: string }` (vault-relative, validated to live under the
  asset dir).
- Reads the image, calls `llm.client.run(prompt, image=<abs path>)` with a
  concise extraction prompt ("Transcribe and summarize the readable content of
  this image as markdown; no preamble.").
- Appends the result to the jot body as an **extracted callout** and returns the
  updated body. Errors **never 500** — on failure it returns the body unchanged
  with `{ extracted:false, reason }` (consistent with the route-auto philosophy).

### `llm/client.run` image support
- Extend the existing `claude -p` wrapper to accept an optional image path and
  pass it to the CLI. **Verification step (plan phase):** confirm the exact
  Claude Code CLI mechanism for attaching an image to a `--print` call (e.g.
  `@<path>` reference) with a 5-minute spike before building on it. The wrapper
  stays the single choke point for all LLM calls (keeps Max/OAuth billing).

### Markdown shape of the callout
Stored as a blockquote with a sentinel first line so it round-trips as plain
markdown and degrades gracefully in any other editor:

```markdown
![photo](90-meta/assets/jots/2026/06/<id>.jpg)

> **Extracted from photo**
> Events flow Kinesis → handler → command store. DLQ on failure, replay
> after fix. Idempotency keyed on commandId.
```

### Editor rendering of the callout
- A custom **`extractCallout` node** recognizes a blockquote whose first line is
  the bold sentinel `**Extracted from photo**` and renders it as the neon
  left-border block (mockup A). It serializes back to exactly the blockquote
  above. If parsing is ever ambiguous it falls back to a normal blockquote — no
  data loss.
- While extraction is in flight, the editor shows a transient "extracting…"
  affordance (spinner in the callout); replaced by real content on success, or a
  small "couldn't read photo — retry" on failure.

## Component 5 — Jots screen polish (direction A)

- **Tree leaves**: show title + a one-line excerpt + a small photo thumbnail
  when the jot contains an image (thumbnail = the first asset, rendered via
  `gbasset://`).
- **Top bar**: add a `📷 capture` button next to `new` (opens the webcam modal
  and creates a fresh jot if none is selected).
- **Editor frame**: toolbar on top (Component 2), document body, status footer
  unchanged in behavior (context pill, routing status, re-route, delete).
- Visual refinements only — spacing, the neon selection treatment, mono labels
  — no change to the routing/autosave logic in `jots.tsx`.

## Data flow — capture to extracted note

1. User clicks `📷` → `WebcamCaptureModal` opens, requests camera.
2. Shutter → freeze frame → review → "use photo".
3. Canvas → JPEG blob → `gb.assets.write({ jotId })` → returns
   `90-meta/assets/jots/2026/06/<id>.jpg`.
4. Editor inserts `ImageInline(src=<that path>)`; autosave persists the
   markdown (image link now in the file).
5. Renderer calls `POST /v1/notes/{jotId}/extract-photo { assetPath }`.
6. Sidecar runs vision, appends the callout, returns updated body.
7. Editor reconciles the new body (callout node renders neon block). Autosave is
   already satisfied (server wrote it); the editor resync path
   (`setContent(markdown, false)`) handles the update without scheduling a
   redundant save.

## Error handling

- **Camera denied / absent** → inline modal message; no insert.
- **Asset write fails** → toast; nothing inserted; no orphaned markdown link.
- **Extraction fails / times out** → photo stays embedded; callout shows a
  retryable "couldn't read photo" note; never blocks the user or 500s.
- **Protocol path traversal** → `gbasset://` handler rejects anything resolving
  outside the vault.
- **Unrepresentable markdown** → existing source-mode fallback already covers
  it; the new nodes degrade to image/blockquote.

## Testing

- **Asset protocol**: unit test the path-guard (in-vault resolves, traversal
  rejected). Main-process test alongside existing `__tests__`.
- **ImageInline + extractCallout**: add fixtures to the headless round-trip
  suite (`buildEditorExtensions`) proving `![](path)` and the sentinel
  blockquote survive a parse→serialize cycle byte-for-byte.
- **Toolbar / slash menu**: RTL tests — clicking bold toggles the mark; `/h1`
  inserts a heading.
- **WebcamCaptureModal**: mock `navigator.mediaDevices` (getUserMedia +
  enumerateDevices); assert tracks are stopped on close; assert
  `gb.assets.write` + insert + extract are called on "use photo".
- **Backend extract endpoint**: mock `llm.client.run`; assert the callout is
  appended, assert failure returns body unchanged (no 500), assert 404 for
  unknown jot and 400 for an asset path outside the asset dir.
- **llm client image arg**: unit test that the image path is forwarded to the
  subprocess command.

## Build sequence (slices)

1. **Asset infra** — `gbasset://` protocol + path guard + `gb:assets:write` IPC +
   preload bridge + tests. (No UI yet; testable in isolation.)
2. **Inline images in the editor** — custom ImageInline node + round-trip
   fixtures + drag/drop. Proves images render before webcam exists.
3. **Editor toolbar + slash menu + input-rule verification** — pure editor UX.
4. **Webcam capture modal** — getUserMedia flow, permissions, insert via the
   Component-1 path.
5. **Vision extraction** — llm client image support (after the CLI spike) +
   `/extract-photo` endpoint + extractCallout node + in-flight UI.
6. **Screen polish** — tree thumbnails, top-bar capture button, spacing/visual
   refinements.

Each slice ships independently and leaves the app working.

## Out of scope (YAGNI)

- Multi-photo galleries / carousels (one inline image per insert; multiple
  inserts are fine).
- Video capture, screen capture, file-import of arbitrary attachments
  (image drag/drop falls out for free, but no PDF/doc embedding).
- Re-running extraction across already-routed historical jots (batch backfill).
- Editing/cropping the photo in-app beyond retake.
- Base64-in-markdown storage (explicitly rejected).
