# Poltergeist Jots — Design

**Date:** 2026-05-14
**Status:** Draft, awaiting implementation plan

## Problem

There's no way to persist a passing thought into the vault. Today's vault is fed entirely by connectors (Gmail, Slack, GitHub, Jira, Confluence, Calendar, Claude Code/Desktop) and the recorder. If a thought needs to live in the vault — to be searched, surfaced in digests, recalled by the "ask" flow — the user has to open Obsidian, choose a folder, and create a file by hand. That friction kills the use case.

**The ask:** jot a thought → it lands in the vault → it's indexed → it shows up when the user asks the brain something related.

## Goals

1. **Frictionless capture** — get a thought out of the user's head in under 2 seconds, from anywhere on the OS.
2. **Auto-routing** — the user shouldn't classify their own thoughts; reuse the LLM router that already handles recorder transcripts.
3. **Recall via the existing "ask" surface** — jots are first-class candidates in `/v1/answer` results alongside emails, slack threads, transcripts.
4. **A focused editor for revisiting jots** — tree + markdown editor scoped to user-authored notes only.

## Non-goals

- **Not an Obsidian replacement.** For long-form note-taking, multi-pane editing, graph view, plugins — the user opens Obsidian. Poltergeist's editor is just for the jots the user captures through Poltergeist.
- **Not an editor for connector-ingested content.** Transcripts, emails, slack messages, etc. stay read-only inside Poltergeist. They're huge, noisy, and editing them inline would conflict with the canonical source.
- **No immediate-consistency index.** The semantic index refresh runs every 15 minutes. End-to-end latency from capture to "answerable" is bounded by that interval, not by the capture path. Accepted.

## Architecture overview

```
                ┌─ desktop app ─────────────────────────────┐
                │                                           │
   ⌥-J  ───▶  overlay window (480×260)                      │
                │   POST /v1/notes  ─┐                      │
                │                    │                      │
                │  jots screen   ◀───┼──  GET/PATCH/DELETE  │
                │  (tree + editor)   │                      │
                └────────────────────┼──────────────────────┘
                                     │
                ┌─ python sidecar ───▼──────────────────────┐
                │                                           │
                │  POST /v1/notes                           │
                │   1. write 00-inbox/raw/manual/{id}.md    │
                │   2. ghostbrain.worker.router.route_event │
                │   3. move to 20-contexts/{context}/notes/ │
                │   4. audit-log decision                   │
                │                                           │
                │  scheduler (every 15m)                    │
                │   semantic refresh — embeds new notes,    │
                │   updates `related:` frontmatter          │
                │                                           │
                │  /v1/answer  ◀── jots appear as citations │
                └───────────────────────────────────────────┘
```

The flow is built almost entirely from existing infrastructure:
- **Routing:** `ghostbrain.worker.router.route_event` already supports `source` discriminators (used today for `claude-code`, `slack`, `gmail`, etc.); manual jots use `source: "manual"`.
- **Indexing:** `ghostbrain.semantic.refresh` walks `vault/20-contexts/` and embeds anything new. A jot landing in the right context folder is automatically picked up by the next 15-minute tick.
- **Ask flow:** `/v1/answer` queries the embedding index; routed jots become candidates with no special handling.

## Capture flow (write path)

### Hotkey overlay

- **Trigger:** `⌥-J` global accelerator (macOS), configurable in `settings.json` under `hotkeys.jotOverlay`.
- **Window:** frameless, transparent, `alwaysOnTop: true`, `skipTaskbar: true`, `vibrancy: 'hud'`, 480×260, centered on the focused display.
- **Lifecycle:** created lazily on first press, then kept alive (`hide()` on save/cancel, never `close()`). First paint is instant after the first invocation.
- **Contents:** autofocused multi-line textarea, footer hint `⌘↵ save · esc cancel`. No title field, no tag chips, no context picker — just the body.
- **Save:** `⌘+Enter` → `window.gb.jot.save(body)` → overlay hides **immediately** (optimistic, fire-and-forget). The IPC handler runs `POST /v1/notes` in the background and resolves later. The user sees the overlay close in <16ms; the routing latency (~1–2s) is invisible.
- **Cancel:** `Esc` or window blur → overlay hides; body discarded.
- **Failure surfacing:** since the overlay is gone before the response arrives, errors must be surfaced elsewhere:
  - **Sidecar unreachable / 5xx on initial write** → main app shows an error toast: "couldn't save jot — sidecar not running". The body is lost (acceptable trade-off for optimistic UX; the alternative is to make the user wait through the LLM call).
  - **Routing fails after a successful file write** → jot lands as `manual_review` and appears in the Jot screen's "unrouted" node. No toast needed; the screen surfaces it.
- **No save toast on success.** Silence is the success signal.

### Backend `POST /v1/notes`

Request body:
```json
{ "body": "string", "capturedAt": "2026-05-14T09:30:15+02:00" }
```
`capturedAt` is optional; defaults to server `now()`.

Synchronous pipeline from the *handler's* perspective (LLM router is the only slow step, ~1–2s). The overlay does not wait on the response — see "Hotkey overlay" above. The Jot screen sees the new file appear on its next poll (≤5s).

1. **Compose id and filename.**
   `id = manual-{YYYYMMDDTHHMMSS}-{slug}` where slug is the first 32 chars of the first non-empty line, lowercased, non-alnum collapsed to `-`. Tie-break collisions by appending a 4-char random suffix.

2. **Write the file to `00-inbox/raw/manual/{id}.md`** with `routingStatus: pending`.

3. **Call `ghostbrain.worker.router.route_event({source: "manual", body, capturedAt, id})`.**
   Returns `RoutingDecision(context, confidence, reasoning)`. There is no fast-route (path-rule) for manual jots — it always goes through the LLM (Haiku).

4. **Apply the routing decision.**
   - `confidence ≥ reject_below` → move file to `vault/20-contexts/{context}/notes/{id}.md`; update frontmatter (`routingStatus: routed`, `context`, `routingConfidence`, `routingMethod: llm`, `routingReasoning`).
   - Otherwise → keep at inbox path, set `routingStatus: manual_review`. Surfaces in the "unrouted" tree node.

5. **Audit-log** the decision through the same audit channel the recorder uses.

6. **Return `{id, path, routingStatus}`.**

Failure handling:
- **LLM timeout (>10s) or error** → leave file at inbox path with `routingStatus: manual_review`. Return 200 with that status; the user sees "unrouted" in the tree and can manually route.
- **Filesystem move fails after a successful LLM decision** → file remains at the inbox path with valid frontmatter. Audit log records the partial state. The next semantic refresh still skips it (refresh only walks `20-contexts/`). User-visible behaviour: appears as "unrouted" until manually moved.

## Read/manage flow (Jot screen)

### Layout

```
┌─ jots ──────────────────────────────────────────────────────────────┐
│ [+ new]  [search jots…]                                             │
├──────────────────────┬──────────────────────────────────────────────┤
│  tree (≈260px)       │  markdown editor + live preview              │
│                      │                                              │
│ ▾ inbox (pending)    │  # title                                     │
│   • untitled-1       │                                              │
│ ▾ sanlam             │  body…                                       │
│   ▾ 2026-05          │                                              │
│     • ascp-wizard-…  │  [tags: #idea #ui]                           │
│   ▸ 2026-04          │                                              │
│ ▾ codeship           │  ──────── footer ────────                    │
│ ▾ personal           │  saved 2s ago · sanlam (routed, 0.82)        │
│ ▾ unrouted           │  [re-route] [delete] [open in Obsidian ↗]    │
└──────────────────────┴──────────────────────────────────────────────┘
```

### Tree

- One top-level node per routed context (`sanlam`, `codeship`, `personal`, etc., sourced from the user profile's known contexts).
- Plus `inbox (pending)` for jots still being routed (typically empty since routing is synchronous; appears briefly during the 1–2s LLM call if the screen is open).
- Plus `unrouted` for `routingStatus: manual_review` jots.
- Second level: month buckets `YYYY-MM` based on `created`.
- Leaf label: first non-empty line of the body (not the slug filename). Truncated to ~40 chars.

### Editor

- **CodeMirror 6** with markdown mode, line-wrapping, no line numbers. Side-by-side live preview via `markdown-it`.
- **Autosave** 1s after the last keystroke. Updates `updated:` in frontmatter. Next semantic refresh re-embeds because mtime changed.
- **"+ new"** creates an unsaved buffer. First save writes the file and triggers routing — same end state as the hotkey, just a slower entry point.
- **Search box** runs substring + tag-filter over the in-memory note list (no LLM, no embedding query). Filters the tree to matching leaves.

### Actions (per-jot footer)

- **re-route** — `POST /v1/notes/{id}/route` with `{context}`. Moves the file; updates `routingMethod: user`, `routingConfidence: 1.0`. No-ops if source == destination.
- **delete** — `DELETE /v1/notes/{id}`. Hard-deletes the file. Index drops it on next refresh.
- **open in Obsidian** — `obsidian://open?vault=<vault>&file=<rel-path>` URI scheme. Hands off for power editing.

## Data model

### Filename

`{id}.md` where `id = manual-{YYYYMMDDTHHMMSS}-{slug}`.

### Locations

- Pre-routing: `vault/00-inbox/raw/manual/{id}.md`
- Routed: `vault/20-contexts/{context}/notes/{id}.md`
- Manual review: stays at the pre-routing path with `routingStatus: manual_review`.

### Frontmatter

```yaml
---
id: manual-20260514T093015-ghostbrain-jot-idea
type: note
source: manual
context: sanlam              # null/absent while pending
created: '2026-05-14T09:30:15+02:00'
updated: '2026-05-14T09:30:15+02:00'
ingestedAt: '2026-05-14T09:30:15.123456+00:00'
routingStatus: routed        # pending | routed | manual_review
routingConfidence: 0.82      # null while pending
routingMethod: llm           # llm | user
routingReasoning: |
  Mentions sft-capstone-fe-ascp-v2 component and Cognito session handling —
  consistent with sanlam-digisure work context.
tags: [idea, ui]             # parsed from #hashtags in the body at write time
---

body text exactly as the user typed it, #idea about the ascp wizard flow:
…
```

Notes on the schema:

- **`source: manual`** is the discriminator the Jot screen filters on (vs `source: recorder` for transcripts, `source: gmail`, etc.). Matches the existing capture-list convention.
- **`routingStatus`** is new — the recorder routes synchronously today so it doesn't need this field. Jots also route synchronously, but the field exists so manual-review jots are queryable as a class.
- **`tags`** are extracted at write time by regex `#[a-z0-9-]+` over the body. Not used for routing; only for the Jot screen's search filter.

## API surface

Under `/v1/notes`. The existing `GET /v1/notes?path=…` (read a single note by vault-relative path) is unchanged.

| Method | Path | Body / Query | Returns |
|---|---|---|---|
| `POST` | `/v1/notes` | `{body, capturedAt?}` | `{id, path, routingStatus}` |
| `GET` | `/v1/notes` | `?source=manual&limit&offset&q&context&tag` | `{items: Note[], total}` |
| `PATCH` | `/v1/notes/{id}` | `{body}` | `{id, path, updated}` |
| `POST` | `/v1/notes/{id}/route` | `{context}` | `{id, path, context}` |
| `DELETE` | `/v1/notes/{id}` | — | 204 |

The list endpoint walks both `00-inbox/raw/manual/` and `20-contexts/*/notes/` for files with `source: manual` in their frontmatter, sorts by `created` desc, applies filters in memory. Acceptable for the expected scale (hundreds, not tens of thousands).

## Electron wiring

### Main process (`desktop/src/main/`)

- Register `globalShortcut` with the configured accelerator at `app.whenReady()`. If registration returns false, log + show a one-time toast on next main-window focus. Don't crash, don't retry.
- Lazy-create the overlay `BrowserWindow` on first hotkey press; reuse it (`show`/`hide`) afterwards. Loads its own renderer entry point (`desktop/src/renderer/overlay/`).
- Forward `window.gb.jot.save(body)` IPC calls to the sidecar's `POST /v1/notes`.

### Overlay renderer (`desktop/src/renderer/overlay/`)

- Tiny entry point: `<textarea>` + footer hint. No router, no shared stores, no toast system.
- Autofocus on each `onOpen` IPC event. Clear state on `onClose`.
- `⌘+Enter` → save then close; `Esc` or blur → close.

### Main app (`desktop/src/renderer/`)

- New screen `screens/jots.tsx` added to the sidebar.
- New API hooks in `lib/api/hooks.ts`: `useJots(filters)`, `useJot(id)`, `useCreateJot`, `useUpdateJot`, `useRouteJot`, `useDeleteJot`.
- The Jot screen polls `useJots({source: "manual"})` on a short interval (e.g. 5s) so a jot captured via the overlay appears in the tree without a manual refresh. No IPC coupling needed between the overlay and the main window.

## Testing

### Python (pytest)
- `routes/notes.py` happy paths and edge cases for POST/GET/PATCH/DELETE/route.
- `worker/router.py` integration with `source: "manual"` — mock the LLM, assert routing decision and file destination.
- Failure modes: LLM timeout → `routingStatus: manual_review`; filesystem move failure → file stays at inbox path with valid frontmatter and audit-log entry.

### Electron main (vitest)
- `globalShortcut.register` called with the configured accelerator.
- Hotkey collision (false return) is logged and does not crash.
- Overlay window is created once and reused (`show`/`hide`, never `close`).
- `jot.save` IPC forwards body verbatim to the sidecar.

### Renderer (vitest + RTL)
- Overlay: ⌘-Enter calls `jot.save`; Esc and blur call `jot.cancel`; textarea autofocuses on open.
- Jot screen: tree grouping is correct; "+ new" opens an empty buffer; autosave fires 1s after the last keystroke; re-route action calls the route endpoint; substring search filters the tree.

### Manual E2E (one-time per release)
- Capture via hotkey → file appears in `00-inbox/raw/manual/` within 1s.
- Audit log records the routing decision; file moves to `vault/20-contexts/{context}/notes/`.
- Within 15 min, ask the brain a question that references the jot → it appears as a citation in the answer.

## File-level changes

### New files
- `ghostbrain/api/routes/notes.py` — extend with POST/PATCH/DELETE/route (file already exists, currently GET-only).
- `ghostbrain/api/repo/notes_manual.py` — write/move/list/delete helpers for manual jots, plus tag extraction.
- `desktop/src/main/jot-overlay.ts` — overlay window lifecycle + global shortcut registration.
- `desktop/src/renderer/overlay/index.html` + `overlay/main.tsx` — overlay entry point.
- `desktop/src/renderer/screens/jots.tsx` — tree + editor screen.
- `desktop/src/renderer/components/JotTree.tsx`, `JotEditor.tsx` — tree and editor components.
- `desktop/src/preload/jot.ts` — `window.gb.jot.*` IPC bridge.

### Modified files
- `ghostbrain/api/models/note.py` — add `routingStatus`, `routingMethod`, `tags` fields.
- `ghostbrain/worker/router.py` — confirm `source: "manual"` is accepted by `route_event`; no schema changes expected, but verify.
- `desktop/src/renderer/components/Sidebar.tsx` — add "jots" entry.
- `desktop/src/main/index.ts` — wire up the overlay module.
- `desktop/src/preload/index.ts` — expose the jot IPC.

### Not changing
- `desktop/src/renderer/screens/vault.tsx` — keeps its "open in your file manager" stance for the broader vault. Out of scope.
- `ghostbrain/semantic/refresh.py` — no change; it already picks up new files in `20-contexts/`.
- `ghostbrain/scheduler.py` — no new scheduled job; routing is synchronous on POST.

## Open questions

None at design time. Implementation plan should confirm:
1. The default for `routing.yaml:reject_below` — does it already produce the desired behaviour for short manual jots, or does the `source: manual` branch need its own threshold?
2. The Obsidian URI scheme handoff — works on macOS with the user's existing vault registration; verify in the manual E2E.
