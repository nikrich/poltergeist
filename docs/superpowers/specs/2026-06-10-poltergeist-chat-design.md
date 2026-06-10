# Poltergeist Chat — Design

**Date:** 2026-06-10
**Status:** Approved
**Repo:** ghost-brain (Poltergeist desktop + sidecar)

## Summary

A full multi-turn chat interface in the Poltergeist desktop app. Each turn is
agentic: the sidecar shells out to the local `claude` CLI with the ghostbrain
MCP tools attached, so Claude decides when to search and read the vault.
Responses stream token-by-token with live tool activity. Conversations persist
across restarts as JSON files. The existing single-shot AskPanel is removed —
chat replaces it.

## Decisions (with alternatives considered)

| Decision | Chosen | Rejected alternatives |
|---|---|---|
| Location | Poltergeist desktop app | hive-ide panel; shared/embeddable UI |
| Engine | Agentic via `claude -p --resume` + ghostbrain MCP tools | Multi-turn RAG (extend `/v1/answer`); hybrid with mode toggle |
| Streaming | Full token streaming + tool events over SSE | Whole-response spinner; activity-only |
| Persistence | Conversation list on disk, sidecar-side JSON | Single ephemeral session; markdown notes in the vault |
| UI | New Chat screen in sidebar; AskPanel removed | Keep AskPanel alongside; evolve AskPanel in place |

## Architecture

```
Renderer (Chat screen)
  └─ IPC: window.gb.chat.* (new streaming bridge)
       └─ Main process: opens SSE request to sidecar, forwards events to renderer
            └─ FastAPI sidecar: POST /v1/chat/{id}/messages → text/event-stream
                 └─ Agent runner: claude -p --resume <session> --output-format stream-json
                      --include-partial-messages --mcp-config (ghostbrain-mcp)
                      --allowedTools mcp__poltergeist__* --system-prompt <persona>
```

- Each turn, Claude has the existing ghostbrain MCP tools (`search`,
  `get_note`, `ask`) and decides itself when to hit the vault.
- Multi-turn memory comes from CLI `--resume` with the per-conversation
  stored session id.
- Billing stays on the user's Claude Max OAuth session (subprocess inherits
  it), same as the existing `llm/client.py` approach.
- A custom `--system-prompt` keeps calls lean (no global CLAUDE.md/skills
  injection) and sets the Poltergeist persona + citation rules.

## Storage

One JSON file per conversation at `~/ghostbrain/chats/<uuid>.json`:

```json
{
  "id": "<uuid>",
  "title": "derived from first user message, renameable",
  "created_at": "...",
  "updated_at": "...",
  "claude_session_id": "<cli session id or null>",
  "messages": [
    { "role": "user", "text": "..." },
    { "role": "assistant", "text": "...markdown...",
      "tools": [ { "name": "search", "summary": "searched vault: standup notes" } ] }
  ]
}
```

- No SQLite, no migrations — files as source of truth.
- Title = first user message truncated; `PATCH` renames. No LLM titling call.
- Tool-activity summaries persist so reopening a conversation shows what the
  agent did.

## Sidecar API

| Route | Behavior |
|---|---|
| `GET /v1/chat` | List conversations (id, title, updated_at), newest first |
| `POST /v1/chat` | Create conversation |
| `GET /v1/chat/{id}` | Full message history |
| `PATCH /v1/chat/{id}` | Rename |
| `DELETE /v1/chat/{id}` | Delete conversation file |
| `POST /v1/chat/{id}/messages` | Send message; respond with SSE stream |

SSE event types on the message route:

- `delta` — assistant text tokens as they arrive
- `tool` — tool-use started (name + human summary, e.g. "searching vault: …")
- `done` — turn complete; final message persisted; includes full message
- `error` — structured failure (binary missing, timeout, subprocess error)

A new `ghostbrain/llm/agent.py` wraps the
streaming subprocess: spawn `claude -p`, parse stdout JSON lines
(`stream-json` with `--include-partial-messages`), map to SSE events. The
existing `llm/client.py` stays untouched — it is request/response and used by
the worker/digest paths.

Client disconnect on the SSE response kills the claude subprocess.

## Electron streaming bridge

The existing `gb:api:request` IPC is request/response only. Chat adds a small
dedicated bridge:

- `gb.chat.send(convId, text)` — main process opens the SSE request via the
  api-forwarder's port discovery, reads the body incrementally, and forwards
  each event to the renderer via `webContents.send('gb:chat:event', …)`.
- `gb.chat.stop(convId)` — aborts the in-flight fetch; sidecar sees the
  disconnect and kills the subprocess.

## UI

- New `chat` entry in `ScreenId` + sidebar `NAV_ITEMS` (icon:
  `message-circle`), new `screens/chat.tsx`.
- Layout: conversation list on the left (new / rename / delete), message
  thread on the right.
- Thread reuses `MarkdownBody`; streaming text appends live with a cursor;
  tool activity renders as inline chips while the agent works; stop button
  visible during generation.
- Citations: the system prompt instructs the agent to cite vault notes as
  markdown links by vault-relative path; clicking one navigates to the note
  in the vault screen.
- **AskPanel removal:** `components/AskPanel.tsx` is deleted; the trigger on
  the today screen becomes "open a new chat" (navigates to the chat screen
  with a fresh conversation).

## Error handling

- `claude` binary missing → `error` SSE event reusing the
  `_find_claude_binary` lookup/diagnostic messaging from `llm/client.py`.
- Per-turn timeout: 5 minutes; subprocess killed; partial streamed text is
  persisted and marked interrupted.
- Stale/failed `--resume`: retry the turn once **without** `--resume`,
  prepending the last 6 messages to the prompt so conversational context
  survives; store the new session id.
- Renderer shows errors inline in the thread (not toasts), with retry.

## Testing

- **Backend (pytest):**
  - chat storage CRUD (create/list/get/rename/delete, corrupt-file tolerance)
  - stream-json parser against recorded fixture lines (text deltas, tool use,
    result, error shapes)
  - route tests with a fake agent runner — no real `claude` calls in CI
- **Frontend (Vitest):** conversation store; thread rendering of
  delta/tool/done/error events; composer + stop behavior. Follow existing
  renderer test patterns (`src/renderer/__tests__`).

## Out of scope (v1)

- LLM-generated conversation titles
- Exporting chats into the vault
- Embedding the chat UI in hive-ide
- Attachments / images in the composer
- Permission prompts for tools beyond the allowlisted ghostbrain MCP set
