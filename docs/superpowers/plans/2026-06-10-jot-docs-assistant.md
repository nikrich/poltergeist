# Jot Docs Assistant + Confluence/PDF Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rovo-style writing assistant in the Jots screen (draft from vault / polish selection, streamed) plus export of a jot to Confluence (create + tracked update) or PDF.

**Architecture:** Sidecar gains an SSE assist route reusing `llm/agent.py` with a docs system prompt and vault MCP tools; export route converts markdown → Confluence storage XHTML and create/updates pages via the existing AtlassianClient (gaining POST/PUT). Desktop mirrors the chat SSE relay for assist events, adds an assistant panel + proposal accept/discard in the jots screen, and prints PDFs from editor HTML via a hidden BrowserWindow.

**Tech Stack:** FastAPI sidecar, `claude -p` stream-json agent, python `markdown` + `frontmatter`, Electron IPC + `printToPDF`, React/Zustand/React-Query, TipTap.

**Spec:** `docs/superpowers/specs/2026-06-10-jot-docs-assistant-design.md`

---

## File map

| File | Action | Responsibility |
|---|---|---|
| `ghostbrain/llm/agent.py` | modify | accept `system_prompt`/`allowed_tools` overrides |
| `ghostbrain/api/repo/docs_assist.py` | create | docs prompt building + assist turn orchestration |
| `ghostbrain/api/models/docs.py` | create | request models |
| `ghostbrain/api/routes/docs.py` | create | `/v1/docs/assist` SSE + stop + `/v1/export/confluence` |
| `ghostbrain/connectors/atlassian/_base.py` | modify | generalize to `_request`, add `post`/`put` |
| `ghostbrain/connectors/atlassian/markdown_out.py` | create | markdown → Confluence storage XHTML |
| `ghostbrain/connectors/atlassian/pages.py` | create | `create_page` / `update_page` |
| `ghostbrain/api/repo/notes_manual.py` | modify | `set_frontmatter_fields` helper |
| `ghostbrain/api/repo/export_confluence.py` | create | export orchestration + frontmatter stamping |
| `ghostbrain/api/main.py` | modify | register docs router |
| `pyproject.toml` | modify | add `markdown>=3.6` dependency |
| `desktop/src/shared/api-types.ts` | modify | `DocsAssistEvent`, export types |
| `desktop/src/shared/types.ts` | modify | `GbBridge.docs` |
| `desktop/src/main/docs-stream.ts` | create | SSE relay for assist (mirrors chat-stream) |
| `desktop/src/main/pdf-export.ts` | create | hidden-window printToPDF + save dialog |
| `desktop/src/main/index.ts` | modify | `gb:docs:*` IPC wiring |
| `desktop/src/preload/index.ts` | modify | expose `gb.docs` bridge |
| `desktop/src/renderer/stores/docs-assist.ts` | create | panel state machine |
| `desktop/src/renderer/components/RichMarkdownEditor.tsx` | modify | imperative handle (selection/replace/html) |
| `desktop/src/renderer/components/DocsAssistPanel.tsx` | create | prompt box + quick actions + proposal UI |
| `desktop/src/renderer/components/ConfluenceExportDialog.tsx` | create | space/parent destination picker |
| `desktop/src/renderer/lib/api/hooks.ts` | modify | `useExportConfluence` |
| `desktop/src/renderer/screens/jots.tsx` | modify | panel toggle + export menu integration |

Run Python tests with `pytest tests/<file> -v` from repo root; desktop with `npm test` (vitest), `npm run typecheck`, `npm run lint` from `desktop/`.

---

### Task 1: agent.py — system-prompt + allowed-tools overrides

**Files:** Modify `ghostbrain/llm/agent.py`; Test `tests/test_docs_assist.py` (new)

- [ ] **Step 1: Write failing tests**

```python
# tests/test_docs_assist.py
"""Docs assistant: agent overrides, prompt building, assist orchestration."""
from ghostbrain.llm import agent


def test_build_chat_command_default_system_prompt():
    cmd = agent.build_chat_command("claude", "hi")
    i = cmd.index("--system-prompt")
    assert cmd[i + 1] == agent.CHAT_SYSTEM_PROMPT


def test_build_chat_command_system_prompt_override():
    cmd = agent.build_chat_command("claude", "hi", system_prompt="DOCS MODE")
    i = cmd.index("--system-prompt")
    assert cmd[i + 1] == "DOCS MODE"


def test_build_chat_command_allowed_tools_override():
    cmd = agent.build_chat_command(
        "claude", "hi", mcp_binary="/bin/mcp",
        allowed_tools="mcp__poltergeist__poltergeist_search",
    )
    i = cmd.index("--allowedTools")
    assert cmd[i + 1] == "mcp__poltergeist__poltergeist_search"
```

- [ ] **Step 2: Run to verify failure** — `pytest tests/test_docs_assist.py -v` → FAIL (`unexpected keyword argument 'system_prompt'`)

- [ ] **Step 3: Implement** — in `ghostbrain/llm/agent.py`, extend `build_chat_command` and thread through `run_chat_turn`:

```python
def build_chat_command(
    binary: str,
    prompt: str,
    *,
    model: str = DEFAULT_CHAT_MODEL,
    session_id: str | None = None,
    mcp_binary: str | None = None,
    system_prompt: str | None = None,
    allowed_tools: str | None = None,
) -> list[str]:
    cmd = [
        binary,
        "--print",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",  # required by claude for stream-json with --print
        "--model", model,
        "--system-prompt", system_prompt or CHAT_SYSTEM_PROMPT,
        "--exclude-dynamic-system-prompt-sections",
        "--max-budget-usd", f"{CHAT_BUDGET_USD:.4f}",
    ]
    if mcp_binary:
        cmd += [
            "--mcp-config",
            json.dumps({"mcpServers": {"poltergeist": {"command": mcp_binary}}}),
            "--strict-mcp-config",  # don't drag in the user's other MCP servers
            "--allowedTools", allowed_tools or ALLOWED_TOOLS,
        ]
    if session_id:
        cmd += ["--resume", session_id]
    # `--` terminates option parsing — without it a variadic flag like
    # --allowedTools swallows the positional prompt (verified live).
    cmd += ["--", prompt]
    return cmd
```

`run_chat_turn` gains the same two keyword args (default `None`) and passes them to `build_chat_command`. No other behavior changes.

- [ ] **Step 4: Verify pass** — `pytest tests/test_docs_assist.py tests/test_agent_run.py tests/test_agent_stream.py -v` → all PASS (existing agent tests must stay green)

- [ ] **Step 5: Commit** — `git add ghostbrain/llm/agent.py tests/test_docs_assist.py && git commit -m "feat(docs-assist): agent accepts system-prompt and allowed-tools overrides"`

---

### Task 2: docs_assist repo — prompts + assist orchestration

**Files:** Create `ghostbrain/api/repo/docs_assist.py`; Test `tests/test_docs_assist.py`

- [ ] **Step 1: Write failing tests** (append to `tests/test_docs_assist.py`)

```python
from unittest.mock import patch

from ghostbrain.api.repo import docs_assist


def test_build_prompt_polish_selection():
    p = docs_assist.build_prompt(
        body="# Doc\n\nintro text", instruction=None, selection="intro text", mode="polish",
    )
    assert "intro text" in p
    assert docs_assist.CANNED_INSTRUCTIONS["polish"] in p
    assert "ONLY the replacement markdown for the SELECTION" in p


def test_build_prompt_draft_whole_doc_uses_instruction():
    p = docs_assist.build_prompt(
        body="", instruction="Write an RFC about the activity heatmap",
        selection=None, mode="draft",
    )
    assert "Write an RFC about the activity heatmap" in p
    assert "ONLY the full replacement document" in p


def test_run_assist_streams_and_uses_docs_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_VAULT", str(tmp_path))
    from ghostbrain.api.repo import notes_manual
    rec = notes_manual.write_inbox_jot("# My doc\n\nhello")
    captured = {}

    def fake_turn(prompt, **kw):
        captured.update(kw, prompt=prompt)
        yield {"type": "delta", "text": "polished"}
        yield {"type": "done", "text": "polished", "session_id": "s1"}

    with patch.object(docs_assist.agent, "run_chat_turn", fake_turn):
        events = list(docs_assist.run_assist(rec["id"], instruction=None, selection=None, mode="polish"))
    assert [e["type"] for e in events] == ["delta", "done"]
    assert captured["system_prompt"] == docs_assist.DOCS_SYSTEM_PROMPT
    assert captured["allowed_tools"] == docs_assist.DOCS_ALLOWED_TOOLS
    assert captured["turn_key"] == f"docs:{rec['id']}"
    assert "hello" in captured["prompt"]


def test_run_assist_unknown_jot_yields_error():
    events = list(docs_assist.run_assist("manual-nope", instruction=None, selection=None, mode="polish"))
    assert events == [{"type": "error", "message": "jot not found"}]
```

(Check `tests/conftest.py` first: if the vault fixture uses a different env var or fixture name, mirror what `test_chat_repo.py` / notes tests do to point the vault at `tmp_path`.)

- [ ] **Step 2: Verify failure** — `pytest tests/test_docs_assist.py -v` → FAIL (no module `docs_assist`)

- [ ] **Step 3: Implement** `ghostbrain/api/repo/docs_assist.py`:

```python
"""Docs assistant: one-shot streamed writing turns over a jot.

Unlike chat there is no session persistence — every assist call is a fresh
single turn. Cancellation reuses the agent registry with key ``docs:<jot_id>``.
"""
from __future__ import annotations

import logging
from typing import Iterator

from ghostbrain.api.repo import notes_manual
from ghostbrain.llm import agent

log = logging.getLogger("ghostbrain.docs_assist")

DOCS_ALLOWED_TOOLS = ",".join(
    n for n in agent.TOOL_SUMMARIES if not n.endswith("poltergeist_ask")
)

DOCS_SYSTEM_PROMPT = """You are Poltergeist's technical writer. You draft and \
polish documents inside the user's personal knowledge app, grounded in their \
vault.

Rules:
1. Ground factual claims in the vault: poltergeist_search to locate notes, \
poltergeist_get_note to read them. Never invent facts about the user's work; \
if the vault doesn't cover something, write around it or mark it [TODO].
2. Your ENTIRE output is used verbatim as document content. Output ONLY \
markdown for the document — no preamble, no explanation, no code fences \
around the whole answer, no YAML frontmatter.
3. Match the user's tone and terminology. Keep structure clean: one H1 at \
most, sensible heading levels, tight prose."""

CANNED_INSTRUCTIONS = {
    "draft": "Write the document described by the user's instruction.",
    "polish": "Polish this text: fix grammar, tighten wording, improve flow. Preserve meaning, structure, and markdown formatting.",
    "expand": "Expand this text with relevant detail, grounded in the vault where possible. Keep the existing structure and voice.",
    "summarize": "Rewrite this text as a tighter summary, preserving the key points and any headings worth keeping.",
}


def build_prompt(
    *, body: str, instruction: str | None, selection: str | None, mode: str
) -> str:
    task = CANNED_INSTRUCTIONS.get(mode, CANNED_INSTRUCTIONS["polish"])
    parts = [f"Task: {task}"]
    if instruction:
        parts.append(f"User instruction: {instruction}")
    if selection:
        parts.append(
            "The user selected part of the document. Reply with ONLY the "
            "replacement markdown for the SELECTION."
        )
        parts.append(f"FULL DOCUMENT (context only):\n{body}")
        parts.append(f"SELECTION (replace this):\n{selection}")
    else:
        parts.append(
            "Reply with ONLY the full replacement document as markdown."
        )
        parts.append(f"CURRENT DOCUMENT:\n{body}" if body.strip() else "The document is currently empty.")
    return "\n\n".join(parts)


def run_assist(
    jot_id: str, *, instruction: str | None, selection: str | None, mode: str
) -> Iterator[dict]:
    try:
        jot = notes_manual.read_jot(jot_id)
    except notes_manual.JotNotFound:
        yield {"type": "error", "message": "jot not found"}
        return
    prompt = build_prompt(
        body=jot["body"], instruction=instruction, selection=selection, mode=mode
    )
    yield from agent.run_chat_turn(
        prompt,
        system_prompt=DOCS_SYSTEM_PROMPT,
        allowed_tools=DOCS_ALLOWED_TOOLS,
        turn_key=f"docs:{jot_id}",
    )


def cancel(jot_id: str) -> bool:
    return agent.cancel_turn(f"docs:{jot_id}")
```

- [ ] **Step 4: Verify pass** — `pytest tests/test_docs_assist.py -v` → PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(docs-assist): assist repo — docs prompt + streamed turn orchestration"`

---

### Task 3: docs routes + models + registration

**Files:** Create `ghostbrain/api/models/docs.py`, `ghostbrain/api/routes/docs.py`; Modify `ghostbrain/api/main.py`; Test `tests/test_docs_routes.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_docs_routes.py
"""Docs assist + export routes (SSE shape, stop, error mapping)."""
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app


def _client():
    app = create_app(require_auth=False)  # match how other route tests build the app
    return TestClient(app)


def test_assist_streams_sse():
    def fake(jot_id, **kw):
        yield {"type": "delta", "text": "hi"}
        yield {"type": "done", "text": "hi", "session_id": ""}

    with patch("ghostbrain.api.routes.docs.docs_assist.run_assist", fake):
        res = _client().post("/v1/docs/assist", json={"jot_id": "j1", "mode": "polish"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/event-stream")
    payloads = [json.loads(l[6:]) for l in res.text.splitlines() if l.startswith("data: ")]
    assert [p["type"] for p in payloads] == ["delta", "done"]


def test_assist_stop():
    with patch("ghostbrain.api.routes.docs.docs_assist.cancel", return_value=True):
        res = _client().post("/v1/docs/assist/stop", json={"jot_id": "j1"})
    assert res.json() == {"stopped": True}
```

(Adapt `_client()` to the app factory signature used by existing route tests — copy from `tests/test_atlassian_import_refactor.py` or similar.)

- [ ] **Step 2: Verify failure** — `pytest tests/test_docs_routes.py -v` → FAIL

- [ ] **Step 3: Implement.** `ghostbrain/api/models/docs.py`:

```python
"""Request models for the docs assistant + export routes."""
from typing import Literal

from pydantic import BaseModel


class DocsAssistRequest(BaseModel):
    jot_id: str
    mode: Literal["draft", "polish", "expand", "summarize"] = "polish"
    instruction: str | None = None
    selection: str | None = None


class DocsAssistStopRequest(BaseModel):
    jot_id: str


class ConfluenceExportRequest(BaseModel):
    jot_id: str
    space_key: str
    parent_id: str | None = None
    title: str | None = None
    force_new: bool = False
```

`ghostbrain/api/routes/docs.py`:

```python
"""Docs assistant: streamed writing turns + Confluence export."""
import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ghostbrain.api.models.docs import (
    ConfluenceExportRequest,
    DocsAssistRequest,
    DocsAssistStopRequest,
)
from ghostbrain.api.repo import docs_assist

router = APIRouter(prefix="/v1/docs", tags=["docs"])


@router.post("/assist")
def assist(payload: DocsAssistRequest) -> StreamingResponse:
    def gen():
        # Sync generator: starlette threadpools it and closes it on client
        # disconnect, which kills the claude subprocess (same as chat).
        for event in docs_assist.run_assist(
            payload.jot_id,
            instruction=payload.instruction,
            selection=payload.selection,
            mode=payload.mode,
        ):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/assist/stop")
def stop(payload: DocsAssistStopRequest) -> dict:
    return {"stopped": docs_assist.cancel(payload.jot_id)}
```

Register in `ghostbrain/api/main.py` alongside the other routers (`from ghostbrain.api.routes import docs as docs_routes` + `app.include_router(docs_routes.router)`). The export endpoint is added to this router in Task 7.

- [ ] **Step 4: Verify pass** — `pytest tests/test_docs_routes.py -v` → PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(docs-assist): /v1/docs/assist SSE route + stop"`

---

### Task 4: markdown → Confluence storage XHTML

**Files:** Create `ghostbrain/connectors/atlassian/markdown_out.py`; Modify `pyproject.toml`; Test `tests/test_markdown_out.py`

- [ ] **Step 1: Add dependency** — in `pyproject.toml` `[project].dependencies`, add `"markdown>=3.6",` (alphabetical near `markdownify`). Run `pip install -e ".[api]"` to pick it up.

- [ ] **Step 2: Write failing tests**

```python
# tests/test_markdown_out.py
from ghostbrain.connectors.atlassian.markdown_out import to_storage_html


def test_headings_and_paragraphs():
    html = to_storage_html("# Title\n\nbody text")
    assert "<h1>Title</h1>" in html and "<p>body text</p>" in html


def test_tables_extension_enabled():
    html = to_storage_html("| a | b |\n|---|---|\n| 1 | 2 |")
    assert "<table>" in html


def test_fenced_code():
    html = to_storage_html("```\ncode here\n```")
    assert "code here" in html and "<pre>" in html


def test_wikilinks_flattened():
    assert ">target<" not in to_storage_html("see [[20-contexts/x/note]]")
    html = to_storage_html("see [[20-contexts/x/note|the note]]")
    assert "the note" in html and "[[" not in html
```

- [ ] **Step 3: Verify failure** — `pytest tests/test_markdown_out.py -v` → FAIL

- [ ] **Step 4: Implement** `ghostbrain/connectors/atlassian/markdown_out.py`:

```python
"""Markdown → Confluence storage-format XHTML (the export inverse of the
connector's markdownify import path). Confluence storage format accepts
standard XHTML for text/tables/code; we don't emit any <ac:*> macros in v1."""
from __future__ import annotations

import re

import markdown as md_lib

_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def _flatten_wikilinks(text: str) -> str:
    """``[[path|label]]`` → ``label``; ``[[path]]`` → last path segment.
    Vault-relative paths mean nothing inside Confluence."""
    def repl(m: re.Match) -> str:
        label = m.group(2)
        return label if label else m.group(1).rsplit("/", 1)[-1]
    return _WIKILINK.sub(repl, text)


def to_storage_html(markdown_text: str) -> str:
    return md_lib.markdown(
        _flatten_wikilinks(markdown_text),
        extensions=["tables", "fenced_code"],
        output_format="xhtml",
    )
```

- [ ] **Step 5: Verify pass** — `pytest tests/test_markdown_out.py -v` → PASS
- [ ] **Step 6: Commit** — `git commit -m "feat(docs-assist): markdown → confluence storage xhtml converter"`

---

### Task 5: AtlassianClient post/put + page create/update

**Files:** Modify `ghostbrain/connectors/atlassian/_base.py`; Create `ghostbrain/connectors/atlassian/pages.py`; Test `tests/test_atlassian_pages.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_atlassian_pages.py
from unittest.mock import MagicMock

from ghostbrain.connectors.atlassian._base import AtlassianClient
from ghostbrain.connectors.atlassian.pages import PageGone, create_page, update_page


def _client_returning(*responses):
    client = AtlassianClient("x.atlassian.net", "e@x.com", "tok")
    mocks = []
    for status, body in responses:
        r = MagicMock(status_code=status, text="")
        r.json.return_value = body
        mocks.append(r)
    client._session.request = MagicMock(side_effect=mocks)
    return client, client._session.request


def test_create_page_posts_storage_body():
    client, req = _client_returning((200, {"id": "123", "_links": {"base": "https://x.atlassian.net/wiki", "webui": "/spaces/K/pages/123"}}))
    out = create_page(client, space_key="K", title="T", storage_html="<p>hi</p>", parent_id="9")
    assert out["page_id"] == "123"
    assert out["url"] == "https://x.atlassian.net/wiki/spaces/K/pages/123"
    kwargs = req.call_args
    sent = kwargs.kwargs.get("json") or kwargs[1].get("json")
    assert sent["space"]["key"] == "K"
    assert sent["ancestors"] == [{"id": "9"}]
    assert sent["body"]["storage"]["value"] == "<p>hi</p>"


def test_update_page_increments_version():
    client, req = _client_returning(
        (200, {"id": "123", "version": {"number": 4}, "title": "T"}),   # GET current
        (200, {"id": "123", "_links": {"base": "https://x.atlassian.net/wiki", "webui": "/x"}}),  # PUT
    )
    update_page(client, page_id="123", title="T2", storage_html="<p>v2</p>")
    put_body = req.call_args_list[1].kwargs.get("json") or req.call_args_list[1][1]["json"]
    assert put_body["version"]["number"] == 5
    assert put_body["title"] == "T2"


def test_update_page_404_raises_page_gone():
    client, req = _client_returning((404, {}))
    try:
        update_page(client, page_id="123", title="T", storage_html="x")
        assert False, "expected PageGone"
    except PageGone:
        pass
```

- [ ] **Step 2: Verify failure** — `pytest tests/test_atlassian_pages.py -v` → FAIL

- [ ] **Step 3: Refactor `_base.py`** — generalize `get` into `_request(method, path, ...)` keeping the existing retry/429/401 behavior **identical** (move the body of `get` into `_request` with a `method` arg and `json_body: dict | None`; `self._session.get(url, params=...)` becomes `self._session.request(method, url, params=params, json=json_body, timeout=timeout_s)`). Then:

```python
    def get(self, path, params=None, *, timeout_s=DEFAULT_TIMEOUT_S, max_retries=3) -> dict:
        return self._request("GET", path, params=params, timeout_s=timeout_s, max_retries=max_retries)

    def post(self, path, json_body: dict, *, timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
        return self._request("POST", path, json_body=json_body, timeout_s=timeout_s, max_retries=1)

    def put(self, path, json_body: dict, *, timeout_s: int = DEFAULT_TIMEOUT_S) -> dict:
        return self._request("PUT", path, json_body=json_body, timeout_s=timeout_s, max_retries=1)
```

`max_retries=1` for writes: never auto-retry a non-idempotent POST. Inside `_request`, surface 404 distinctly: add

```python
            if response.status_code == 404:
                raise AtlassianNotFound(f"404 from {url}")
```

with `class AtlassianNotFound(RuntimeError)` defined next to `AtlassianAuthError`. **Check `tests/test_atlassian_base.py` still passes** — the GET path's behavior (429 sleep, 5xx backoff, 401 → AtlassianAuthError) must be unchanged except 404 now raising AtlassianNotFound instead of `raise_for_status`'s HTTPError; if an existing test asserts HTTPError on 404, update it deliberately and note it in the commit message.

- [ ] **Step 4: Implement** `ghostbrain/connectors/atlassian/pages.py`:

```python
"""Confluence page write operations (create + tracked update)."""
from __future__ import annotations

from ghostbrain.connectors.atlassian._base import AtlassianClient, AtlassianNotFound


class PageGone(RuntimeError):
    """The tracked page no longer exists on Confluence."""


def _page_url(data: dict) -> str:
    links = data.get("_links") or {}
    return f"{links.get('base', '')}{links.get('webui', '')}"


def create_page(
    client: AtlassianClient,
    *,
    space_key: str,
    title: str,
    storage_html: str,
    parent_id: str | None = None,
) -> dict:
    body = {
        "type": "page",
        "title": title,
        "space": {"key": space_key},
        "body": {"storage": {"value": storage_html, "representation": "storage"}},
    }
    if parent_id:
        body["ancestors"] = [{"id": parent_id}]
    data = client.post("/wiki/rest/api/content", body)
    return {"page_id": str(data["id"]), "url": _page_url(data)}


def update_page(
    client: AtlassianClient, *, page_id: str, title: str, storage_html: str
) -> dict:
    try:
        current = client.get(f"/wiki/rest/api/content/{page_id}", params={"expand": "version"})
    except AtlassianNotFound as e:
        raise PageGone(page_id) from e
    version = int(((current.get("version") or {}).get("number")) or 1) + 1
    body = {
        "id": page_id,
        "type": "page",
        "title": title,
        "version": {"number": version},
        "body": {"storage": {"value": storage_html, "representation": "storage"}},
    }
    data = client.put(f"/wiki/rest/api/content/{page_id}", body)
    return {"page_id": str(data["id"]), "url": _page_url(data)}
```

- [ ] **Step 5: Verify pass** — `pytest tests/test_atlassian_pages.py tests/test_atlassian_base.py -v` → PASS
- [ ] **Step 6: Commit** — `git commit -m "feat(docs-assist): atlassian client POST/PUT + confluence page create/update"`

---

### Task 6: notes_manual — frontmatter stamping helper

**Files:** Modify `ghostbrain/api/repo/notes_manual.py`; Test `tests/test_notes_manual.py` (append; if jot repo tests live in a differently named file, append there)

- [ ] **Step 1: Write failing test**

```python
def test_set_frontmatter_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_VAULT", str(tmp_path))
    from ghostbrain.api.repo import notes_manual
    rec = notes_manual.write_inbox_jot("# Doc\n\nbody")
    notes_manual.set_frontmatter_fields(rec["id"], {"confluence_page_id": "123"})
    jot = notes_manual.read_jot(rec["id"])
    assert jot["frontmatter"]["confluence_page_id"] == "123"
    assert jot["body"] == "# Doc\n\nbody"  # body untouched
```

(Use the same vault fixture mechanism as existing notes tests.)

- [ ] **Step 2: Verify failure**, then **implement** in `notes_manual.py` (below `update_jot_body`):

```python
def set_frontmatter_fields(jot_id: str, fields: dict[str, Any]) -> dict:
    """Stamp arbitrary frontmatter fields without touching the body."""
    path = _find_file(jot_id)
    post = frontmatter.load(path)
    for key, value in fields.items():
        post[key] = value
    post["updated"] = _now_iso()
    path.write_text(frontmatter.dumps(post) + "\n", encoding="utf-8")
    return {"id": jot_id, "path": _vault_rel(path)}
```

- [ ] **Step 3: Verify pass + commit** — `git commit -m "feat(docs-assist): frontmatter stamping helper for jots"`

---

### Task 7: Confluence export repo + route

**Files:** Create `ghostbrain/api/repo/export_confluence.py`; Modify `ghostbrain/api/routes/docs.py`; Test `tests/test_export_confluence.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_export_confluence.py
from unittest.mock import MagicMock, patch

import pytest

from ghostbrain.api.repo import export_confluence, notes_manual
from ghostbrain.connectors.atlassian.pages import PageGone


@pytest.fixture()
def vault(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_VAULT", str(tmp_path))
    return tmp_path


def _patch_client():
    return patch.object(export_confluence, "_client_for_space", return_value=MagicMock())


def test_export_creates_and_stamps(vault):
    rec = notes_manual.write_inbox_jot("# RFC Title\n\nbody")
    with _patch_client(), patch.object(
        export_confluence.pages, "create_page",
        return_value={"page_id": "42", "url": "https://x/wiki/42"},
    ) as create:
        out = export_confluence.export_jot(rec["id"], space_key="K", parent_id=None, title=None, force_new=False)
    assert out["page_id"] == "42" and out["action"] == "created"
    assert create.call_args.kwargs["title"] == "RFC Title"
    fm = notes_manual.read_jot(rec["id"])["frontmatter"]
    assert fm["confluence_page_id"] == "42" and fm["confluence_url"] == "https://x/wiki/42"


def test_reexport_updates_tracked_page(vault):
    rec = notes_manual.write_inbox_jot("# T\n\nv1")
    notes_manual.set_frontmatter_fields(rec["id"], {"confluence_page_id": "42"})
    with _patch_client(), patch.object(
        export_confluence.pages, "update_page",
        return_value={"page_id": "42", "url": "https://x/wiki/42"},
    ):
        out = export_confluence.export_jot(rec["id"], space_key="K", parent_id=None, title=None, force_new=False)
    assert out["action"] == "updated"


def test_tracked_page_gone_raises(vault):
    rec = notes_manual.write_inbox_jot("# T\n\nv1")
    notes_manual.set_frontmatter_fields(rec["id"], {"confluence_page_id": "42"})
    with _patch_client(), patch.object(
        export_confluence.pages, "update_page", side_effect=PageGone("42"),
    ):
        with pytest.raises(export_confluence.TrackedPageGone):
            export_confluence.export_jot(rec["id"], space_key="K", parent_id=None, title=None, force_new=False)
    # no re-stamp happened — page id is still the stale one
    assert notes_manual.read_jot(rec["id"])["frontmatter"]["confluence_page_id"] == "42"


def test_force_new_creates_despite_tracking(vault):
    rec = notes_manual.write_inbox_jot("# T\n\nv1")
    notes_manual.set_frontmatter_fields(rec["id"], {"confluence_page_id": "42"})
    with _patch_client(), patch.object(
        export_confluence.pages, "create_page",
        return_value={"page_id": "99", "url": "https://x/wiki/99"},
    ):
        out = export_confluence.export_jot(rec["id"], space_key="K", parent_id=None, title=None, force_new=True)
    assert out["action"] == "created" and out["page_id"] == "99"
```

- [ ] **Step 2: Verify failure**, then **implement** `ghostbrain/api/repo/export_confluence.py`:

```python
"""Export a jot to Confluence: create a page, or update the page we created.

Frontmatter is the tracking store: ``confluence_page_id`` decides create vs
update. Frontmatter is only stamped AFTER the Atlassian call succeeded.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from ghostbrain.api.repo import notes_manual
from ghostbrain.api.repo.import_atlassian import (
    CONFLUENCE_NOT_CONFIGURED,
    ImportNotConfiguredError,
    _client,
    _confluence_config,
    _load_routing,
)
from ghostbrain.connectors.atlassian import pages
from ghostbrain.connectors.atlassian.markdown_out import to_storage_html

log = logging.getLogger("ghostbrain.export_confluence")

_H1 = re.compile(r"^#\s+(.+)$", re.MULTILINE)


class TrackedPageGone(RuntimeError):
    """Tracked confluence_page_id 404s remotely. Route maps to HTTP 409."""


def _title_for(jot: dict, override: str | None) -> str:
    if override:
        return override
    m = _H1.search(jot["body"])
    return m.group(1).strip() if m else jot["title"]


def _client_for_space(space_key: str):
    routing = _load_routing()
    sites, spaces = _confluence_config(routing)
    # All monitored spaces live on the configured sites; first site that the
    # space belongs to wins, else fall back to the first site.
    host = sites[0]
    return _client(host, not_configured=CONFLUENCE_NOT_CONFIGURED)


def export_jot(
    jot_id: str,
    *,
    space_key: str,
    parent_id: str | None,
    title: str | None,
    force_new: bool,
) -> dict:
    jot = notes_manual.read_jot(jot_id)  # raises JotNotFound → route 404
    client = _client_for_space(space_key)
    storage = to_storage_html(jot["body"])
    page_title = _title_for(jot, title)
    tracked = None if force_new else jot["frontmatter"].get("confluence_page_id")

    if tracked:
        try:
            result = pages.update_page(
                client, page_id=str(tracked), title=page_title, storage_html=storage
            )
            action = "updated"
        except pages.PageGone as e:
            raise TrackedPageGone(str(tracked)) from e
    else:
        result = pages.create_page(
            client,
            space_key=space_key,
            title=page_title,
            storage_html=storage,
            parent_id=parent_id,
        )
        action = "created"

    notes_manual.set_frontmatter_fields(jot_id, {
        "confluence_page_id": result["page_id"],
        "confluence_space": space_key,
        "confluence_url": result["url"],
        "confluence_exported_at": datetime.now(timezone.utc).isoformat(),
    })
    return {"action": action, "page_id": result["page_id"], "url": result["url"]}
```

(`_client`, `_confluence_config`, `_load_routing` are private in `import_atlassian.py` — importing them is acceptable within the package, but if review prefers, promote them to public names in `import_atlassian.py` first.)

- [ ] **Step 3: Add the route** to `ghostbrain/api/routes/docs.py`:

```python
from fastapi import HTTPException

from ghostbrain.api.repo import export_confluence
from ghostbrain.api.repo.import_atlassian import ImportNotConfiguredError
from ghostbrain.api.repo.notes_manual import JotNotFound
from ghostbrain.connectors.atlassian._base import AtlassianAuthError


@router.post("/export/confluence")
def export_to_confluence(payload: ConfluenceExportRequest) -> dict:
    try:
        return export_confluence.export_jot(
            payload.jot_id,
            space_key=payload.space_key,
            parent_id=payload.parent_id,
            title=payload.title,
            force_new=payload.force_new,
        )
    except JotNotFound:
        raise HTTPException(status_code=404, detail="jot not found")
    except ImportNotConfiguredError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except export_confluence.TrackedPageGone:
        raise HTTPException(
            status_code=409,
            detail="the Confluence page this jot was exported to no longer exists",
        )
    except AtlassianAuthError as e:
        raise HTTPException(status_code=502, detail=str(e))
```

Add route tests to `tests/test_docs_routes.py`: 200 happy path (mock `export_confluence.export_jot`), 404 on `JotNotFound`, 409 on `TrackedPageGone` (assert the detail message mentions "no longer exists").

- [ ] **Step 4: Verify** — `pytest tests/test_export_confluence.py tests/test_docs_routes.py -v` → PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(docs-assist): confluence export — create + tracked update with frontmatter stamping"`

---

### Task 8: desktop — shared types, docs SSE relay, preload bridge

**Files:** Modify `desktop/src/shared/api-types.ts`, `desktop/src/shared/types.ts`, `desktop/src/main/index.ts`, `desktop/src/preload/index.ts`; Create `desktop/src/main/docs-stream.ts`; Test `desktop/src/main/__tests__/docs-stream.test.ts`

- [ ] **Step 1: Types.** In `api-types.ts`, next to the chat event types: `export type DocsAssistEvent = ChatStreamEvent;` plus

```typescript
export type DocsAssistMode = 'draft' | 'polish' | 'expand' | 'summarize';
export interface DocsAssistRequest {
  jot_id: string;
  mode: DocsAssistMode;
  instruction?: string;
  selection?: string;
}
export interface ConfluenceExportRequest {
  jot_id: string;
  space_key: string;
  parent_id?: string;
  title?: string;
  force_new?: boolean;
}
export interface ConfluenceExportResponse {
  action: 'created' | 'updated';
  page_id: string;
  url: string;
}
```

In `shared/types.ts`, extend `GbBridge` (mirror the `chat` member):

```typescript
  docs: {
    assist: (req: DocsAssistRequest) => Promise<{ ok: true } | { ok: false; error: string }>;
    assistStop: (jotId: string) => Promise<void>;
    exportPdf: (payload: { title: string; html: string }) =>
      Promise<{ ok: true; path: string } | { ok: false; error: string } | { ok: false; cancelled: true }>;
  };
```

- [ ] **Step 2: Main relay.** Create `desktop/src/main/docs-stream.ts` as a near-copy of `chat-stream.ts` with: endpoint `POST /v1/docs/assist` (JSON body = the whole `DocsAssistRequest`), keyed by `jot_id`, stop calls nothing HTTP-side here (route stop handled in index.ts like chat). Reuse `createSseParser` by importing it from `./chat-stream`. Write `__tests__/docs-stream.test.ts` mirroring the existing chat-stream test (if `desktop/src/main/__tests__/` has one — check; at minimum test that `createSseParser` is reused and the URL/body are correct with a mocked `fetch`).

- [ ] **Step 3: IPC wiring** in `main/index.ts` (next to the `gb:chat:*` handlers, same shape):

```typescript
ipcMain.handle('gb:docs:assist', async (e, req: unknown) => {
  const r = req as DocsAssistRequest;
  return startDocsStream(sidecar, r, (event) => {
    const wc = e.sender;
    if (!wc.isDestroyed()) wc.send('gb:docs:event', { jotId: r.jot_id, event });
  });
});
ipcMain.handle('gb:docs:assist-stop', (_e, jotId: unknown) => {
  stopDocsStream(String(jotId));
  void forward(sidecar, 'POST', '/v1/docs/assist/stop', { jot_id: String(jotId) });
});
```

(Match `forward`'s actual signature from `api-forwarder.ts` — copy how the chat stop handler calls it.)

- [ ] **Step 4: Preload** — add to the bridge in `preload/index.ts`:

```typescript
  docs: {
    assist: (req) => ipcRenderer.invoke('gb:docs:assist', req),
    assistStop: (jotId) => ipcRenderer.invoke('gb:docs:assist-stop', jotId),
    exportPdf: (payload) => ipcRenderer.invoke('gb:docs:export-pdf', payload),
  },
```

(Renderer listens for events via the existing generic `gb.on('docs:event', …)` bridge member.)

- [ ] **Step 5: Verify** — `cd desktop && npm run typecheck && npm test` → PASS
- [ ] **Step 6: Commit** — `git commit -m "feat(docs-assist): docs SSE relay + IPC bridge"`

---

### Task 9: PDF export (main process)

**Files:** Create `desktop/src/main/pdf-export.ts`; Modify `desktop/src/main/index.ts`; Test `desktop/src/main/__tests__/pdf-export.test.ts`

- [ ] **Step 1: Implement** `desktop/src/main/pdf-export.ts`:

```typescript
import { BrowserWindow, dialog } from 'electron';
import { writeFile } from 'node:fs/promises';

const PRINT_CSS = `
  body { font: 13px/1.6 -apple-system, 'Helvetica Neue', sans-serif; color: #1a1a1a;
         max-width: 700px; margin: 40px auto; padding: 0 24px; }
  h1, h2, h3 { line-height: 1.3; } pre, code { font: 11px/1.5 ui-monospace, monospace;
  background: #f5f5f5; border-radius: 4px; } pre { padding: 12px; overflow-x: hidden; }
  code { padding: 1px 4px; } table { border-collapse: collapse; }
  th, td { border: 1px solid #ddd; padding: 6px 10px; text-align: left; }
  blockquote { border-left: 3px solid #ddd; margin-left: 0; padding-left: 16px; color: #555; }
`;

export function wrapPrintableHtml(title: string, bodyHtml: string): string {
  return `<!doctype html><html><head><meta charset="utf-8"><title>${escapeHtml(title)}</title><style>${PRINT_CSS}</style></head><body>${bodyHtml}</body></html>`;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

export async function exportPdf(
  parent: BrowserWindow | null,
  payload: { title: string; html: string },
): Promise<{ ok: true; path: string } | { ok: false; error: string } | { ok: false; cancelled: true }> {
  const safeName = payload.title.replace(/[\/\\:*?"<>|]/g, '-').slice(0, 80) || 'document';
  const picked = await dialog.showSaveDialog(parent ?? undefined!, {
    defaultPath: `${safeName}.pdf`,
    filters: [{ name: 'PDF', extensions: ['pdf'] }],
  });
  if (picked.canceled || !picked.filePath) return { ok: false, cancelled: true };

  const win = new BrowserWindow({ show: false, webPreferences: { sandbox: true } });
  try {
    const html = wrapPrintableHtml(payload.title, payload.html);
    await win.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
    const pdf = await win.webContents.printToPDF({ printBackground: true });
    await writeFile(picked.filePath, pdf);
    return { ok: true, path: picked.filePath };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  } finally {
    win.destroy();
  }
}
```

- [ ] **Step 2: Wire IPC** in `index.ts`: `ipcMain.handle('gb:docs:export-pdf', (e, payload) => exportPdf(BrowserWindow.fromWebContents(e.sender), payload as { title: string; html: string }));`

- [ ] **Step 3: Test** `wrapPrintableHtml` (pure): title is escaped, body passed through, style present. Electron window behavior is covered by manual E2E.

- [ ] **Step 4: Verify** — `npm run typecheck && npm test && npm run lint` → PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(docs-assist): pdf export via hidden window printToPDF"`

---

### Task 10: RichMarkdownEditor imperative handle

**Files:** Modify `desktop/src/renderer/components/RichMarkdownEditor.tsx`; Test in existing editor test file (`desktop/src/renderer/components/__tests__/` — locate the RichMarkdownEditor test and append)

- [ ] **Step 1: Add a `handleRef` prop:**

```typescript
export interface EditorHandle {
  /** Markdown for the current selection; '' when collapsed. */
  getSelectionMarkdown: () => string;
  /** Replace current selection (or whole doc when none) with markdown. */
  replaceWith: (markdown: string, target: 'selection' | 'doc') => void;
  /** Full document as HTML (for PDF export). */
  getHTML: () => string;
  /** Full document as markdown. */
  getMarkdown: () => string;
}

interface Props {
  // …existing…
  handleRef?: React.MutableRefObject<EditorHandle | null>;
}
```

Inside the component, after `useEditor` returns, populate it (rich mode; in source mode fall back to whole-doc semantics using `current.current`):

```typescript
useEffect(() => {
  if (!handleRef) return;
  handleRef.current = {
    getSelectionMarkdown: () => {
      if (!editor || mode !== 'rich') return '';
      const { from, to } = editor.state.selection;
      if (from === to) return '';
      // Slice the markdown via the doc text between positions: serialize the
      // selected slice through the same pipeline getMarkdown uses.
      return getMarkdown(editor, { from, to });
    },
    replaceWith: (md, target) => {
      if (editor && mode === 'rich') {
        if (target === 'selection') editor.chain().focus().insertContent(md).run();
        else editor.commands.setContent(md);
        const next = getMarkdown(editor);
        scheduleSave(next);
      } else {
        // source mode: whole-doc replacement only
        current.current = md;
        scheduleSave(md);
      }
    },
    getHTML: () => (editor && mode === 'rich' ? editor.getHTML() : ''),
    getMarkdown: () => current.current,
  };
  return () => { if (handleRef) handleRef.current = null; };
}, [editor, mode, handleRef]);
```

**Check `lib/editor/markdown.ts` first:** if `getMarkdown` doesn't support a range, implement `getSelectionMarkdown` by serializing `editor.state.doc.textBetween(from, to, '\n')` instead (plain-text selection is acceptable for v1 — the LLM receives it as the selection content) and note it in the component comment.

- [ ] **Step 2: Tests** — append to the editor's existing vitest file: handle is populated on mount; `replaceWith(md,'doc')` triggers `onSave` with the new markdown after debounce (use fake timers, mirror existing autosave tests).

- [ ] **Step 3: Verify** — `npm test -- RichMarkdownEditor && npm run typecheck` → PASS
- [ ] **Step 4: Commit** — `git commit -m "feat(docs-assist): editor imperative handle — selection, replace, html"`

---

### Task 11: docs-assist store + DocsAssistPanel

**Files:** Create `desktop/src/renderer/stores/docs-assist.ts`, `desktop/src/renderer/components/DocsAssistPanel.tsx`; Test `desktop/src/renderer/stores/__tests__/docs-assist.test.ts` (mirror where existing store tests live — check `stores/` for test placement convention first)

- [ ] **Step 1: Store (state machine):**

```typescript
import { create } from 'zustand';
import type { DocsAssistMode } from '../../shared/api-types';

export type AssistTarget = 'selection' | 'doc';
export type AssistPhase = 'idle' | 'streaming' | 'proposal' | 'error';

interface DocsAssistState {
  open: boolean;
  phase: AssistPhase;
  jotId: string | null;
  target: AssistTarget;
  mode: DocsAssistMode;
  /** Original selection text the proposal replaces (for preview). */
  selection: string;
  streamed: string;
  error: string | null;
  toggleOpen: () => void;
  start: (p: { jotId: string; mode: DocsAssistMode; target: AssistTarget; selection: string }) => void;
  appendDelta: (text: string) => void;
  finish: (fullText: string) => void;
  fail: (message: string) => void;
  reset: () => void;
}

export const useDocsAssist = create<DocsAssistState>((set) => ({
  open: false,
  phase: 'idle',
  jotId: null,
  target: 'doc',
  mode: 'polish',
  selection: '',
  streamed: '',
  error: null,
  toggleOpen: () => set((s) => ({ open: !s.open })),
  start: ({ jotId, mode, target, selection }) =>
    set({ phase: 'streaming', jotId, mode, target, selection, streamed: '', error: null }),
  appendDelta: (text) => set((s) => ({ streamed: s.streamed + text })),
  finish: (fullText) => set((s) => ({ phase: 'proposal', streamed: fullText || s.streamed })),
  fail: (message) => set({ phase: 'error', error: message }),
  reset: () => set({ phase: 'idle', streamed: '', error: null, selection: '' }),
}));
```

Store tests: full transition path idle→streaming→proposal (`finish('')` keeps accumulated deltas), streaming→error, reset from each phase.

- [ ] **Step 2: Panel component** `DocsAssistPanel.tsx` — props `{ jotId: string; editorHandle: React.MutableRefObject<EditorHandle | null> }`. Behavior:
  - quick-action buttons (polish / expand / summarize) + a textarea + "go" button (mode `draft` when instruction non-empty and no selection, else keeps selected quick-action semantics);
  - on submit: read `editorHandle.current?.getSelectionMarkdown()`; `target = selection ? 'selection' : 'doc'`; `store.start(...)`; subscribe `window.gb.on('docs:event', ...)` filtered by `jotId`; call `window.gb.docs.assist({ jot_id, mode, instruction, selection: selection || undefined })`;
  - events: `delta` → `appendDelta`; `done` → `finish(text)`; `error` → `fail(message)`;
  - **streaming view**: live `streamed` text in a scrolling `<pre className="whitespace-pre-wrap">` + stop button (`window.gb.docs.assistStop(jotId)`);
  - **proposal view**: rendered preview (use `MarkdownBody`), Accept → `editorHandle.current?.replaceWith(streamed, target); store.reset()`; Discard → `store.reset()`;
  - **error view**: message + Retry (re-submit last request) — mirror `PanelError` styling;
  - subscription cleanup on unmount; switching jots while streaming calls `assistStop` + `reset` (effect on `jotId`).
  Use `Btn`, `Panel`, `Eyebrow` components to match app styling.

- [ ] **Step 3: Verify** — `npm test -- docs-assist && npm run typecheck && npm run lint` → PASS
- [ ] **Step 4: Commit** — `git commit -m "feat(docs-assist): assist store + panel component"`

---

### Task 12: export hooks, dialog, jots screen integration

**Files:** Modify `desktop/src/renderer/lib/api/hooks.ts`, `desktop/src/renderer/screens/jots.tsx`; Create `desktop/src/renderer/components/ConfluenceExportDialog.tsx`

- [ ] **Step 1: Hook** (in `hooks.ts`, mirror `useUpdateJot`'s mutation shape):

```typescript
export function useExportConfluence() {
  return useMutation({
    mutationFn: (req: ConfluenceExportRequest) =>
      api<ConfluenceExportResponse>('POST', '/v1/docs/export/confluence', req),
  });
}
```

(Match the actual request helper name/signature used by other mutations in the file.)

- [ ] **Step 2: Dialog** `ConfluenceExportDialog.tsx` — props `{ jotId: string; defaultTitle: string; onClose: () => void }`:
  - `useImportSpaces()` for the space list (already exists); space `<select>`; optional parent: fetch pages for the chosen space via the existing import pages hook if present (check `hooks.ts` around `useImportSpaces` — if a `useImportPages(spaceKey)` exists, use it; otherwise parent stays a free-text page-id input labeled "parent page id (optional)" for v1);
  - remember last `{spaceKey, parentId}` in the settings store (`stores/settings.ts` pattern) under key `docsExportDestination`;
  - Export button → `useExportConfluence().mutate`; on success toast `exported — <action>` and offer "open" via `window.gb.shell.openExternal(url)`; on 409 "no longer exists" error, show inline "page was deleted on Confluence — export as new?" button that retries with `force_new: true`; other errors → error toast.

- [ ] **Step 3: jots.tsx integration:**
  - `const editorHandle = useRef<EditorHandle | null>(null);` passed to `<RichMarkdownEditor handleRef={editorHandle} …/>`;
  - TopBar `right`: add a ghost `Btn` "assist" toggling `useDocsAssist.getState().toggleOpen()`; when open, render `<DocsAssistPanel jotId={selectedId} editorHandle={editorHandle} />` as a right-hand `<aside className="w-[320px] …">` inside the existing flex row (after `<main>`);
  - footer: add an "export…" `<select>` (mirror the existing re-route select) with options `confluence` / `pdf`:
    - `confluence` → gate: `useConnectors()` data contains a confluence/atlassian connector with state `'on'`; if not, the option is `disabled`; selecting opens `ConfluenceExportDialog`;
    - `pdf` → `window.gb.docs.exportPdf({ title: selectedItem?.title ?? 'document', html: editorHandle.current?.getHTML() ?? '' })`; toast on success/error; no-op toast "switch to rich mode to export pdf" when html is `''`.

- [ ] **Step 4: Verify** — `npm run typecheck && npm run lint && npm test` → all PASS
- [ ] **Step 5: Commit** — `git commit -m "feat(docs-assist): jots screen — assist panel, confluence export dialog, pdf download"`

---

### Task 13: full verification + spec status

- [ ] **Step 1:** `pytest` (full suite) from repo root → PASS
- [ ] **Step 2:** `cd desktop && npm run typecheck && npm run lint && npm test` → PASS
- [ ] **Step 3: Manual E2E** (requires running app — flag for human if no display):
  1. open a jot → assist panel → "polish" with a selection → proposal → accept → body updated + autosaved;
  2. empty jot → instruction "write a short doc about the activity heatmap from the vault" → draft streams, tools show vault searches → accept;
  3. export → confluence (sandbox space) twice → first creates, second updates (check page version bumped);
  4. export → pdf → file opens in Preview.
- [ ] **Step 4:** Update spec `Implementation status` section + this plan's checkboxes; commit `docs(docs-assist): implementation status`.

---

## Self-review notes

- Spec coverage: assist route/panel (T1–T3, T10–T11), Confluence export incl. 409 re-export flow (T4–T7, T12), PDF (T9, T12), connector gating (T12), error handling (T3/T7 route mapping, T11 error view), tests per spec section.
- Deviation from spec: PDF HTML comes from the renderer's TipTap `getHTML()` (sent to main) rather than main re-rendering markdown — avoids bundling a markdown renderer into the main process; same visual pipeline the user edits in.
- Executors MUST verify assumed details against the real files before coding each task (marked inline): conftest vault fixture name, `create_app` signature, `forward()` signature, `getMarkdown` range support, existing import-pages hook, store test placement.
