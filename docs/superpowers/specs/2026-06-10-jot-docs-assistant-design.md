# Jot Docs Assistant + Confluence/PDF Export — Design

- **Date:** 2026-06-10
- **Status:** Approved
- **Repo:** ghost-brain (poltergeist)
- **Depends on:** chat agent infra (`ghostbrain/llm/agent.py`), Atlassian import (`ghostbrain/api/repo/import_atlassian.py`), RichMarkdownEditor
- **Author:** brainstormed with Jannik

## Summary

- Rovo-style writing assistant inside the **Jots screen**: a collapsible side panel that drafts documents from vault knowledge or polishes what the user wrote, plus selection-level quick actions.
- Export the open jot to **Confluence** (create page; re-export updates the page we created) via the existing Atlassian client, or download as **PDF** rendered Electron-side.

## Decisions

| Decision | Chosen | Rejected alternatives |
|---|---|---|
| Home for the feature | Jots screen (assistant panel + selection actions) | Dedicated Docs screen; chat artifacts |
| LLM path | Streaming agent (`agent.py`) with doc-mode system prompt + vault MCP tools, SSE relay | One-shot `client.py` call with stuffed search results (no streaming, weaker grounding) |
| Confluence export | Create page with space/parent picker; frontmatter tracks page id; re-export updates that page | Fresh page every export (duplicates); overwrite arbitrary pages (conflict risk) |
| PDF generation | Electron `webContents.printToPDF` of `MarkdownBody`-styled HTML | Python-side weasyprint/pandoc (bloats PyInstaller sidecar) |
| Markdown → Confluence | Python `markdown` package → storage XHTML in the sidecar | Renderer-side markdown-it (export must work from API layer, keep conversion next to the Atlassian client) |
| Apply model | Proposed replacement with accept/discard in the editor | Stream directly into the saved body (silent overwrite of user text) |

## Architecture

### 1. Assist route (sidecar)

`POST /v1/docs/assist` → SSE stream (same shape as chat: `delta` / `tool` / `done` / `error` events).

Payload:

```json
{
  "jot_id": "…",
  "instruction": "free-form prompt; for quick actions a canned instruction",
  "selection": "optional substring of the body the action targets",
  "mode": "draft | polish | expand | summarize"
}
```

- Repo layer `ghostbrain/api/repo/docs_assist.py` loads the jot body, builds the agent prompt (body + selection + instruction), and runs a turn via `ghostbrain/llm/agent.py` with:
  - `DOCS_SYSTEM_PROMPT`: technical-writer persona; output is **only** the replacement markdown (no preamble, no fences); ground claims in the vault via the MCP tools; keep frontmatter out of the output.
  - MCP tools: existing `poltergeist_search` / `poltergeist_get_note` (no `poltergeist_ask` — the agent IS the writer).
  - No session persistence: each assist call is a fresh single turn (unlike chat).
- Cancellation mirrors chat: `POST /v1/docs/assist/stop` kills the subprocess; subprocess also killed when the SSE consumer disconnects.

### 2. Assistant panel (renderer)

- `DocsAssistPanel.tsx`, collapsible, right of the editor in `screens/jots.tsx`.
- Prompt box + quick-action buttons (Polish, Expand, Summarize). Quick actions map to canned instructions; all four go through the same route with `mode` set.
- Targeting: current editor selection if non-empty, else whole body. Selection is read from TipTap state via a small imperative handle added to `RichMarkdownEditor` (`getSelectionMarkdown()`)
- Streaming output renders live in the panel; on `done` the result becomes a **pending proposal**:
  - selection op → editor shows replacement preview for that range, Accept/Discard buttons;
  - whole-doc op → side-by-side proposal in the panel, Accept replaces the body.
  - Accept triggers the editor's normal autosave path (`PATCH /v1/notes/{jot_id}`); Discard drops the proposal. Nothing is saved before Accept.
- Electron main relays the SSE the same way chat does (`gb:docs:event` IPC channel, reusing the api-forwarder streaming path).

### 3. Confluence export

- Atlassian client (`ghostbrain/connectors/atlassian/_base.py`) gains `create_page(space_key, title, storage_html, parent_id=None)` and `update_page(page_id, title, storage_html)` (version-increment handled inside).
- `ghostbrain/connectors/atlassian/markdown_out.py`: markdown → Confluence storage XHTML using the `markdown` package (tables + fenced-code extensions). Wikilinks `[[…]]` are flattened to plain text.
- `POST /v1/export/confluence` `{jot_id, space_key, parent_id?, title?}`:
  - title defaults to the jot's first `# heading`, else its filename;
  - on success stamps frontmatter: `confluence_page_id`, `confluence_space`, `confluence_url`, `confluence_exported_at`;
  - if `confluence_page_id` already present → `update_page` instead; if Confluence returns 404 for it (page deleted remotely) → 409 to the client with a "page gone — export as new?" message; client retries with `force_new: true`.
- UI: Export dropdown in the jot editor header → "Confluence…" opens a destination dialog reusing the import screen's space browser (`/v1/import/confluence/spaces` + page-tree endpoints) for space + optional parent. Last destination remembered (settings store). Menu item hidden when the Atlassian connector status probe says unconfigured.

### 4. PDF download

- Export dropdown → "Download PDF": renderer asks main via `gb:docs:export-pdf` `{title, markdown}`.
- Main renders the markdown to HTML (same renderer pipeline as `MarkdownBody`, bundled print stylesheet) in a hidden `BrowserWindow`, calls `webContents.printToPDF`, then shows a save dialog defaulting to `<title>.pdf`.
- No sidecar involvement; works with no connectors configured.

## Error handling

- **Assist:** agent error / timeout → `error` SSE event → inline panel error with Retry (same component pattern as chat turn errors). Stop button always available while streaming.
- **Confluence:** 401/403 → "Atlassian token invalid or missing scope"; 404 space → "space not found"; tracked-page 404 → 409 + re-export-as-new flow; network → generic retryable toast. Export never mutates frontmatter unless the API call succeeded.
- **PDF:** printToPDF or save failure → toast with the OS error; temp window always destroyed (finally).

## Testing

- **pytest:** docs_assist repo (mocked agent — prompt assembly per mode/selection, SSE event passthrough, cancellation); markdown_out conversion (headings, tables, code, wikilink flattening); export repo with mocked Atlassian client (create vs update branch, frontmatter stamping, remote-404 → 409, no stamp on failure).
- **vitest:** panel state machine (idle → streaming → proposal → accept/discard), selection vs whole-doc targeting, export menu gating on connector status, destination dialog wiring (mocked hooks).
- **E2E (manual):** draft-from-vault into an empty jot; polish a selection; export to a sandbox Confluence space twice (create then update); PDF download opens in Preview.

## Out of scope (v1)

- Exporting arbitrary vault notes (jots only).
- Updating Confluence pages not created by Poltergeist.
- Doc templates, multi-document generation, image/attachment upload to Confluence.
- Assist history/undo beyond the single pending proposal (editor undo stack still applies after Accept).

## Implementation status

- 2026-06-10: spec approved, implementation starting (worktree).
- 2026-06-10: implemented on `worktree-docs-assist` (15 commits, subagent-driven with per-unit spec + quality reviews). Tests: 30 new pytest (assist repo/routes, markdown_out, atlassian pages, export repo/routes), 34 new vitest (docs-stream, pdf-export, editor handle, store, panel, dialog, jots gating) — full suites green (652 py / 195 desktop).
- Deviations from spec (all reviewed): PDF renders from the editor's TipTap HTML via a temp file + hidden window (not main-side markdown render; data-URI hits Chromium's ~2MB URL cap); export route lives at `/v1/docs/export/confluence` (docs router prefix); last export destination remembered in module memory, not persisted settings (v1); parent page is a plain id input, not a tree picker (v1); user-initiated stop returns the assist panel to idle (spec didn't define post-stop state).
- Known follow-ups: connector-gate predicate (connector `on`) differs from the export 409 predicate (spaces configured in routing.yaml) — a user with the connector on but no spaces sees a 409 toast; source-mode `replaceWith` updates the saved body but not the live CodeMirror view until remount; "no longer exists" error detection is string-coupled to the route's 409 detail.
- Manual E2E (assist draft/polish against live vault, double export to a sandbox Confluence space, PDF in Preview) pending human hands.
