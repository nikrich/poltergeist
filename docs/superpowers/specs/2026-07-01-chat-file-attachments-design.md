# Chat file attachments — design

**Status:** approved (brainstorm), pending implementation plan
**Date:** 2026-07-01

## Goal

Let the user drop or paste files into the chat composer. Each attached file
becomes:

1. **Grounding for the current turn** — the agent reads it and answers with it
   in context.
2. **A permanent, searchable vault note** — indexed like any other note.

Supported content: **text/markdown/code, PDFs/office docs, and images.** These
are captured in one spec but implemented as three slices (below).

## Key decisions (from brainstorm)

- **Always index, then reference.** Every attached file is written to the vault
  first; the turn references it by path. No ephemeral-only mode.
- **Vault location: `20-contexts/chat-attachments/`.** It must live under
  `20-contexts/` because `semantic/refresh.py` (`contexts_root = vault_path() /
  "20-contexts"`, `refresh.py:63`) and search only walk that tree. Placing
  attachments in `00-inbox` would make them unsearchable.
- **In-turn grounding = reference by path (pure).** The prompt is augmented with
  the attachment wikilinks plus an instruction to read them first; the agent
  fetches each via `poltergeist_get_note`. Content is NOT inlined into the
  prompt. This matches the existing citation convention and keeps prompts small.
- **No new indexing code.** The current turn reads notes by direct path
  (`get_note` reads the file, no embedding required). The periodic
  `semantic refresh` job then embeds the new notes on its next cycle, making them
  searchable. Immediate searchability is not guaranteed; immediate grounding is.

## Current architecture (as-is)

- **Chat send:** renderer composer → IPC `gb:chat:send(convId, text)`
  (`preload/index.ts:25`) → main `gb:chat:send` handler (`main/index.ts:295`) →
  `startChatStream` → sidecar `POST /v1/chat/{conv}/messages`
  (`api/routes/chat.py:57`) → `repo_chat.send_message`
  (`api/repo/chat.py:28`) → `agent.run_chat_turn` → `claude -p` subprocess.
- **Agent tools:** the `claude -p` subprocess is locked to the poltergeist MCP
  server only (`--allowedTools`, `agent.py:211`) — `poltergeist_search`,
  `poltergeist_get_note`, `poltergeist_ask`. **No `Read` tool, no filesystem or
  vision input.** This is why images cannot reach the agent in-turn and are
  handled by captioning (Slice 3).
- **Vault writes / indexing:** connectors + imports write notes via the worker
  pipeline (`process_event` → `write_note`). Semantic indexing is a separate
  batch `semantic refresh` that rglobs `20-contexts/**/*.md`, embeds by content
  hash, and writes `related:` frontmatter.
- **Message persistence:** `chat_store` holds conversations as message dicts
  (`role`, `text`, optional `tools`, `interrupted`).

## Data flow (to-be)

```
Composer (drag-drop / paste / click-to-browse)
  → collect File objects → render attachment chips (removable)
  → on send, for each file:
      IPC gb:chat:attach(convId, {name, mime, bytes})
        → main forwards → sidecar POST /v1/chat/{conv}/attachments
            → chat_attachments repo: (extract if needed) → write note under
              20-contexts/chat-attachments/  → return {path, title, kind}
  → then IPC gb:chat:send(convId, text, attachmentPaths[])
      → sidecar POST /v1/chat/{conv}/messages { text, attachment_paths }
          → repo_chat stores the user message WITH attachment metadata
          → prompt augmented: "The user attached these notes; read each with
            poltergeist_get_note before answering:\n- [[path]]…\n\n<text>"
          → agent runs; reads each attachment via get_note (pure reference)
Later: `semantic refresh` (scans 20-contexts) embeds the new notes → searchable.
```

**Why two steps (attach then send):** persisting first gives every attachment a
real vault path before the turn starts, so the turn stays atomic and the user
message can be re-rendered from history with its attachment chips intact. A
failed upload blocks the send with a toast rather than producing a half-grounded
turn.

## Vault note shape

Directory: `20-contexts/chat-attachments/` (binaries under
`20-contexts/chat-attachments/assets/`).

- **Filename:** `YYYYMMDDTHHMMSS-<slug>.md` (matches connector filename
  convention; slug derived from the original filename).
- **Frontmatter:**
  ```yaml
  id: <content-hash>
  source: chat-attachment
  title: <original filename>
  created: <iso timestamp>
  conversation_id: <conv id>
  original_filename: <original filename>
  kind: text | pdf | docx | image
  ```
- **Body by type:**
  - **text / md / code** — content inlined verbatim; code fenced by extension
    (` ```py `, etc.). Markdown inlined as-is.
  - **PDF / docx** — extracted plain text.
  - **image** — OCR/caption text, followed by an embed
    `![[chat-attachments/assets/<hash>.<ext>]]`. The binary is written to
    `assets/`.

Re-attaching identical content (same hash) reuses the existing note rather than
duplicating (mirrors import's stale-copy handling).

## Message persistence & rendering

- Extend the chat message type with `attachments?: { path, title, kind }[]`:
  - shared `desktop/src/shared/api-types.ts`
  - Python `api/models/chat.py`
  - `chat_store` append/read (persist + return the field)
- **Renderer:** user bubbles render an attachment chip row (icon by `kind`,
  title, clickable as a wikilink to the stored note) — in both the live
  `StreamingTurn` and reloaded history `Message`. The optimistic stream state
  (`stores/chat.ts` `StreamState`) carries the pending attachments for the
  in-flight user bubble.

## Composer UI

- **Drag-drop:** a drop overlay appears on `dragover` of the composer/thread;
  drop collects the files.
- **Paste:** `onPaste` on the textarea reads `clipboardData.files` (covers
  screenshot paste → image) and `items`.
- **Click-to-browse:** a small paperclip button opens a file picker (parity +
  accessibility).
- **Chips:** a removable chip row above the textarea shows queued attachments
  before send. Send is disabled while uploading; a per-file spinner/error state
  is shown. Oversize/unsupported files are rejected inline with a toast.

## Type-specific processing — the three slices

### Slice 1 — text / markdown / code (foundation)
Delivers the entire mechanism end-to-end for the simplest content: drop zone,
paste, click-to-browse, chips, `gb:chat:attach` IPC, the attachments endpoint +
`chat_attachments` repo, note write, message-schema extension, prompt
augmentation, and history rendering. No extraction step. Everything else builds
on this.

### Slice 2 — PDF / office docs
Add a Python text-extraction step before the note write (`pypdf` for PDF,
`python-docx` for `.docx`; extend the accepted extensions/MIME allowlist).
Reuses Slice 1's persistence, prompt injection, and rendering unchanged.

### Slice 3 — images (riskiest, decision deferred)
Store the binary under `assets/` and generate caption/OCR text for the note
body. Because the chat agent is MCP-only (no vision input), captioning runs as a
**separate step at attach time**, not by the chat turn. Two candidate
approaches, to be pinned down when this slice is planned:

- **A — dedicated `claude -p` vision call:** a second, isolated `claude`
  invocation that accepts the image (via stream-json image block / file input)
  and returns a caption. Reuses the existing Max-billing `claude` path; no new
  dependency; adds latency + cost per image.
- **B — local OCR (e.g. tesseract):** offline, free, no LLM; weaker on
  non-text imagery (diagrams, photos), adds a native/system dependency.

This slice is flagged as the uncertain one; its approach is an **open decision**
recorded here, resolved in its own planning pass.

## Limits & error handling

- Max ~10 files per message; per-file caps (text ~1 MB, image ~10 MB); total cap.
- Unsupported MIME/extension rejected inline (toast), never uploaded.
- Upload failure → toast, block the send (no half-grounded turn).
- Per-file failures within a batch are reported but don't abort the batch.
- Prompt augmentation is built once; the resume/history fallback in `repo_chat`
  keeps the same attachment references so context survives a session reset.

## Testing

- **Python**
  - `chat_attachments` repo: filename, frontmatter, path returned, hash reuse,
    per-type body (Slice 1 text; Slice 2 pdf/docx; Slice 3 image+asset).
  - attach endpoint: happy path, oversize/unsupported rejection, per-file
    failure isolation.
  - `repo_chat`: prompt augmentation includes the wikilinks + instruction; user
    message persisted with `attachments`; resume fallback preserves references.
- **Renderer (RTL)**
  - composer: drop, paste (incl. image blob), click-to-browse, chip
    add/remove, oversize/unsupported rejection, send disabled while uploading.
  - upload-then-send ordering; failure blocks send.
  - message renders attachment chips in stream + reloaded history.
- **Main**
  - `gb:chat:attach` IPC handler: shape validation, forward, error surfacing.

## Out of scope

- In-turn vision (agent directly "seeing" an image) — precluded by the MCP-only
  tool set; images are grounded via their caption note instead.
- Editing/re-routing attachment notes after creation (they're plain vault notes;
  normal vault tooling applies).
- Streaming/very-large-file handling beyond the size caps.
