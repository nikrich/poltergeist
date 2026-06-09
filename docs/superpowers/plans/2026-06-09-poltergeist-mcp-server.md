# Poltergeist MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the Poltergeist vault's `ask`/`search`/`get_note` retrieval surface as MCP tools so Claude Code & Desktop can query the brain through the already-running sidecar, plus an installable `poltergeist-recall` skill.

**Architecture:** A thin Python stdio MCP server (`ghostbrain-mcp`) discovers the running FastAPI sidecar via a new on-disk runtime descriptor (`~/ghostbrain/run/sidecar.json`), then forwards each tool call over local HTTP with the sidecar's bearer token. The shim holds no retrieval logic — all embedding/LLM work stays in the warm daemon. Tool *logic* lives in plain, unit-testable functions; the MCP transport wrapper is a thin shell over them.

**Tech Stack:** Python 3.11, the `mcp` SDK (`FastMCP`, stdio transport), `httpx`, FastAPI sidecar (existing), pytest.

**Spec:** `docs/superpowers/specs/2026-06-08-poltergeist-mcp-server-design.md`

---

## File Structure

**Create:**
- `ghostbrain/api/runtime.py` — runtime-descriptor location, schema, atomic write (`chmod 600`), `load_descriptor()` with pid-liveness check, `remove_descriptor()`.
- `ghostbrain/mcp/__init__.py` — package marker.
- `ghostbrain/mcp/client.py` — `SidecarClient` (descriptor discovery + httpx-with-token) and `SidecarNotRunning`.
- `ghostbrain/mcp/tools.py` — `ask()` / `search()` / `get_note()` plain functions that format sidecar responses into agent-facing text.
- `ghostbrain/mcp/__main__.py` — `FastMCP` server registering the three tools + `main()` (stdio).
- `.claude/skills/poltergeist-recall/SKILL.md` — install/verify the MCP connection.
- `.claude/skills/poltergeist-recall/using.md` — when/how Claude should query the brain.
- `tests/test_mcp_runtime.py`, `tests/test_mcp_client.py`, `tests/test_mcp_tools.py`, `tests/test_mcp_server.py`, `tests/test_mcp_integration.py`.

**Modify:**
- `ghostbrain/api/__main__.py` — publish the descriptor on boot, remove it on exit.
- `pyproject.toml` — new `mcp` optional-dependency extra + `ghostbrain-mcp` console script.
- `README.md` — MCP setup section + `.mcp.json` snippet.

**Note on package naming:** our new subpackage is `ghostbrain.mcp`; the third-party SDK is the top-level `mcp`. Python 3 absolute imports resolve `from mcp.server.fastmcp import FastMCP` to the site-packages package, *not* our subpackage — there is no shadowing. Do not use relative `from . import ...` to reach the SDK.

---

## Task 1: Runtime descriptor module

**Files:**
- Create: `ghostbrain/api/runtime.py`
- Test: `tests/test_mcp_runtime.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_runtime.py
import json
import os
import stat

import pytest

from ghostbrain.api import runtime


@pytest.fixture(autouse=True)
def _run_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("GHOSTBRAIN_RUN_DIR", str(tmp_path / "run"))
    yield


def test_write_then_load_round_trips():
    runtime.write_descriptor(
        port=51234,
        token="deadbeef",
        pid=os.getpid(),
        version="1.0.0",
        started_at="2026-06-09T09:30:15+02:00",
    )
    d = runtime.load_descriptor()
    assert d is not None
    assert d["port"] == 51234
    assert d["token"] == "deadbeef"
    assert d["pid"] == os.getpid()
    assert d["version"] == "1.0.0"


def test_descriptor_file_is_chmod_600():
    runtime.write_descriptor(
        port=1, token="t", pid=os.getpid(), version="1.0.0", started_at="x"
    )
    mode = stat.S_IMODE(os.stat(runtime.descriptor_path()).st_mode)
    assert mode == 0o600


def test_load_missing_returns_none():
    assert runtime.load_descriptor() is None


def test_load_unparseable_returns_none():
    runtime.run_dir().mkdir(parents=True, exist_ok=True)
    runtime.descriptor_path().write_text("{not json")
    assert runtime.load_descriptor() is None


def test_load_dead_pid_returns_none():
    # PID 999999 is virtually certain not to exist.
    runtime.write_descriptor(
        port=1, token="t", pid=999999, version="1.0.0", started_at="x"
    )
    assert runtime.load_descriptor() is None


def test_remove_is_idempotent():
    runtime.write_descriptor(
        port=1, token="t", pid=os.getpid(), version="1.0.0", started_at="x"
    )
    runtime.remove_descriptor()
    runtime.remove_descriptor()  # second call must not raise
    assert runtime.load_descriptor() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_runtime.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.api.runtime'`

- [ ] **Step 3: Write the implementation**

```python
# ghostbrain/api/runtime.py
"""On-disk descriptor advertising the running sidecar to local MCP clients.

The sidecar picks a random port + bearer token on every boot and prints them
to stdout for the Electron parent. The MCP shim is spawned independently by
Claude Code, so it can't see that banner. This module persists {port, token,
pid, ...} to ~/ghostbrain/run/sidecar.json on boot (chmod 600 — it holds the
token) and removes it on exit. Readers liveness-check the pid so a crash-
leftover file reads as "not running".
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def run_dir() -> Path:
    """Directory for runtime state. Override with GHOSTBRAIN_RUN_DIR (tests)."""
    raw = os.environ.get("GHOSTBRAIN_RUN_DIR")
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / "ghostbrain" / "run").resolve()


def descriptor_path() -> Path:
    return run_dir() / "sidecar.json"


def write_descriptor(
    *, port: int, token: str, pid: int, version: str, started_at: str
) -> Path:
    """Atomically write the descriptor with 0600 perms. Returns its path."""
    d = run_dir()
    d.mkdir(parents=True, exist_ok=True)
    target = descriptor_path()
    tmp = target.with_name(target.name + ".tmp")
    payload = json.dumps(
        {
            "port": port,
            "token": token,
            "pid": pid,
            "version": version,
            "started_at": started_at,
        }
    )
    tmp.write_text(payload)
    os.chmod(tmp, 0o600)
    os.replace(tmp, target)
    return target


def load_descriptor() -> dict | None:
    """Return the descriptor dict, or None if absent/unparseable/process-dead."""
    path = descriptor_path()
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    pid = data.get("pid")
    if not isinstance(pid, int):
        return None
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None  # process is gone
    except PermissionError:
        pass  # alive but owned by another user — still "running"
    except OSError:
        return None
    return data


def remove_descriptor() -> None:
    """Best-effort delete. Never raises."""
    try:
        descriptor_path().unlink(missing_ok=True)
    except OSError:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_runtime.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/runtime.py tests/test_mcp_runtime.py
git commit -m "feat(api): runtime descriptor for sidecar discovery"
```

---

## Task 2: Publish the descriptor from the sidecar boot path

**Files:**
- Modify: `ghostbrain/api/__main__.py`
- Test: `tests/test_mcp_runtime.py` (add one test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_mcp_runtime.py`:

```python
def test_publish_descriptor_writes_current_process(monkeypatch, tmp_path):
    monkeypatch.setenv("GHOSTBRAIN_RUN_DIR", str(tmp_path / "run2"))
    from ghostbrain.api.__main__ import _publish_descriptor

    _publish_descriptor(port=40404, token="abc123")
    d = runtime.load_descriptor()
    assert d is not None
    assert d["port"] == 40404
    assert d["token"] == "abc123"
    assert d["pid"] == os.getpid()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mcp_runtime.py::test_publish_descriptor_writes_current_process -v`
Expected: FAIL with `ImportError: cannot import name '_publish_descriptor'`

- [ ] **Step 3: Implement `_publish_descriptor` and wire it into `main()`**

In `ghostbrain/api/__main__.py`, add these imports near the other stdlib imports (after `import sys`):

```python
import atexit
import signal
from datetime import datetime
```

Add this function above `def main()`:

```python
def _publish_descriptor(port: int, token: str) -> None:
    """Write the runtime descriptor and register removal on exit."""
    from ghostbrain.api import runtime
    from ghostbrain.api.main import API_VERSION

    runtime.write_descriptor(
        port=port,
        token=token,
        pid=os.getpid(),
        version=API_VERSION,
        started_at=datetime.now().astimezone().isoformat(),
    )
    atexit.register(runtime.remove_descriptor)

    def _on_signal(signum, frame):  # noqa: ANN001, ARG001
        runtime.remove_descriptor()
        raise SystemExit(0)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _on_signal)
        except (ValueError, OSError):
            # signal() only works on the main thread; ignore if not.
            pass
```

Then, in `main()`, immediately after the line `app = create_app(token=token)`, add:

```python
    _publish_descriptor(port=port, token=token)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mcp_runtime.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/__main__.py tests/test_mcp_runtime.py
git commit -m "feat(api): publish runtime descriptor on sidecar boot"
```

---

## Task 3: Dependencies, entrypoint, package marker

**Files:**
- Modify: `pyproject.toml`
- Create: `ghostbrain/mcp/__init__.py`

- [ ] **Step 1: Add the `mcp` optional-dependency extra**

In `pyproject.toml`, under `[project.optional-dependencies]`, after the `api = [ ... ]` block, add:

```toml
mcp = [
    "mcp>=1.2.0",
    "httpx>=0.27.0",
]
```

- [ ] **Step 2: Add the console script**

In `pyproject.toml` under `[project.scripts]`, add this line (alphabetical order is not required; append it):

```toml
ghostbrain-mcp = "ghostbrain.mcp.__main__:main"
```

- [ ] **Step 3: Create the package marker**

```python
# ghostbrain/mcp/__init__.py
"""Poltergeist MCP server — exposes the vault's retrieval surface over MCP."""
```

- [ ] **Step 4: Install the new extra and verify the SDK imports**

Run: `pip install -e ".[mcp]" && python -c "from mcp.server.fastmcp import FastMCP; print('ok')"`
Expected: prints `ok`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml ghostbrain/mcp/__init__.py
git commit -m "build(mcp): add mcp extra + ghostbrain-mcp entrypoint"
```

---

## Task 4: Sidecar HTTP client

**Files:**
- Create: `ghostbrain/mcp/client.py`
- Test: `tests/test_mcp_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_client.py
import httpx
import pytest

from ghostbrain.mcp.client import SidecarClient, SidecarNotRunning


def _client(handler, descriptor):
    """Build a SidecarClient whose HTTP layer is a MockTransport."""
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return SidecarClient(loader=lambda: descriptor, http_client=http)


DESCRIPTOR = {"port": 51234, "token": "secret-tok", "pid": 1, "version": "1.0.0"}


def test_answer_posts_with_bearer_token():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"] = request.method
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"answer": "hi", "sources": []})

    out = _client(handler, DESCRIPTOR).answer("why?", limit=5)
    assert out == {"answer": "hi", "sources": []}
    assert seen["method"] == "POST"
    assert seen["url"] == "http://127.0.0.1:51234/v1/answer"
    assert seen["auth"] == "Bearer secret-tok"
    assert '"q": "why?"' in seen["body"] or '"q":"why?"' in seen["body"]
    assert "5" in seen["body"]


def test_search_posts_to_search_endpoint():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == "http://127.0.0.1:51234/v1/search"
        return httpx.Response(200, json={"items": [], "total": 0, "query": "x"})

    out = _client(handler, DESCRIPTOR).search("x", limit=10)
    assert out["total"] == 0


def test_get_note_gets_with_path_query():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/v1/notes"
        assert request.url.params.get("path") == "20-contexts/sanlam/x.md"
        return httpx.Response(200, json={"path": "p", "title": "t", "body": "b", "frontmatter": {}})

    out = _client(handler, DESCRIPTOR).get_note("20-contexts/sanlam/x.md")
    assert out["title"] == "t"


def test_no_descriptor_raises_not_running():
    client = SidecarClient(loader=lambda: None, http_client=httpx.Client())
    with pytest.raises(SidecarNotRunning):
        client.answer("q", limit=1)


def test_connection_refused_raises_not_running():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    with pytest.raises(SidecarNotRunning):
        _client(handler, DESCRIPTOR).search("x", limit=1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.mcp.client'`

- [ ] **Step 3: Write the implementation**

```python
# ghostbrain/mcp/client.py
"""Discover and call the running Poltergeist sidecar over local HTTP."""
from __future__ import annotations

from typing import Any, Callable

import httpx

from ghostbrain.api.runtime import load_descriptor

NOT_RUNNING_MESSAGE = "Poltergeist isn't running — open the Poltergeist app to start it."

# answer can take ~5-15s on sonnet; allow generous headroom.
DEFAULT_TIMEOUT = 60.0


class SidecarNotRunning(RuntimeError):
    """Raised when no live sidecar can be reached."""


class SidecarClient:
    """Thin HTTP client bound to the sidecar advertised by the descriptor."""

    def __init__(
        self,
        *,
        loader: Callable[[], dict | None] = load_descriptor,
        http_client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._loader = loader
        self._http = http_client or httpx.Client(timeout=timeout)

    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        descriptor = self._loader()
        if not descriptor:
            raise SidecarNotRunning(NOT_RUNNING_MESSAGE)
        url = f"http://127.0.0.1:{descriptor['port']}{path}"
        headers = {"Authorization": f"Bearer {descriptor['token']}"}
        try:
            resp = self._http.request(method, url, headers=headers, **kwargs)
        except httpx.ConnectError as e:
            raise SidecarNotRunning(NOT_RUNNING_MESSAGE) from e
        resp.raise_for_status()
        return resp.json()

    def answer(self, q: str, limit: int = 8) -> dict:
        return self._request("POST", "/v1/answer", json={"q": q, "limit": limit})

    def search(self, q: str, limit: int = 10) -> dict:
        return self._request("POST", "/v1/search", json={"q": q, "limit": limit})

    def get_note(self, path: str) -> dict:
        return self._request("GET", "/v1/notes", params={"path": path})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_client.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/mcp/client.py tests/test_mcp_client.py
git commit -m "feat(mcp): sidecar HTTP client with descriptor discovery"
```

---

## Task 5: Tool functions (format sidecar responses for agents)

**Files:**
- Create: `ghostbrain/mcp/tools.py`
- Test: `tests/test_mcp_tools.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mcp_tools.py
from ghostbrain.mcp import tools


class FakeClient:
    def __init__(self, answer=None, search=None, note=None):
        self._answer, self._search, self._note = answer, search, note
        self.calls = []

    def answer(self, q, limit=8):
        self.calls.append(("answer", q, limit))
        return self._answer

    def search(self, q, limit=10):
        self.calls.append(("search", q, limit))
        return self._search

    def get_note(self, path):
        self.calls.append(("get_note", path))
        return self._note


def test_ask_includes_answer_and_source_paths():
    client = FakeClient(answer={
        "answer": "Use sonnet.",
        "sources": [
            {"path": "20-contexts/sanlam/a.md", "title": "A", "score": 0.81, "snippet": "..."},
            {"path": "20-contexts/codeship/b.md", "title": "B", "score": 0.77, "snippet": "..."},
        ],
    })
    out = tools.ask(client, "which model?", limit=5)
    assert "Use sonnet." in out
    assert "20-contexts/sanlam/a.md" in out
    assert "20-contexts/codeship/b.md" in out
    assert client.calls == [("answer", "which model?", 5)]


def test_ask_reports_empty_answer_error():
    client = FakeClient(answer={"answer": "", "sources": [], "error": "LLMTimeout: timed out"})
    out = tools.ask(client, "q")
    assert "LLMTimeout" in out


def test_search_lists_ranked_hits():
    client = FakeClient(search={"total": 1, "items": [
        {"path": "p.md", "title": "T", "score": 0.9, "snippet": "snip"},
    ]})
    out = tools.search(client, "x", limit=3)
    assert "p.md" in out
    assert "T" in out
    assert "snip" in out
    assert client.calls == [("search", "x", 3)]


def test_search_empty_says_no_matches():
    client = FakeClient(search={"total": 0, "items": []})
    out = tools.search(client, "x")
    assert "no" in out.lower()


def test_get_note_renders_title_and_body():
    client = FakeClient(note={"path": "p.md", "title": "Title", "body": "Body text", "frontmatter": {"context": "sanlam"}})
    out = tools.get_note(client, "p.md")
    assert "Title" in out
    assert "Body text" in out
    assert "p.md" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_mcp_tools.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.mcp.tools'`

- [ ] **Step 3: Write the implementation**

```python
# ghostbrain/mcp/tools.py
"""Format sidecar responses into agent-facing markdown text.

These are plain functions taking a client object (any object exposing
.answer/.search/.get_note). The MCP transport wrapper in __main__ is a thin
shell over them; keeping the logic here makes it unit-testable without the
MCP runtime.
"""
from __future__ import annotations

from typing import Protocol


class _Client(Protocol):
    def answer(self, q: str, limit: int = 8) -> dict: ...
    def search(self, q: str, limit: int = 10) -> dict: ...
    def get_note(self, path: str) -> dict: ...


def ask(client: _Client, question: str, limit: int = 8) -> str:
    data = client.answer(question, limit=limit)
    answer = (data.get("answer") or "").strip()
    error = data.get("error")
    sources = data.get("sources") or []

    if not answer and error:
        return f"Poltergeist could not answer: {error}"
    if not answer:
        return "The vault has no notes matching this question yet."

    lines = [answer, "", "Sources:"]
    if sources:
        for i, s in enumerate(sources, start=1):
            lines.append(f"[{i}] {s.get('title') or s.get('path')} — {s.get('path')}")
    else:
        lines.append("(none)")
    return "\n".join(lines)


def search(client: _Client, query: str, limit: int = 10) -> str:
    data = client.search(query, limit=limit)
    items = data.get("items") or []
    if not items:
        return "No matching notes found in the vault."

    lines = [f"{len(items)} matches:"]
    for i, hit in enumerate(items, start=1):
        score = hit.get("score")
        score_str = f"{score:.2f}" if isinstance(score, (int, float)) else "?"
        lines.append(f"[{i}] {hit.get('title') or hit.get('path')}  (score {score_str})")
        lines.append(f"    {hit.get('path')}")
        snippet = (hit.get("snippet") or "").strip().replace("\n", " ")
        if snippet:
            lines.append(f"    {snippet}")
    return "\n".join(lines)


def get_note(client: _Client, path: str) -> str:
    data = client.get_note(path)
    title = data.get("title") or data.get("path") or path
    fm = data.get("frontmatter") or {}
    body = data.get("body") or ""
    context = fm.get("context")
    header = f"# {title}\n`{data.get('path', path)}`"
    if context:
        header += f"  ·  context: {context}"
    return f"{header}\n\n{body}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_mcp_tools.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/mcp/tools.py tests/test_mcp_tools.py
git commit -m "feat(mcp): tool functions formatting ask/search/get_note"
```

---

## Task 6: MCP server (FastMCP + stdio)

**Files:**
- Create: `ghostbrain/mcp/__main__.py`
- Test: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_server.py
import asyncio


def test_server_registers_three_tools():
    from ghostbrain.mcp.__main__ import build_server

    server = build_server()
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert names == {"poltergeist_ask", "poltergeist_search", "poltergeist_get_note"}


def test_tools_have_nonempty_descriptions():
    from ghostbrain.mcp.__main__ import build_server

    server = build_server()
    tools = asyncio.run(server.list_tools())
    for t in tools:
        assert t.description and len(t.description) > 20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mcp_server.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ghostbrain.mcp.__main__'`

- [ ] **Step 3: Write the implementation**

```python
# ghostbrain/mcp/__main__.py
"""Poltergeist MCP server. Run via the `ghostbrain-mcp` console script.

Thin stdio shell over ghostbrain.mcp.tools, which forward to the running
sidecar through ghostbrain.mcp.client. Tool descriptions are written for an
agent audience — they steer Claude toward the right tool and good chaining.
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from ghostbrain.mcp import tools
from ghostbrain.mcp.client import SidecarClient


def build_server(client: SidecarClient | None = None) -> FastMCP:
    client = client or SidecarClient()
    mcp = FastMCP("poltergeist")

    @mcp.tool()
    def poltergeist_ask(question: str, limit: int = 8) -> str:
        """Ask a natural-language question about the user's own work, history,
        and decisions across all their contexts. Returns a synthesized answer
        with citations. Costs an LLM call (~5-15s) — prefer poltergeist_search
        when you only need to locate notes."""
        return tools.ask(client, question, limit=limit)

    @mcp.tool()
    def poltergeist_search(query: str, limit: int = 10) -> str:
        """Semantic search across the user's vault. Cheap and fast (no LLM).
        Returns ranked note paths with snippets; follow up with
        poltergeist_get_note to read a full note."""
        return tools.search(client, query, limit=limit)

    @mcp.tool()
    def poltergeist_get_note(path: str) -> str:
        """Fetch the full content and metadata of one vault note by its
        vault-relative path (as returned by poltergeist_search or a citation
        from poltergeist_ask)."""
        return tools.get_note(client, path)

    return mcp


def main() -> None:
    build_server().run()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mcp_server.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/mcp/__main__.py tests/test_mcp_server.py
git commit -m "feat(mcp): FastMCP stdio server with three tools"
```

---

## Task 7: End-to-end integration test (real app, no ML)

**Files:**
- Test: `tests/test_mcp_integration.py`

This drives the real client + tools against the real FastAPI app via an ASGI
transport (no live server, no embedding model). It covers `get_note` end-to-end
(which needs no ML) and the "not running" path. `ask`/`search` request wiring is
already proven by `tests/test_mcp_client.py`; their semantic results are the
sidecar's own (separately tested) behaviour.

- [ ] **Step 1: Write the test**

```python
# tests/test_mcp_integration.py
import httpx
import pytest

from ghostbrain.api.main import create_app
from ghostbrain.mcp import tools
from ghostbrain.mcp.client import SidecarClient, SidecarNotRunning


@pytest.fixture
def seeded_vault(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    note_dir = vault / "20-contexts" / "sanlam" / "notes"
    note_dir.mkdir(parents=True)
    (note_dir / "x.md").write_text(
        "---\ntitle: ASCP wizard\ncontext: sanlam\n---\n\nUse Cognito session refresh.\n"
    )
    monkeypatch.setenv("VAULT_PATH", str(vault))
    return vault


def _client_for(app, token):
    transport = httpx.ASGITransport(app=app)
    http = httpx.Client(transport=transport)
    return SidecarClient(
        loader=lambda: {"port": 1, "token": token, "pid": 1, "version": "1.0.0"},
        http_client=http,
    )


def test_get_note_end_to_end(seeded_vault):
    app = create_app(token="test-token")
    client = _client_for(app, "test-token")
    out = tools.get_note(client, "20-contexts/sanlam/notes/x.md")
    assert "ASCP wizard" in out
    assert "Cognito session refresh" in out
    assert "context: sanlam" in out


def test_bad_token_is_rejected(seeded_vault):
    app = create_app(token="real-token")
    client = _client_for(app, "wrong-token")
    with pytest.raises(httpx.HTTPStatusError):
        tools.get_note(client, "20-contexts/sanlam/notes/x.md")


def test_not_running_path():
    client = SidecarClient(loader=lambda: None, http_client=httpx.Client())
    with pytest.raises(SidecarNotRunning):
        tools.get_note(client, "anything.md")
```

- [ ] **Step 2: Run the test**

Run: `pytest tests/test_mcp_integration.py -v`
Expected: PASS (3 tests). If `get_note` returns 404, confirm the seeded note path matches the requested `path` exactly.

- [ ] **Step 3: Run the whole MCP suite**

Run: `pytest tests/test_mcp_runtime.py tests/test_mcp_client.py tests/test_mcp_tools.py tests/test_mcp_server.py tests/test_mcp_integration.py -v`
Expected: PASS (all)

- [ ] **Step 4: Commit**

```bash
git add tests/test_mcp_integration.py
git commit -m "test(mcp): end-to-end get_note + not-running integration"
```

---

## Task 8: `poltergeist-recall` skill

**Files:**
- Create: `.claude/skills/poltergeist-recall/SKILL.md`
- Create: `.claude/skills/poltergeist-recall/using.md`

- [ ] **Step 1: Write `SKILL.md`**

```markdown
---
name: poltergeist-recall
description: Use to connect Poltergeist (the ghostbrain second-brain) to Claude Code/Desktop over MCP, and to query the user's vault during work. Triggers include "connect Poltergeist to Claude", "set up the Poltergeist MCP", "query my second brain/vault from here", or any moment where recalling the user's own prior decisions, past incidents, or why something was built a certain way would help.
---

# Poltergeist Recall

Query the user's Poltergeist vault from Claude via the `poltergeist` MCP server.
Two jobs: **install** the connection, then **use** it well during work.

## Install / verify the MCP connection

1. **Check the entrypoint resolves.** Run `which ghostbrain-mcp`. If missing,
   the user hasn't `pip install`-ed the package into the active env — have them
   run `pip install -e ".[mcp]"` from the repo (or point the command at the
   venv that has it).

2. **Add the server to `.mcp.json`.** Ask the user: project scope
   (`./.mcp.json`, this repo only) or user scope (every project)? Then add:
   ```json
   { "mcpServers": { "poltergeist": { "command": "ghostbrain-mcp" } } }
   ```
   (Merge into existing `mcpServers` if the file already has entries.)

3. **Confirm the sidecar is running.** The MCP forwards to the desktop app's
   sidecar. Check `~/ghostbrain/run/sidecar.json` exists and its `pid` is alive.
   If not, tell the user to open the Poltergeist desktop app.

4. **Smoke-test.** After the MCP reconnects, call `poltergeist_search` with a
   throwaway query (e.g. "test"). A structured result or the clear
   "Poltergeist isn't running" message both confirm the wiring is correct.

## Using it during work

See `using.md` in this skill directory for when to reach for each tool and how
to fold recalled context into your work.
```

- [ ] **Step 2: Write `using.md`**

```markdown
# Using Poltergeist during work

The `poltergeist` MCP exposes three tools over the user's local vault.

## When to reach for it

Before starting non-trivial work in one of the user's known contexts, recall
what they already decided instead of asking them to re-explain:
- prior architectural decisions and *why* they were made
- past incidents / bugs and their root causes
- what the user already concluded about a topic

## Which tool

- **`poltergeist_ask`** — a real question needing a synthesized answer
  ("why did we move off the Anthropic API for LLM calls?"). Costs an LLM call
  (~5-15s). Returns an answer plus cited note paths.
- **`poltergeist_search`** → **`poltergeist_get_note`** — when you want the raw
  source material: search to locate notes cheaply, then read the most relevant
  one in full. Prefer this for exploration.

## Using results

- Cite the note path when you act on recalled context, so the user can trace it.
- Treat vault content as the user's ground truth — it's their own notes.

## What not to do

- Don't `ask` about things already in the current conversation.
- A "Poltergeist isn't running" error is never a reason to invent facts — tell
  the user to open the app, or proceed without the recall.
```

- [ ] **Step 3: Verify the skill files are well-formed**

Run: `head -3 .claude/skills/poltergeist-recall/SKILL.md`
Expected: shows the YAML frontmatter opening `---` and the `name:` line.

- [ ] **Step 4: Commit**

```bash
git add .claude/skills/poltergeist-recall/
git commit -m "feat(skill): poltergeist-recall — install + use the MCP"
```

---

## Task 9: README documentation

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add an MCP section**

In `README.md`, add a new section after the Quick start (find the line ending the
Quick start table; insert before the `## Why` section):

```markdown
## Query from Claude Code / Desktop (MCP)

Poltergeist ships an MCP server so Claude Code & Desktop can query your vault
mid-task — ask it questions, search it, read notes.

```bash
pip install -e ".[mcp]"     # adds the ghostbrain-mcp entrypoint
```

Add to your `.mcp.json` (project scope) or `~/.claude.json` (user scope):

```json
{ "mcpServers": { "poltergeist": { "command": "ghostbrain-mcp" } } }
```

The server forwards to the running desktop-app sidecar (it must be open). Tools:
`poltergeist_ask` (RAG answer + citations), `poltergeist_search` (ranked hits),
`poltergeist_get_note` (full note by path). The `poltergeist-recall` skill in
`.claude/skills/` automates the wiring and tells Claude when to use it.

> Writing notes from Claude (`poltergeist_capture`) is a planned follow-on once
> Poltergeist Jots lands.
```

- [ ] **Step 2: Verify it renders sanely**

Run: `grep -n "Query from Claude Code" README.md`
Expected: one match.

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(readme): MCP server setup section"
```

---

## Final verification

- [ ] **Run the full MCP test suite + lint**

Run: `pytest tests/test_mcp_*.py -v && ruff check ghostbrain/mcp ghostbrain/api/runtime.py`
Expected: all tests PASS, ruff reports no errors.

- [ ] **Manual smoke (optional, needs the desktop app running)**

1. Start the desktop app (or `GHOSTBRAIN_SCHEDULER_ENABLED=1 python -m ghostbrain.api`).
2. Confirm `~/ghostbrain/run/sidecar.json` appears.
3. Register the MCP in a scratch project's `.mcp.json` and run `claude` — confirm `poltergeist_search` returns hits.
```
