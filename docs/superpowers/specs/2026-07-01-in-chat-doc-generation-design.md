# In-chat doc generation (styled HTML → PDF) — design

**Status:** approved (brainstorm), pending implementation plan
**Date:** 2026-07-01

## Goal

Let the user ask Poltergeist, in a normal chat, to **write a document** ("draft a confidential one-pager on the hiring freeze"). The chat agent generates a **complete, self-styled HTML document**, saves it to the vault through a write-capable tool, and the user opens it as a **styled PDF** rendered by the app.

## Why (the concrete problem this fixes)

Today the chat agent has only read tools. When asked to write a doc it falls back to Claude's built-in `Write`/`Bash`, which:
1. **Hits a permission wall** — in `--print` mode there's no interactive dialog, so the write hangs/blocks (the exact failure `agent.py` warns about).
2. **Writes to the wrong place** — the claude subprocess's cwd is the sidecar's repo root, so a relative write lands in a code repo the user can't reach from chat.

A scoped, allowlisted MCP write tool that writes to an **absolute vault path** solves both.

## Decisions (from brainstorm)

- **Trigger:** in-chat, natural-language request (no separate command/UI).
- **Output:** the agent emits a **full styled HTML document**; the app renders it to **PDF** and opens it **externally** (Preview). Not plain markdown — the user wants the styled look (vertical "CONFIDENTIAL" sidebar, "⚠ DRAFT" footer, phase-gate taglines, one section per page) the agent was already hand-rolling.
- **Mechanism:** a **new write-capable MCP tool** (`poltergeist_write_doc`), added to the chat agent's allowlist.
- **Location:** a dedicated, hard-scoped folder `20-contexts/generated-docs/`.
- **Open UX (a):** an **"Open as PDF" button** on the assistant message (not auto-open — a window popping up unprompted is surprising).
- **PDF storage (b):** the rendered PDF is **saved into the vault beside the `.html`** (kept, not throwaway).

## Current architecture (reused)

- **Chat turn:** renderer → `gb:chat:send` → sidecar `/v1/chat/{id}/messages` → `repo_chat` → `agent.run_chat_turn` → `claude -p` with the poltergeist MCP server. `ALLOWED_TOOLS = ",".join(TOOL_SUMMARIES)` (`agent.py`); `CHAT_SYSTEM_PROMPT` describes the tools.
- **MCP server** (`ghostbrain/mcp/`): `@mcp.tool()` functions in `__main__.py` call `tools.<fn>(client, …)`; `client.py` proxies to the sidecar over HTTP (`search`/`answer`/`get_note`).
- **HTML→PDF (already exists):** `desktop/src/main/pdf-export.ts` `exportPdf(parent, {title, html})` loads HTML into a hidden `BrowserWindow` and calls `printToPDF({printBackground:true})` (full CSS/`@page` fidelity). Wired via IPC `gb:docs:export-pdf`. `wrapPrintableHtml` wraps a body *fragment* in default CSS — for agent-generated *full* HTML we render it as-is (no wrap).
- **Chat rendering:** assistant messages render markdown via `MarkdownBody`; the app already turns `[[vault path]]` wikilinks into clickable in-app links.

## Data flow (to-be)

```
You (chat): "write a confidential one-pager on the hiring freeze"
  → agent gathers context (existing read tools), generates a COMPLETE styled HTML doc
  → agent calls  poltergeist_write_doc(title, html)
       → MCP tool → sidecar  POST /v1/docs/write {title, html}
            → generated_docs.write_doc: writes 20-contexts/generated-docs/<stamp>-<slug>.html
              → returns the vault-relative path
       → tool returns the path string to the agent
  → agent's reply references the doc (path)
  → renderer detects a generated-docs/*.html reference → shows "Open as PDF"
       → IPC gb:docs:open-generated {path}
            → main reads the vault .html → printToPDF (reuse pdf-export.ts, no re-wrap)
              → writes <same-stem>.pdf beside the .html in the vault
              → shell.openPath(pdf)  → opens in Preview
```

## Components & responsibilities

### Sidecar
- **`ghostbrain/api/repo/generated_docs.py`** — `write_doc(title: str, html: str) -> dict` returning `{"path": <vault-relative .html>, "title": title}`. Hard-scoped: always writes under `20-contexts/generated-docs/`, filename `YYYYMMDDTHHMMSS-<slug>.html`. The agent supplies **only title + html** — never a path (no arbitrary writes). Rejects empty title/html; caps html size (e.g. 2 MB).
  - The `.html` file is the styled document as-is (the agent includes its own `<style>`/`<html>`). No frontmatter — it's a real HTML file meant for the browser/print engine, not a markdown note.
- **`POST /v1/docs/write`** in `ghostbrain/api/routes/docs.py` (the docs router already exists) → `generated_docs.write_doc`. 400 on empty title/html.

### MCP
- **`ghostbrain/mcp/client.py`** — `write_doc(self, title, html) -> dict` → `POST /v1/docs/write`.
- **`ghostbrain/mcp/tools.py`** — `write_doc(client, title, html) -> str` (returns the path, or an error string on failure — never raises, so a tool failure surfaces as text the agent can relay).
- **`ghostbrain/mcp/__main__.py`** — `@mcp.tool() def poltergeist_write_doc(title: str, html: str) -> str` with a docstring telling the model to pass a **complete self-styled HTML document**.

### Agent wiring (`ghostbrain/llm/agent.py`)
- Add `"mcp__poltergeist__poltergeist_write_doc": ("write_doc", "wrote doc: {title}")` to `TOOL_SUMMARIES` (auto-included in `ALLOWED_TOOLS`).
- Extend `CHAT_SYSTEM_PROMPT`: "When the user asks you to write, draft, or create a document, produce a COMPLETE, self-contained, styled HTML document (its own `<style>`; print-friendly `@page`/per-section layout when appropriate) and call `poltergeist_write_doc(title, html)`. Then tell the user the doc is ready and include the tool's returned path verbatim on its own line as a wikilink, e.g. `[[20-contexts/generated-docs/...html]]` — do NOT paste the full HTML into the chat." (This is how the renderer finds the doc — see below.)

### Desktop main (`desktop/src/main/`)
- Extend `pdf-export.ts` with `renderVaultHtmlToPdf(vaultHtmlRelPath) -> {ok, path} | {ok:false, error}`: resolve the vault path (must be under `20-contexts/generated-docs/`, `.html`), load it directly (no `wrapPrintableHtml` — it's already a full doc), `printToPDF`, write `<stem>.pdf` beside it, `shell.openPath(pdf)`.
- New IPC `gb:docs:open-generated` (validate `{path:string}`, enforce the generated-docs/.html scope) → `renderVaultHtmlToPdf`. Preload: `docs.openGenerated(path)`.

### Desktop renderer (`desktop/src/renderer/screens/chat.tsx`)
- Detect generated docs by regex-scanning the assistant message text for `20-contexts/generated-docs/[^\s\]]+\.html` (the agent is prompted to include the path as a wikilink). For each match, render an **"Open as PDF"** chip/button that calls `window.gb.docs.openGenerated(path)`; toast on error. (The `tool` stream event only carries `{name, summary}` — not the path — so detection is text-based, not tool-event-based.)

## Storage

- `20-contexts/generated-docs/<YYYYMMDDTHHMMSS>-<slug>.html` — the styled source (retrievable, reusable, re-openable).
- `<same-stem>.pdf` — rendered on first "Open as PDF", kept beside the HTML.
- HTML is not markdown, so it is **not** semantically indexed — acceptable for output documents (the user chose HTML→PDF over markdown notes).

## Safety

- `poltergeist_write_doc` is the agent's ONLY write capability; the repo fixes the directory and filename, so the agent cannot write outside `20-contexts/generated-docs/` or overwrite arbitrary files. Html size cap. Invoked only when the agent chooses to, on a user request.
- The `gb:docs:open-generated` IPC re-validates the path is under `generated-docs/` and ends in `.html` before rendering — the renderer can't drive the printer at arbitrary files.

## Error handling

- Empty title/html → 400 from the endpoint → `tools.write_doc` returns an error string → agent relays it in chat.
- PDF render failure (bad HTML, printToPDF error) → IPC returns `{ok:false,error}` → renderer toast; the `.html` still exists in the vault.
- Old build without the tool: the agent has no `poltergeist_write_doc`, so it degrades to replying with the content inline (no file) — no hang, no wrong-location write.

## Testing

- **Python:** `generated_docs.write_doc` (filename, slug, scoping under `20-contexts/generated-docs/`, `.html` extension, empty-input rejection, size cap); `POST /v1/docs/write` (happy + 400); `mcp.tools.write_doc` returns the path / error string (mocked client).
- **Agent:** `poltergeist_write_doc` key is in `ALLOWED_TOOLS`; `CHAT_SYSTEM_PROMPT` mentions it. (Do not invoke real claude.)
- **Desktop main:** `renderVaultHtmlToPdf` path-scope validation (rejects non-`generated-docs`/non-`.html`); a spot-check that a small HTML renders to a PDF file (may run under the test electron env or be smoke-only).
- **Renderer:** an assistant message containing a `generated-docs/*.html` reference shows the "Open as PDF" button and calls `docs.openGenerated` with the path.

## Out of scope (future)

- docx/markdown output (this slice is HTML→PDF only).
- Editing/regenerating a doc in place, versioning, templates library.
- Auto-open (chosen: button), or saving the PDF outside the vault (chosen: beside the HTML).
- Indexing generated HTML into semantic search.
- Confluence export of generated docs (a separate existing path).
