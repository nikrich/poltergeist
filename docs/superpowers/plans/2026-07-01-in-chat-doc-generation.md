# In-chat Doc Generation (HTML → PDF) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the chat agent write a styled HTML document to the vault via a new scoped MCP tool, and let the user open it as a PDF rendered by the app.

**Architecture:** A new `poltergeist_write_doc(title, html)` MCP tool → sidecar `POST /v1/docs/write` → `generated_docs` repo writes `20-contexts/generated-docs/<stamp>-<slug>.html` (hard-scoped, absolute vault path — no permission wall, no wrong-cwd). The chat renderer detects the generated-doc path in the reply and shows an "Open as PDF" button that has Electron render the vault HTML via `printToPDF` (reusing `pdf-export.ts`), save the PDF beside the HTML, and open it.

**Tech Stack:** Python 3 / FastAPI / pydantic / MCP (`mcp.server.fastmcp`) / pytest; TypeScript / Electron / React / Vitest + RTL.

## Global Constraints

- Generated docs live ONLY under `20-contexts/generated-docs/`; the repo fixes the directory and filename — the agent supplies only `title` + `html`, never a path.
- Files are `.html` (the agent emits a complete self-styled HTML document); the PDF is `<same-stem>.pdf` saved beside the HTML in the vault.
- HTML size cap: `MAX_HTML_BYTES = 2_000_000`.
- Filename: `YYYYMMDDTHHMMSS-<slug>.html` (slug from the title, `[^a-z0-9]+`→`-`, ≤60 chars).
- The `open-generated` IPC and the render helper MUST re-validate the path is under `20-contexts/generated-docs/` and ends in `.html`.
- Run Python tests from the worktree root with `/Users/jannik/.agentflow/.venv/bin/pytest <paths> -v`. Desktop tests: `npx vitest run <filter>` and `npm run typecheck` from `desktop/`.

---

### Task 1: `generated_docs` repo — write an HTML doc to the vault

**Files:**
- Create: `ghostbrain/api/repo/generated_docs.py`
- Test: `ghostbrain/api/tests/test_generated_docs.py`

**Interfaces:**
- Consumes: `ghostbrain.paths.vault_path`.
- Produces: `write_doc(title: str, html: str) -> dict` returning `{"path": <vault-relative .html>, "title": <stripped title>}`; raises `ValueError` on empty title, empty html, or oversize html. Constants `GENERATED_DOCS_DIR_REL = "20-contexts/generated-docs"`, `MAX_HTML_BYTES = 2_000_000`.

- [ ] **Step 1: Write the failing tests**

Create `ghostbrain/api/tests/test_generated_docs.py`:

```python
from pathlib import Path

import pytest

from ghostbrain.api.repo import generated_docs as repo

HTML = "<!doctype html><html><head><style>body{color:red}</style></head><body><h1>Q3</h1></body></html>"


def test_writes_html_under_generated_docs(tmp_vault: Path):
    result = repo.write_doc("Q3 One-Pager", HTML)
    assert result["title"] == "Q3 One-Pager"
    assert result["path"].startswith("20-contexts/generated-docs/")
    assert result["path"].endswith(".html")
    f = tmp_vault / result["path"]
    assert f.exists()
    assert f.read_text(encoding="utf-8") == HTML  # stored as-is, no wrapping


def test_slug_from_title(tmp_vault: Path):
    result = repo.write_doc("Hiring Freeze: 2026!", HTML)
    name = result["path"].rsplit("/", 1)[-1]
    assert name.endswith("-hiring-freeze-2026.html")


def test_empty_title_rejected(tmp_vault: Path):
    with pytest.raises(ValueError):
        repo.write_doc("   ", HTML)


def test_empty_html_rejected(tmp_vault: Path):
    with pytest.raises(ValueError):
        repo.write_doc("t", "   ")


def test_oversize_html_rejected(tmp_vault: Path):
    big = "<p>" + "a" * (repo.MAX_HTML_BYTES) + "</p>"
    with pytest.raises(ValueError):
        repo.write_doc("t", big)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/jannik/.agentflow/.venv/bin/pytest ghostbrain/api/tests/test_generated_docs.py -v`
Expected: FAIL — `ModuleNotFoundError: ghostbrain.api.repo.generated_docs`.

- [ ] **Step 3: Implement the repo**

Create `ghostbrain/api/repo/generated_docs.py`:

```python
"""Persist agent-generated documents as styled HTML files in the vault.

Written by the chat agent's `poltergeist_write_doc` tool. Hard-scoped to
20-contexts/generated-docs/ — the agent supplies only title + html, never a
path, so it cannot write elsewhere. The app renders these to PDF on demand.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from ghostbrain.paths import vault_path

GENERATED_DOCS_DIR_REL = "20-contexts/generated-docs"
MAX_HTML_BYTES = 2_000_000


def _slug(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60] or "document"


def write_doc(title: str, html: str) -> dict:
    title = title.strip()
    if not title:
        raise ValueError("title must not be empty")
    if not html.strip():
        raise ValueError("html must not be empty")
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        raise ValueError(f"html exceeds {MAX_HTML_BYTES} bytes")

    target_dir = vault_path() / GENERATED_DOCS_DIR_REL
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = target_dir / f"{stamp}-{_slug(title)}.html"
    path.write_text(html, encoding="utf-8")

    rel = path.resolve().relative_to(vault_path().resolve())
    return {"path": str(rel), "title": title}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/jannik/.agentflow/.venv/bin/pytest ghostbrain/api/tests/test_generated_docs.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/generated_docs.py ghostbrain/api/tests/test_generated_docs.py
git commit -m "feat(docs): write agent-generated HTML docs into the vault"
```

---

### Task 2: `POST /v1/docs/write` endpoint

**Files:**
- Modify: `ghostbrain/api/models/docs.py`
- Modify: `ghostbrain/api/routes/docs.py`
- Test: `ghostbrain/api/tests/test_generated_docs.py` (append)

**Interfaces:**
- Consumes: `generated_docs.write_doc` (Task 1).
- Produces: `POST /v1/docs/write` accepting `{"title": str, "html": str}`, returning `{"path": str, "title": str}`. 422 on empty title/html (model validation); 400 on repo `ValueError` (e.g. oversize).

- [ ] **Step 1: Write the failing tests**

Append to `ghostbrain/api/tests/test_generated_docs.py`:

```python
def test_write_endpoint_happy(client, auth_headers):
    res = client.post(
        "/v1/docs/write",
        json={"title": "Board Update", "html": HTML},
        headers=auth_headers,
    )
    assert res.status_code == 200
    body = res.json()
    assert body["title"] == "Board Update"
    assert body["path"].startswith("20-contexts/generated-docs/")


def test_write_endpoint_empty_html_422(client, auth_headers):
    res = client.post(
        "/v1/docs/write", json={"title": "x", "html": ""}, headers=auth_headers
    )
    assert res.status_code == 422


def test_write_endpoint_oversize_400(client, auth_headers):
    big = "<p>" + "a" * (repo.MAX_HTML_BYTES) + "</p>"
    res = client.post(
        "/v1/docs/write", json={"title": "x", "html": big}, headers=auth_headers
    )
    assert res.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/jannik/.agentflow/.venv/bin/pytest ghostbrain/api/tests/test_generated_docs.py -v -k endpoint`
Expected: FAIL — route missing (404/405).

- [ ] **Step 3: Add the models**

In `ghostbrain/api/models/docs.py`, add:

```python
class WriteDocRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    html: str = Field(..., min_length=1)


class WriteDocResponse(BaseModel):
    path: str
    title: str
```

(If `Field` isn't already imported in this file, add it: `from pydantic import BaseModel, Field`.)

- [ ] **Step 4: Add the route**

In `ghostbrain/api/routes/docs.py`, extend the model import and add `generated_docs`:

```python
from ghostbrain.api.models.docs import (
    ConfluenceExportRequest,
    DocsAssistRequest,
    DocsAssistStopRequest,
    WriteDocRequest,
    WriteDocResponse,
)
from ghostbrain.api.repo import docs_assist, export_confluence, generated_docs
```

Add the route (anywhere after `router = APIRouter(...)`):

```python
@router.post("/write", response_model=WriteDocResponse)
def write_doc(payload: WriteDocRequest) -> dict:
    try:
        return generated_docs.write_doc(payload.title, payload.html)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `/Users/jannik/.agentflow/.venv/bin/pytest ghostbrain/api/tests/test_generated_docs.py -v`
Expected: PASS (all).

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/api/models/docs.py ghostbrain/api/routes/docs.py ghostbrain/api/tests/test_generated_docs.py
git commit -m "feat(docs): POST /v1/docs/write endpoint"
```

---

### Task 3: MCP `poltergeist_write_doc` tool + agent wiring

**Files:**
- Modify: `ghostbrain/mcp/client.py`
- Modify: `ghostbrain/mcp/tools.py`
- Modify: `ghostbrain/mcp/__main__.py`
- Modify: `ghostbrain/llm/agent.py`
- Test: `tests/test_mcp_tools.py`, `tests/test_agent_run.py`

**Interfaces:**
- Consumes: `POST /v1/docs/write` (Task 2).
- Produces:
  - `SidecarClient.write_doc(self, title, html) -> dict`.
  - `tools.write_doc(client, title, html) -> str` — returns the vault path on success, or a `"Poltergeist could not save the document: …"` string on failure (never raises); `_Client` protocol gains `write_doc`.
  - MCP tool `poltergeist_write_doc(title: str, html: str) -> str`.
  - `TOOL_SUMMARIES` gains `"mcp__poltergeist__poltergeist_write_doc": ("write_doc", "wrote doc: {title}")` (so it is in `ALLOWED_TOOLS`); `CHAT_SYSTEM_PROMPT` describes it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mcp_tools.py`:

```python
def test_write_doc_returns_path():
    class FakeClient:
        def write_doc(self, title, html):
            return {"path": "20-contexts/generated-docs/20260701T120000-x.html", "title": title}

    from ghostbrain.mcp import tools

    out = tools.write_doc(FakeClient(), "X", "<html></html>")
    assert out == "20-contexts/generated-docs/20260701T120000-x.html"


def test_write_doc_error_is_returned_not_raised():
    class BoomClient:
        def write_doc(self, title, html):
            raise RuntimeError("sidecar down")

    from ghostbrain.mcp import tools

    out = tools.write_doc(BoomClient(), "X", "<html></html>")
    assert "could not save" in out.lower()
```

Append to `tests/test_agent_run.py`:

```python
def test_write_doc_tool_is_allowlisted():
    from ghostbrain.llm.agent import ALLOWED_TOOLS

    assert "mcp__poltergeist__poltergeist_write_doc" in ALLOWED_TOOLS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/jannik/.agentflow/.venv/bin/pytest tests/test_mcp_tools.py tests/test_agent_run.py -v -k write_doc`
Expected: FAIL — `tools.write_doc` missing; key not in `ALLOWED_TOOLS`.

- [ ] **Step 3: Add the client method**

In `ghostbrain/mcp/client.py`, add alongside `get_note`:

```python
    def write_doc(self, title: str, html: str) -> dict:
        return self._request("POST", "/v1/docs/write", json={"title": title, "html": html})
```

- [ ] **Step 4: Add the tools function + protocol**

In `ghostbrain/mcp/tools.py`, extend the `_Client` protocol:

```python
class _Client(Protocol):
    def answer(self, q: str, limit: int = 8) -> dict: ...
    def search(self, q: str, limit: int = 10) -> dict: ...
    def get_note(self, path: str) -> dict: ...
    def write_doc(self, title: str, html: str) -> dict: ...
```

Add the function:

```python
def write_doc(client: _Client, title: str, html: str) -> str:
    """Save an agent-generated HTML document to the vault; return its path."""
    try:
        data = client.write_doc(title, html)
    except Exception as e:  # noqa: BLE001 — surface failure as text, never raise
        return f"Poltergeist could not save the document: {e}"
    return str(data.get("path") or "")
```

- [ ] **Step 5: Register the MCP tool**

In `ghostbrain/mcp/__main__.py`, add inside `build_server` (next to the other `@mcp.tool()` blocks):

```python
    @mcp.tool()
    def poltergeist_write_doc(title: str, html: str) -> str:
        """Save a document the user asked you to write. Pass a COMPLETE,
        self-contained HTML document (its own <style>; print-friendly layout
        when appropriate) as `html`. Returns the vault-relative path of the
        saved doc — cite it back to the user as a wikilink. Use this ONLY when
        the user asks you to write/draft/create a document."""
        return tools.write_doc(client, title, html)
```

- [ ] **Step 6: Wire the agent**

In `ghostbrain/llm/agent.py`, add to `TOOL_SUMMARIES`:

```python
    "mcp__poltergeist__poltergeist_write_doc": ("write_doc", "wrote doc: {title}"),
```

Append to `CHAT_SYSTEM_PROMPT` (before the closing `"""`), as a new rule:

```
6. When the user asks you to write, draft, or create a document, produce a \
COMPLETE, self-contained, styled HTML document (its own <style>; print-friendly \
per-section layout when it suits the content) and call poltergeist_write_doc \
with a short title and that HTML. Then tell the user the doc is ready and put \
the tool's returned path on its own line as a wikilink, e.g. \
[[20-contexts/generated-docs/…​.html]]. Do NOT paste the raw HTML into the chat.
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `/Users/jannik/.agentflow/.venv/bin/pytest tests/test_mcp_tools.py tests/test_agent_run.py -q`
Expected: PASS (existing + new).

- [ ] **Step 8: Commit**

```bash
git add ghostbrain/mcp/client.py ghostbrain/mcp/tools.py ghostbrain/mcp/__main__.py ghostbrain/llm/agent.py tests/test_mcp_tools.py tests/test_agent_run.py
git commit -m "feat(docs): poltergeist_write_doc MCP tool + agent wiring"
```

---

### Task 4: Main process — render vault HTML to PDF + open

**Files:**
- Modify: `desktop/src/main/pdf-export.ts`
- Modify: `desktop/src/main/index.ts`
- Modify: `desktop/src/preload/index.ts`
- Modify: `desktop/src/shared/types.ts`
- Test: `desktop/src/main/__tests__/pdf-export.test.ts`

**Interfaces:**
- Consumes: nothing from earlier tasks (contract is the vault-relative path string).
- Produces:
  - `isGeneratedDocPath(rel: string): boolean` (exported, pure) — true iff `rel` starts with `20-contexts/generated-docs/`, ends with `.html`, and contains no `..` segment.
  - `renderVaultHtmlToPdf(vaultPath: string, rel: string): Promise<{ ok: true; path: string } | { ok: false; error: string }>`.
  - IPC `gb:docs:open-generated` and preload `docs.openGenerated(path: string)`.

- [ ] **Step 1: Write the failing test**

Create/append `desktop/src/main/__tests__/pdf-export.test.ts`:

```typescript
import { describe, expect, it } from 'vitest';
import { isGeneratedDocPath } from '../pdf-export';

describe('isGeneratedDocPath', () => {
  it('accepts a generated-docs .html path', () => {
    expect(isGeneratedDocPath('20-contexts/generated-docs/20260701T120000-x.html')).toBe(true);
  });
  it('rejects paths outside generated-docs', () => {
    expect(isGeneratedDocPath('20-contexts/sanlam/notes/x.html')).toBe(false);
  });
  it('rejects non-.html', () => {
    expect(isGeneratedDocPath('20-contexts/generated-docs/x.md')).toBe(false);
  });
  it('rejects path traversal', () => {
    expect(isGeneratedDocPath('20-contexts/generated-docs/../../etc/x.html')).toBe(false);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (from `desktop/`): `npx vitest run pdf-export`
Expected: FAIL — `isGeneratedDocPath` not exported.

- [ ] **Step 3: Add the scope helper + render function**

In `desktop/src/main/pdf-export.ts`, add only `shell` to the existing `electron` import (`join` and `writeFile` are already imported at the top of the file; `win.loadFile` reads the HTML itself, so no `readFile`/`dirname` are needed — do not add unused imports, `noUnusedLocals` will fail). Then add:

```typescript
export function isGeneratedDocPath(rel: string): boolean {
  const norm = rel.replace(/\\/g, '/');
  return (
    norm.startsWith('20-contexts/generated-docs/') &&
    norm.endsWith('.html') &&
    !norm.split('/').includes('..')
  );
}

export async function renderVaultHtmlToPdf(
  vaultPath: string,
  rel: string,
): Promise<{ ok: true; path: string } | { ok: false; error: string }> {
  if (!vaultPath) return { ok: false, error: 'vault path not configured' };
  if (!isGeneratedDocPath(rel)) {
    return { ok: false, error: 'path is not a generated doc' };
  }
  const htmlPath = join(vaultPath, rel);
  const pdfPath = htmlPath.replace(/\.html$/, '.pdf');
  const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true } });
  try {
    // The agent's HTML is already a complete styled document — load as-is
    // (no wrapPrintableHtml), so its own CSS/@page rules drive the layout.
    await win.loadFile(htmlPath);
    const pdf = await win.webContents.printToPDF({ printBackground: true });
    await writeFile(pdfPath, pdf);
    await shell.openPath(pdfPath);
    return { ok: true, path: pdfPath };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  } finally {
    win.destroy();
  }
}
```

The only import change is adding `shell` to the existing electron import line:

```typescript
import { BrowserWindow, dialog, shell } from 'electron';
```

`writeFile` (from `node:fs/promises`), `join` (from `node:path`), `tmpdir`, `mkdtemp`, `rm` are already imported by the existing `exportPdf` code — reuse them; add nothing else.

- [ ] **Step 4: Add the IPC handler + preload + type**

In `desktop/src/main/index.ts`, add near the `gb:docs:export-pdf` handler (import `renderVaultHtmlToPdf` from `./pdf-export`, and `settings` is already imported):

```typescript
ipcMain.handle('gb:docs:open-generated', (_e, path: unknown) => {
  if (typeof path !== 'string' || path === '') {
    return { ok: false as const, error: 'open-generated: expected a path string' };
  }
  return renderVaultHtmlToPdf(settings.getAll().vaultPath ?? '', path);
});
```

Update the import line `import { exportPdf } from './pdf-export';` to:

```typescript
import { exportPdf, renderVaultHtmlToPdf } from './pdf-export';
```

In `desktop/src/preload/index.ts`, add to the `docs` object:

```typescript
    openGenerated: (path: string) => ipcRenderer.invoke('gb:docs:open-generated', path),
```

In `desktop/src/shared/types.ts`, add to the `docs` interface:

```typescript
    openGenerated(
      path: string,
    ): Promise<{ ok: true; path: string } | { ok: false; error: string }>;
```

- [ ] **Step 5: Run tests + typecheck**

Run (from `desktop/`): `npx vitest run pdf-export` then `npm run typecheck`.
Expected: `isGeneratedDocPath` tests PASS; typecheck exit 0. (The `renderVaultHtmlToPdf` printToPDF path needs the Electron runtime and is verified in the app manually, not unit-tested.)

- [ ] **Step 6: Commit**

```bash
git add desktop/src/main/pdf-export.ts desktop/src/main/index.ts desktop/src/preload/index.ts desktop/src/shared/types.ts desktop/src/main/__tests__/pdf-export.test.ts
git commit -m "feat(docs): render a generated vault HTML doc to PDF and open it"
```

---

### Task 5: Renderer — "Open as PDF" button on generated-doc replies

**Files:**
- Modify: `desktop/src/renderer/screens/chat.tsx`
- Test: `desktop/src/renderer/__tests__/ChatScreen.test.tsx`

**Interfaces:**
- Consumes: `window.gb.docs.openGenerated(path)` (Task 4); `toast` (`../stores/toast`).
- Produces: assistant messages whose text contains a `20-contexts/generated-docs/….html` path render an "Open as PDF" button per match that calls `openGenerated`.

- [ ] **Step 1: Write the failing test**

Append to `desktop/src/renderer/__tests__/ChatScreen.test.tsx` (reuse the file's existing conversation-mock + render helpers; this shows the assertions — an assistant message carrying a generated-doc path):

```typescript
it('shows an Open as PDF button for a generated-doc reply and calls openGenerated', async () => {
  const openGenerated = vi.fn().mockResolvedValue({ ok: true, path: '/v/x.pdf' });
  // ensure the stub bridge exposes docs.openGenerated (extend the test's window.gb stub)
  (window.gb as unknown as { docs: { openGenerated: typeof openGenerated } }).docs = {
    ...(window.gb as unknown as { docs: object }).docs,
    openGenerated,
  };
  renderChatWithMessages([
    {
      role: 'assistant',
      text: 'Your doc is ready:\n\n[[20-contexts/generated-docs/20260701T120000-brief.html]]',
    },
  ]);
  const btn = await screen.findByRole('button', { name: /open as pdf/i });
  await userEvent.click(btn);
  expect(openGenerated).toHaveBeenCalledWith(
    '20-contexts/generated-docs/20260701T120000-brief.html',
  );
});
```

If `ChatScreen.test.tsx` lacks a `renderChatWithMessages` helper, extend the file's existing conversation mock to accept a `messages` array (match how the attachment tests there set messages), rather than adding a parallel harness.

- [ ] **Step 2: Run test to verify it fails**

Run (from `desktop/`): `npx vitest run ChatScreen`
Expected: FAIL — no "Open as PDF" button.

- [ ] **Step 3: Add detection + button to the assistant message**

In `desktop/src/renderer/screens/chat.tsx`, add the import (if `toast` isn't already imported) and a small helper + component near `Message`:

```typescript
import { toast } from '../stores/toast';

const GENERATED_DOC_RE = /20-contexts\/generated-docs\/[^\s\]]+\.html/g;

function generatedDocPaths(text: string): string[] {
  return [...new Set(text.match(GENERATED_DOC_RE) ?? [])];
}

function OpenDocButtons({ paths }: { paths: string[] }) {
  if (paths.length === 0) return null;
  const open = (p: string) => {
    void window.gb.docs.openGenerated(p).then((res) => {
      if (!res.ok) toast.error(res.error);
    });
  };
  return (
    <div className="flex flex-wrap gap-2">
      {paths.map((p) => (
        <Btn
          key={p}
          variant="ghost"
          size="sm"
          icon={<Lucide name="file-text" size={12} />}
          onClick={() => open(p)}
        >
          open as pdf
        </Btn>
      ))}
    </div>
  );
}
```

In the `Message` component's assistant branch, render the buttons under the `MarkdownBody` (the assistant `return (...)` block around line 442):

```typescript
      <MarkdownBody className="text-14 leading-[1.65] text-ink-0">
        {message.text}
      </MarkdownBody>
      <OpenDocButtons paths={generatedDocPaths(message.text)} />
```

(Apply the same `<OpenDocButtons paths={generatedDocPaths(stream.text)} />` under the streaming assistant `MarkdownBody` in `StreamingTurn` if you want it live mid-stream — optional; the historical `Message` path is what the test covers.)

- [ ] **Step 4: Run tests + typecheck**

Run (from `desktop/`): `npx vitest run ChatScreen` then `npm run typecheck`.
Expected: PASS; typecheck exit 0.

- [ ] **Step 5: Commit**

```bash
git add desktop/src/renderer/screens/chat.tsx desktop/src/renderer/__tests__/ChatScreen.test.tsx
git commit -m "feat(docs): Open as PDF button on generated-doc chat replies"
```

---

## Final verification

- [ ] Python: `/Users/jannik/.agentflow/.venv/bin/pytest ghostbrain/api/tests/test_generated_docs.py tests/test_mcp_tools.py tests/test_mcp_client.py tests/test_agent_run.py tests/test_docs_routes.py -q` — expect green.
- [ ] Desktop: from `desktop/`, `npx vitest run` then `npm run typecheck` — expect green.
- [ ] Manual smoke (dev app): in chat, "write a short confidential one-pager on X". Confirm: the agent calls `write_doc` (a "wrote doc" tool chip appears), the reply has an "Open as PDF" button, clicking it renders and opens a styled PDF in Preview, and both `…​.html` and `…​.pdf` exist under `~/ghostbrain/vault/20-contexts/generated-docs/`.

## Out of scope (future)

- docx/markdown output; regenerate-in-place; templates.
- Auto-open (chose button); PDF outside the vault (chose beside the HTML).
- Semantic indexing of generated HTML.
