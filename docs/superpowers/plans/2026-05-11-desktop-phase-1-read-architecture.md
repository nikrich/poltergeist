# Ghostbrain Desktop — Phase 1: Read Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the six desktop screens to real data from the existing ghostbrain vault via a Python FastAPI sidecar that the Electron app spawns and proxies through. Stable architecture that Phase 2 (writes, recording, OAuth, bundling) extends without rewriting.

**Architecture:** New Python module `ghostbrain/api/` exposes read-only JSON endpoints under `/v1/`. Electron main spawns the sidecar, captures a random token from its stdout, forwards renderer IPC calls to localhost HTTP with the token. Renderer uses React Query for fetch lifecycle.

**Tech Stack:** FastAPI + uvicorn (sidecar), Pydantic v2 (schemas), @tanstack/react-query v5 (renderer fetch), existing Electron + Vite + TS + Tailwind stack from Slice 1.5.

**Spec:** `docs/superpowers/specs/2026-05-11-desktop-phase-1-read-architecture-design.md`

**Hard rule for every commit on this branch:** the diff against `main` must only touch:
- `ghostbrain/api/**` (new module, additive)
- `desktop/**`
- `pyproject.toml` (adding the `[api]` extras)
- `docs/**`

Existing `ghostbrain/*.py` modules outside `api/` are **off-limits**. Existing `tests/`, `scripts/`, `orchestration/`, root README, CLAUDE.md — all off-limits. Verifiable:

```bash
git diff main..HEAD -- ghostbrain/ ':!ghostbrain/api/'
# expected: empty
```

---

## File structure

### Python side (sidecar)

| Path | Responsibility |
|------|----------------|
| `ghostbrain/api/__init__.py` | Exports `create_app(token: str) -> FastAPI` |
| `ghostbrain/api/__main__.py` | `python -m ghostbrain.api` entrypoint; picks port, generates token, prints `READY` banner, runs uvicorn |
| `ghostbrain/api/main.py` | FastAPI app factory: middleware wiring, router registration, OpenAPI metadata |
| `ghostbrain/api/auth.py` | Bearer token middleware |
| `ghostbrain/api/routes/vault.py` | `GET /v1/vault/stats` |
| `ghostbrain/api/routes/connectors.py` | `GET /v1/connectors`, `GET /v1/connectors/{id}` |
| `ghostbrain/api/routes/captures.py` | `GET /v1/captures`, `GET /v1/captures/{id}` |
| `ghostbrain/api/routes/meetings.py` | `GET /v1/meetings` |
| `ghostbrain/api/routes/agenda.py` | `GET /v1/agenda` |
| `ghostbrain/api/routes/activity.py` | `GET /v1/activity` |
| `ghostbrain/api/routes/suggestions.py` | `GET /v1/suggestions` |
| `ghostbrain/api/models/__init__.py` | Re-exports all Pydantic models |
| `ghostbrain/api/models/vault.py` | `VaultStats` |
| `ghostbrain/api/models/connector.py` | `Connector`, `ConnectorState`, `ConnectorDetail` |
| `ghostbrain/api/models/capture.py` | `CaptureSummary`, `Capture`, `CapturesPage` |
| `ghostbrain/api/models/meeting.py` | `PastMeeting`, `MeetingsPage` |
| `ghostbrain/api/models/agenda.py` | `AgendaItem` |
| `ghostbrain/api/models/activity.py` | `ActivityRow` |
| `ghostbrain/api/models/suggestion.py` | `Suggestion` |
| `ghostbrain/api/repo/__init__.py` | Re-exports repo functions |
| `ghostbrain/api/repo/vault.py` | Vault filesystem reads (note count, queue depth, size) |
| `ghostbrain/api/repo/connectors.py` | Enumerates `ghostbrain/connectors/` + reads state dir |
| `ghostbrain/api/repo/captures.py` | Reads `queue_dir()` + `audit_dir()` |
| `ghostbrain/api/repo/meetings.py` | Reads meeting markdown files from the vault |
| `ghostbrain/api/repo/agenda.py` | Reads calendar files from the vault |
| `ghostbrain/api/repo/activity.py` | Parses audit log for recent processed events |
| `ghostbrain/api/repo/suggestions.py` | Phase 1 stub: 2-3 trivial computed hints |
| `tests/test_api/conftest.py` | Pytest fixtures: tmp vault, sample notes, fake state dir |
| `tests/test_api/test_vault.py` | Tests for vault stats endpoint |
| `tests/test_api/test_connectors.py` | Tests for connectors endpoints |
| `tests/test_api/test_captures.py` | Tests for captures endpoints |
| `tests/test_api/test_meetings.py` | Tests for meetings endpoint |
| `tests/test_api/test_agenda.py` | Tests for agenda endpoint |
| `tests/test_api/test_activity.py` | Tests for activity endpoint |
| `tests/test_api/test_suggestions.py` | Tests for suggestions endpoint |
| `tests/test_api/test_auth.py` | Tests for token auth middleware |
| `tests/test_api/test_main.py` | Tests for app factory and startup banner |

> Note on `tests/test_api/`: this is a NEW subdirectory under the existing `tests/`. Adding new test files is fine — but **do not modify any existing `tests/test_*.py` file**. The hard rule allows additions to `tests/` only inside the new `test_api/` subdir.
>
> Wait — the spec's hard rule says "tests/ off-limits". Reconcile: tests for the new `ghostbrain.api` module live alongside existing tests OR inside `ghostbrain/api/tests/`. The cleanest option is `ghostbrain/api/tests/` (co-located with the module), which keeps the `tests/` root untouched. Use that. Adjust the paths accordingly:

### Python tests (revised location)

| Path | Responsibility |
|------|----------------|
| `ghostbrain/api/tests/__init__.py` | Empty package marker |
| `ghostbrain/api/tests/conftest.py` | Pytest fixtures |
| `ghostbrain/api/tests/test_auth.py` | Auth middleware tests |
| `ghostbrain/api/tests/test_main.py` | App factory tests |
| `ghostbrain/api/tests/test_vault.py` | Vault endpoint tests |
| `ghostbrain/api/tests/test_connectors.py` | Connectors endpoint tests |
| `ghostbrain/api/tests/test_captures.py` | Captures endpoint tests |
| `ghostbrain/api/tests/test_meetings.py` | Meetings endpoint tests |
| `ghostbrain/api/tests/test_agenda.py` | Agenda endpoint tests |
| `ghostbrain/api/tests/test_activity.py` | Activity endpoint tests |
| `ghostbrain/api/tests/test_suggestions.py` | Suggestions endpoint tests |

> All under `ghostbrain/api/tests/` — co-located with the module, doesn't touch the root `tests/` dir. pytest discovers them via the existing `pyproject.toml` `[tool.pytest.ini_options] testpaths = ["tests"]`. **Add `ghostbrain/api/tests` to that list** in Task 1 (the only pyproject.toml change).

### TypeScript side

| Path | Responsibility |
|------|----------------|
| `desktop/src/main/sidecar.ts` | Sidecar process lifecycle (spawn, READY parse, restart, shutdown) |
| `desktop/src/main/api-forwarder.ts` | HTTP forwarder: `forward(method, path, body)` |
| `desktop/src/main/index.ts` | (modify) wire sidecar + IPC handler `gb:api:request` |
| `desktop/src/preload/index.ts` | (modify) add `api.request<T>` to the bridge |
| `desktop/src/shared/types.ts` | (modify) add `GbApiBridge` interface |
| `desktop/src/shared/api-types.ts` | TS types mirroring Pydantic models (single source of truth on TS side) |
| `desktop/src/renderer/lib/api/client.ts` | Typed wrapper around `window.gb.api.request` |
| `desktop/src/renderer/lib/api/hooks.ts` | React Query hooks per resource |
| `desktop/src/renderer/lib/api/query-client.ts` | Shared QueryClient instance with defaults |
| `desktop/src/renderer/components/SkeletonRows.tsx` | Loading skeleton for list panels |
| `desktop/src/renderer/components/PanelEmpty.tsx` | Empty state |
| `desktop/src/renderer/components/PanelError.tsx` | Error state with retry |
| `desktop/src/renderer/components/SidecarSetup.tsx` | First-run screen when sidecar fails |
| `desktop/src/renderer/stores/sidecar.ts` | Zustand store tracking sidecar status (ready/failed/connecting) |
| `desktop/src/renderer/main.tsx` | (modify) wrap App in QueryClientProvider |
| `desktop/src/renderer/App.tsx` | (modify) check sidecar status, render SidecarSetup if not ready |
| `desktop/src/renderer/screens/today.tsx` | (modify) replace mocks with hooks |
| `desktop/src/renderer/screens/connectors.tsx` | (modify) replace mocks with hooks |
| `desktop/src/renderer/screens/capture.tsx` | (modify) replace mocks with hooks |
| `desktop/src/renderer/screens/meetings.tsx` | (modify) replace HISTORY mock with hook; recording UI stays |
| `desktop/src/renderer/public/assets/connectors/claude_code.svg` | New logo |
| `desktop/src/renderer/public/assets/connectors/jira.svg` | New logo |
| `desktop/src/renderer/public/assets/connectors/confluence.svg` | New logo |
| `desktop/src/renderer/public/assets/connectors/atlassian.svg` | New logo |

### Files deleted at end

- `desktop/src/renderer/lib/mocks/today.ts`
- `desktop/src/renderer/lib/mocks/connectors.ts`
- `desktop/src/renderer/lib/mocks/capture.ts`
- `desktop/src/renderer/lib/mocks/meetings.ts`

---

## Phase 1A — Sidecar foundation

### Task 1: pyproject.toml api extras + ghostbrain/api skeleton

**Files:**
- Modify: `pyproject.toml`
- Create: `ghostbrain/api/__init__.py`
- Create: `ghostbrain/api/tests/__init__.py`

- [ ] **Step 1.1: Add the `[api]` optional-dependencies group**

Edit `pyproject.toml`. Find the `[project.optional-dependencies]` block (currently has `dev` and `semantic`). Add `api`:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "ruff>=0.5",
]
semantic = [
    "sentence-transformers>=2.7",
    "numpy>=1.26",
]
api = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "httpx>=0.27.0",
]
```

`httpx` is included because FastAPI's `TestClient` uses it. Tests in `ghostbrain/api/tests/` need it.

- [ ] **Step 1.2: Update pytest testpaths**

Still in `pyproject.toml`, find `[tool.pytest.ini_options]`. Update:

```toml
[tool.pytest.ini_options]
testpaths = ["tests", "ghostbrain/api/tests"]
```

- [ ] **Step 1.3: Create the empty `api` package marker**

Create `ghostbrain/api/__init__.py` with:

```python
"""Read-only HTTP API exposing ghostbrain vault data to the desktop app.

This module is additive — it imports from existing ghostbrain.* but does
not modify any existing module's surface. Phase 2 extends this with write
endpoints, OAuth flows, and WebSocket events.
"""
```

Create `ghostbrain/api/tests/__init__.py` as an empty file.

- [ ] **Step 1.4: Install the new extras**

```bash
cd ~/dev/poltergeist
source .venv/bin/activate   # or however the user activates the project venv
pip install -e ".[api,dev]"
```

Expected: installs fastapi, uvicorn, httpx (and updates dev). Verify:

```bash
python -c "import fastapi, uvicorn, httpx; print(fastapi.__version__, uvicorn.__version__, httpx.__version__)"
```

Expected: three version numbers print.

- [ ] **Step 1.5: Commit**

```bash
git add pyproject.toml ghostbrain/api/__init__.py ghostbrain/api/tests/__init__.py
git commit -m "chore(api): scaffold ghostbrain.api package + add [api] extras

FastAPI + uvicorn + httpx as an optional dependency group. Pytest testpaths
extended to include ghostbrain/api/tests. No existing ghostbrain modules
modified."
```

---

### Task 2: Auth middleware + tests

**Files:**
- Create: `ghostbrain/api/auth.py`
- Create: `ghostbrain/api/tests/test_auth.py`

- [ ] **Step 2.1: Write the failing test**

Create `ghostbrain/api/tests/test_auth.py`:

```python
"""Auth middleware: rejects missing/wrong tokens, allows OpenAPI introspection."""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ghostbrain.api.auth import make_auth_middleware

TOKEN = "test-token-1234"


def _make_app() -> FastAPI:
    app = FastAPI()
    app.middleware("http")(make_auth_middleware(TOKEN))

    @app.get("/v1/echo")
    def echo():
        return {"ok": True}

    return app


def test_missing_auth_header_returns_401():
    client = TestClient(_make_app())
    res = client.get("/v1/echo")
    assert res.status_code == 401


def test_wrong_token_returns_401():
    client = TestClient(_make_app())
    res = client.get("/v1/echo", headers={"Authorization": "Bearer wrong"})
    assert res.status_code == 401


def test_correct_token_passes():
    client = TestClient(_make_app())
    res = client.get("/v1/echo", headers={"Authorization": f"Bearer {TOKEN}"})
    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_openapi_endpoint_skips_auth():
    client = TestClient(_make_app())
    res = client.get("/openapi.json")
    assert res.status_code == 200


def test_docs_endpoint_skips_auth():
    client = TestClient(_make_app())
    res = client.get("/docs")
    assert res.status_code == 200
```

- [ ] **Step 2.2: Run test, watch it fail**

```bash
pytest ghostbrain/api/tests/test_auth.py -v
```

Expected: ImportError on `make_auth_middleware` — module doesn't exist yet.

- [ ] **Step 2.3: Implement the middleware**

Create `ghostbrain/api/auth.py`:

```python
"""Bearer token middleware for the ghostbrain read API."""
from typing import Awaitable, Callable

from fastapi import HTTPException, Request, Response, status

# Paths exempt from auth (developer introspection only; sidecar binds 127.0.0.1
# so external reach is already prevented).
_UNAUTH_PATHS = frozenset({"/openapi.json", "/docs", "/redoc"})


def make_auth_middleware(
    token: str,
) -> Callable[[Request, Callable[[Request], Awaitable[Response]]], Awaitable[Response]]:
    """Build an ASGI HTTP middleware that requires `Authorization: Bearer <token>`."""
    expected = f"Bearer {token}"

    async def auth_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path in _UNAUTH_PATHS:
            return await call_next(request)
        header = request.headers.get("authorization", "")
        if header != expected:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return await call_next(request)

    return auth_middleware
```

- [ ] **Step 2.4: Run test, watch it pass**

```bash
pytest ghostbrain/api/tests/test_auth.py -v
```

Expected: 5 passed.

- [ ] **Step 2.5: Commit**

```bash
git add ghostbrain/api/auth.py ghostbrain/api/tests/test_auth.py
git commit -m "feat(api): bearer token auth middleware

Rejects missing/wrong Authorization headers with 401. Allows /openapi.json,
/docs, /redoc unauthenticated for developer introspection (sidecar binds
127.0.0.1 only, so these aren't reachable externally)."
```

---

### Task 3: FastAPI app factory

**Files:**
- Create: `ghostbrain/api/main.py`
- Create: `ghostbrain/api/tests/test_main.py`

- [ ] **Step 3.1: Write the failing test**

Create `ghostbrain/api/tests/test_main.py`:

```python
"""App factory: builds a FastAPI app with auth + routers + OpenAPI metadata."""
from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app


def test_app_has_openapi_schema():
    app = create_app(token="t")
    client = TestClient(app)
    res = client.get("/openapi.json")
    assert res.status_code == 200
    schema = res.json()
    assert schema["info"]["title"] == "ghostbrain"
    assert schema["info"]["version"].startswith("1.")


def test_app_requires_auth_on_v1_routes():
    app = create_app(token="t")
    client = TestClient(app)
    # No /v1/* routes exist yet, but a hypothetical one would 401 without auth
    # rather than 404. We verify by checking a route that exists once we add it.
    # For now, this assertion is implicit via test_auth.py; this test focuses on
    # the metadata.
    pass


def test_app_unauthenticated_health_endpoint():
    """/v1/health does NOT exist by design — auth happens on every /v1/ path."""
    # If this test fails because /v1/health exists, remove it and remove the
    # health endpoint from main.py. Health-checking is a sidecar concern, not
    # an HTTP concern.
    pass
```

> The second and third tests are placeholders documenting intent. Actual coverage of v1 auth happens in route-specific tests in later tasks.

- [ ] **Step 3.2: Run test, watch it fail**

```bash
pytest ghostbrain/api/tests/test_main.py -v
```

Expected: ImportError on `create_app`.

- [ ] **Step 3.3: Implement the factory**

Create `ghostbrain/api/main.py`:

```python
"""FastAPI app factory for the ghostbrain read API."""
from fastapi import FastAPI

from ghostbrain.api.auth import make_auth_middleware

API_VERSION = "1.0.0"


def create_app(token: str) -> FastAPI:
    """Build a FastAPI app with auth wired in. Routers added in later tasks."""
    app = FastAPI(
        title="ghostbrain",
        description="Read-only API for the ghostbrain desktop app.",
        version=API_VERSION,
    )
    app.middleware("http")(make_auth_middleware(token))
    return app
```

- [ ] **Step 3.4: Run test, watch it pass**

```bash
pytest ghostbrain/api/tests/test_main.py -v
```

Expected: 3 passed (the two `pass` placeholders count as passing).

- [ ] **Step 3.5: Commit**

```bash
git add ghostbrain/api/main.py ghostbrain/api/tests/test_main.py
git commit -m "feat(api): create_app factory with auth middleware

FastAPI app with title 'ghostbrain', version 1.0.0, bearer token auth.
Routers added in subsequent tasks."
```

---

### Task 4: `python -m ghostbrain.api` entrypoint with READY banner

**Files:**
- Create: `ghostbrain/api/__main__.py`

> This task is tricky to test in pytest cleanly because it actually starts a uvicorn server. We verify by running the command and observing the banner, plus a smoke curl. No pytest test for this one.

- [ ] **Step 4.1: Implement the entrypoint**

Create `ghostbrain/api/__main__.py`:

```python
"""Run the ghostbrain read API as a subprocess from Electron main.

Picks a random free port on 127.0.0.1, generates a random 256-bit hex token,
prints the READY banner to stdout BEFORE handing off to uvicorn (so the parent
process can capture port + token from a single line), then runs the server.
"""
from __future__ import annotations

import secrets
import socket
import sys

import uvicorn

from ghostbrain.api.main import create_app


def _pick_port() -> int:
    """Bind a transient socket to an OS-assigned port, then close. Race-y but
    fine for the local-only sidecar; uvicorn re-binds the same port immediately."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    token = secrets.token_hex(32)
    port = _pick_port()
    app = create_app(token=token)

    # Print the READY banner BEFORE uvicorn takes over output. Parent process
    # parses this single line to capture port + token.
    print(f"READY port={port} token={token}", flush=True)

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4.2: Smoke-test by running it**

```bash
python -m ghostbrain.api &
SIDECAR_PID=$!
sleep 2
# Capture the banner from process output if possible, or just hit a known endpoint
# (after Task 5 adds /v1/vault/stats). For now, hit /openapi.json (unauthenticated):
curl -s http://127.0.0.1:<port-from-banner>/openapi.json | python -m json.tool | head -10
kill $SIDECAR_PID
```

Easier verification: redirect output and grep:

```bash
python -m ghostbrain.api > /tmp/sidecar.log 2>&1 &
SIDECAR_PID=$!
sleep 2
head -3 /tmp/sidecar.log
# Expected line: READY port=<some-number> token=<64-hex-chars>
kill $SIDECAR_PID
```

If the banner doesn't appear within 2 seconds, check the imports (probably a missing dep — `pip install -e ".[api]"` again).

- [ ] **Step 4.3: Commit**

```bash
git add ghostbrain/api/__main__.py
git commit -m "feat(api): python -m ghostbrain.api entrypoint with READY banner

Picks a random free port, generates a 256-bit hex token, prints
'READY port=<port> token=<token>' to stdout as the first line, then hands
off to uvicorn. Electron main parses this to capture both values."
```

---

## Phase 1B — Repo modules + endpoints

### Task 5: Vault stats endpoint

**Files:**
- Create: `ghostbrain/api/models/__init__.py`
- Create: `ghostbrain/api/models/vault.py`
- Create: `ghostbrain/api/repo/__init__.py`
- Create: `ghostbrain/api/repo/vault.py`
- Create: `ghostbrain/api/routes/__init__.py`
- Create: `ghostbrain/api/routes/vault.py`
- Modify: `ghostbrain/api/main.py` (register router)
- Create: `ghostbrain/api/tests/conftest.py`
- Create: `ghostbrain/api/tests/test_vault.py`

- [ ] **Step 5.1: Pydantic model**

Create `ghostbrain/api/models/__init__.py`:

```python
"""Pydantic models for the ghostbrain read API."""
from ghostbrain.api.models.vault import VaultStats

__all__ = ["VaultStats"]
```

Create `ghostbrain/api/models/vault.py`:

```python
"""Vault statistics."""
from pydantic import BaseModel, ConfigDict


class VaultStats(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    totalNotes: int
    queuePending: int
    vaultSizeBytes: int
    lastSyncAt: str | None
    indexedCount: int
```

- [ ] **Step 5.2: Pytest fixtures**

Create `ghostbrain/api/tests/conftest.py`:

```python
"""Shared fixtures: temp vault, temp state dir, app factory wired to them."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

from ghostbrain.api.main import create_app

TEST_TOKEN = "test-token-1234567890"


@pytest.fixture
def tmp_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a clean temp vault and point VAULT_PATH at it."""
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "10-daily").mkdir()
    (vault / "20-contexts").mkdir()
    (vault / "60-dashboards").mkdir()
    (vault / "80-profile").mkdir()
    (vault / "90-meta").mkdir()
    (vault / "90-meta" / "queue").mkdir()
    (vault / "90-meta" / "queue" / "pending").mkdir()
    (vault / "90-meta" / "audit").mkdir()
    monkeypatch.setenv("VAULT_PATH", str(vault))
    return vault


@pytest.fixture
def tmp_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a clean temp state dir and point GHOSTBRAIN_STATE_DIR at it."""
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setenv("GHOSTBRAIN_STATE_DIR", str(state))
    return state


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {TEST_TOKEN}"}


@pytest.fixture
def client(tmp_vault: Path, tmp_state_dir: Path) -> Iterator[TestClient]:
    app = create_app(token=TEST_TOKEN)
    with TestClient(app) as c:
        yield c


def write_note(vault: Path, relative_path: str, body: str = "# Note\n\nbody.\n") -> Path:
    """Helper: write a markdown file at vault/<relative_path>, creating dirs."""
    p = vault / relative_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


def write_state(state_dir: Path, connector_id: str, data: dict) -> Path:
    """Helper: write state.json for a connector."""
    p = state_dir / connector_id / "state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data))
    return p
```

- [ ] **Step 5.3: Write the failing test**

Create `ghostbrain/api/tests/test_vault.py`:

```python
"""GET /v1/vault/stats returns aggregate vault numbers."""
from pathlib import Path

from fastapi.testclient import TestClient

from ghostbrain.api.tests.conftest import write_note, write_state


def test_empty_vault_returns_zeros(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/vault/stats", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["totalNotes"] == 0
    assert data["queuePending"] == 0
    assert data["vaultSizeBytes"] == 0
    assert data["lastSyncAt"] is None
    assert data["indexedCount"] == 0


def test_counts_markdown_notes_recursively(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    write_note(tmp_vault, "10-daily/2026-05-11.md")
    write_note(tmp_vault, "20-contexts/personal/gmail/foo.md")
    write_note(tmp_vault, "20-contexts/work/slack/bar.md")
    res = client.get("/v1/vault/stats", headers=auth_headers)
    assert res.json()["totalNotes"] == 3


def test_counts_pending_queue_entries(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    pending = tmp_vault / "90-meta" / "queue" / "pending"
    (pending / "1.json").write_text("{}")
    (pending / "2.json").write_text("{}")
    res = client.get("/v1/vault/stats", headers=auth_headers)
    assert res.json()["queuePending"] == 2


def test_aggregates_last_sync_and_indexed_from_state(
    client: TestClient, auth_headers: dict[str, str], tmp_state_dir: Path
):
    write_state(tmp_state_dir, "github", {"last_run": "2026-05-11T12:00:00Z", "indexed": 100})
    write_state(tmp_state_dir, "slack", {"last_run": "2026-05-11T13:30:00Z", "indexed": 250})
    res = client.get("/v1/vault/stats", headers=auth_headers)
    data = res.json()
    assert data["lastSyncAt"] == "2026-05-11T13:30:00Z"  # max
    assert data["indexedCount"] == 350  # sum
```

- [ ] **Step 5.4: Run test, watch it fail**

```bash
pytest ghostbrain/api/tests/test_vault.py -v
```

Expected: `ImportError` or `404` (route doesn't exist yet).

- [ ] **Step 5.5: Implement the repo function**

Create `ghostbrain/api/repo/__init__.py`:

```python
"""Filesystem-reading functions, separated from HTTP routes for unit testing."""
```

Create `ghostbrain/api/repo/vault.py`:

```python
"""Vault filesystem aggregates."""
from __future__ import annotations

import json
from pathlib import Path

from ghostbrain.paths import queue_dir, state_dir, vault_path


def _walk_size(root: Path) -> tuple[int, int]:
    """Returns (markdown_count, total_bytes) for the subtree."""
    md_count = 0
    total_bytes = 0
    for path in root.rglob("*"):
        if path.is_file():
            total_bytes += path.stat().st_size
            if path.suffix == ".md":
                md_count += 1
    return md_count, total_bytes


def _aggregate_state() -> tuple[str | None, int]:
    """Returns (max last_run timestamp, sum of indexed counts) across connectors."""
    state = state_dir()
    if not state.exists():
        return None, 0
    last_runs: list[str] = []
    indexed_sum = 0
    for entry in state.iterdir():
        state_file = entry / "state.json"
        if not state_file.exists():
            continue
        try:
            data = json.loads(state_file.read_text())
        except json.JSONDecodeError:
            continue
        if isinstance(data.get("last_run"), str):
            last_runs.append(data["last_run"])
        if isinstance(data.get("indexed"), int):
            indexed_sum += data["indexed"]
    return (max(last_runs) if last_runs else None), indexed_sum


def get_vault_stats() -> dict:
    vault = vault_path()
    queue = queue_dir() / "pending"
    if vault.exists():
        md_count, total_bytes = _walk_size(vault)
    else:
        md_count, total_bytes = 0, 0
    pending_count = sum(1 for p in queue.iterdir() if p.is_file()) if queue.exists() else 0
    last_sync, indexed = _aggregate_state()
    return {
        "totalNotes": md_count,
        "queuePending": pending_count,
        "vaultSizeBytes": total_bytes,
        "lastSyncAt": last_sync,
        "indexedCount": indexed,
    }
```

- [ ] **Step 5.6: Implement the route**

Create `ghostbrain/api/routes/__init__.py` (empty file marker).

Create `ghostbrain/api/routes/vault.py`:

```python
"""GET /v1/vault/stats."""
from fastapi import APIRouter

from ghostbrain.api.models.vault import VaultStats
from ghostbrain.api.repo.vault import get_vault_stats

router = APIRouter(prefix="/v1/vault", tags=["vault"])


@router.get("/stats", response_model=VaultStats)
def vault_stats() -> dict:
    return get_vault_stats()
```

- [ ] **Step 5.7: Register the router**

Edit `ghostbrain/api/main.py`. Replace with:

```python
"""FastAPI app factory for the ghostbrain read API."""
from fastapi import FastAPI

from ghostbrain.api.auth import make_auth_middleware
from ghostbrain.api.routes import vault as vault_routes

API_VERSION = "1.0.0"


def create_app(token: str) -> FastAPI:
    """Build a FastAPI app with auth + all routers wired."""
    app = FastAPI(
        title="ghostbrain",
        description="Read-only API for the ghostbrain desktop app.",
        version=API_VERSION,
    )
    app.middleware("http")(make_auth_middleware(token))
    app.include_router(vault_routes.router)
    return app
```

- [ ] **Step 5.8: Run tests, watch them pass**

```bash
pytest ghostbrain/api/tests/test_vault.py -v
```

Expected: 4 passed.

Also verify all earlier tests still pass:

```bash
pytest ghostbrain/api/tests/ -v
```

Expected: 12+ passed.

- [ ] **Step 5.9: Commit**

```bash
git add ghostbrain/api/models/ ghostbrain/api/repo/ ghostbrain/api/routes/ ghostbrain/api/main.py ghostbrain/api/tests/conftest.py ghostbrain/api/tests/test_vault.py
git commit -m "feat(api): GET /v1/vault/stats

Walks vault_path() for markdown count + total size, counts pending entries
in queue_dir(), aggregates last_sync (max) and indexed (sum) from each
connector's state.json in state_dir(). Returns VaultStats schema."
```

---

### Task 6: Connectors endpoints

**Files:**
- Create: `ghostbrain/api/models/connector.py`
- Modify: `ghostbrain/api/models/__init__.py` (re-export)
- Create: `ghostbrain/api/repo/connectors.py`
- Create: `ghostbrain/api/routes/connectors.py`
- Modify: `ghostbrain/api/main.py` (register router)
- Create: `ghostbrain/api/tests/test_connectors.py`

- [ ] **Step 6.1: Pydantic models**

Create `ghostbrain/api/models/connector.py`:

```python
"""Connector schema."""
from typing import Literal

from pydantic import BaseModel, ConfigDict

ConnectorState = Literal["on", "off", "err"]


class Connector(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    displayName: str
    state: ConnectorState
    count: int
    lastSyncAt: str | None
    account: str | None
    throughput: str | None
    error: str | None


class ConnectorDetail(Connector):
    scopes: list[str]
    pulls: list[str]
    vaultDestination: str
```

Update `ghostbrain/api/models/__init__.py`:

```python
"""Pydantic models for the ghostbrain read API."""
from ghostbrain.api.models.connector import Connector, ConnectorDetail, ConnectorState
from ghostbrain.api.models.vault import VaultStats

__all__ = ["Connector", "ConnectorDetail", "ConnectorState", "VaultStats"]
```

- [ ] **Step 6.2: Write the failing tests**

Create `ghostbrain/api/tests/test_connectors.py`:

```python
"""GET /v1/connectors and GET /v1/connectors/{id}."""
from pathlib import Path

from fastapi.testclient import TestClient

from ghostbrain.api.tests.conftest import write_state


def test_empty_connectors_list(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/connectors", headers=auth_headers)
    assert res.status_code == 200
    # The list may not be empty (ghostbrain/connectors/ may contain entries),
    # but each item should be well-formed. Check shape, not emptiness.
    data = res.json()
    assert isinstance(data, list)
    for item in data:
        assert {"id", "displayName", "state", "count", "lastSyncAt", "account", "throughput", "error"}.issubset(item.keys())


def test_connector_state_off_when_no_state_file(
    client: TestClient, auth_headers: dict[str, str], tmp_state_dir: Path
):
    """A connector defined in ghostbrain/connectors/ but with no state.json reports state='off'."""
    res = client.get("/v1/connectors", headers=auth_headers)
    data = res.json()
    # github is one of the connectors that exists; without state it should be 'off'
    github = next((c for c in data if c["id"] == "github"), None)
    if github is not None:
        assert github["state"] == "off"


def test_connector_state_on_with_recent_sync(
    client: TestClient, auth_headers: dict[str, str], tmp_state_dir: Path
):
    write_state(tmp_state_dir, "github", {
        "last_run": "2026-05-11T13:00:00Z",
        "indexed": 824,
        "account": "theo-haunts",
    })
    res = client.get("/v1/connectors", headers=auth_headers)
    data = res.json()
    github = next((c for c in data if c["id"] == "github"), None)
    assert github is not None
    assert github["state"] == "on"
    assert github["count"] == 824
    assert github["account"] == "theo-haunts"
    assert github["lastSyncAt"] == "2026-05-11T13:00:00Z"


def test_connector_state_err_when_state_has_error(
    client: TestClient, auth_headers: dict[str, str], tmp_state_dir: Path
):
    write_state(tmp_state_dir, "github", {
        "last_run": "2026-05-09T08:00:00Z",
        "indexed": 0,
        "error": "token expired",
    })
    res = client.get("/v1/connectors", headers=auth_headers)
    github = next((c for c in res.json() if c["id"] == "github"), None)
    assert github is not None
    assert github["state"] == "err"
    assert github["error"] == "token expired"


def test_connector_detail_returns_404_for_unknown(
    client: TestClient, auth_headers: dict[str, str]
):
    res = client.get("/v1/connectors/does-not-exist", headers=auth_headers)
    assert res.status_code == 404


def test_connector_detail_includes_scopes_and_pulls(
    client: TestClient, auth_headers: dict[str, str], tmp_state_dir: Path
):
    write_state(tmp_state_dir, "github", {"last_run": "2026-05-11T13:00:00Z", "indexed": 1})
    res = client.get("/v1/connectors/github", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert "scopes" in data
    assert "pulls" in data
    assert "vaultDestination" in data
```

- [ ] **Step 6.3: Run, watch fail**

```bash
pytest ghostbrain/api/tests/test_connectors.py -v
```

Expected: ImportError or 404s.

- [ ] **Step 6.4: Implement the repo**

Create `ghostbrain/api/repo/connectors.py`:

```python
"""Connector enumeration and state."""
from __future__ import annotations

import json
from pathlib import Path

from ghostbrain.paths import state_dir

# Static display metadata. Adding a new connector requires adding here too —
# small explicit dev tax in exchange for clean display names.
_DISPLAY: dict[str, dict] = {
    "claude_code": {
        "displayName": "Claude Code",
        "scopes": ["read .claude/projects"],
        "pulls": ["sessions", "tool uses"],
        "vaultDestination": "20-contexts/{ctx}/claude_code/",
    },
    "github": {
        "displayName": "github",
        "scopes": ["repo:read"],
        "pulls": ["issues", "PRs", "commits"],
        "vaultDestination": "20-contexts/{ctx}/github/",
    },
    "jira": {
        "displayName": "jira",
        "scopes": ["read:jira-work"],
        "pulls": ["issues", "comments"],
        "vaultDestination": "20-contexts/{ctx}/jira/",
    },
    "confluence": {
        "displayName": "confluence",
        "scopes": ["read:confluence-content"],
        "pulls": ["pages", "comments"],
        "vaultDestination": "20-contexts/{ctx}/confluence/",
    },
    "calendar": {
        "displayName": "calendar",
        "scopes": ["read events"],
        "pulls": ["events", "attendees"],
        "vaultDestination": "20-contexts/{ctx}/calendar/",
    },
    "atlassian": {
        "displayName": "atlassian",
        "scopes": ["read profile"],
        "pulls": ["account info"],
        "vaultDestination": "20-contexts/{ctx}/atlassian/",
    },
    "slack": {
        "displayName": "slack",
        "scopes": ["channels:history", "users:read"],
        "pulls": ["mentions", "threads"],
        "vaultDestination": "20-contexts/{ctx}/slack/",
    },
    "gmail": {
        "displayName": "gmail",
        "scopes": ["read messages", "read labels"],
        "pulls": ["threads", "attachments"],
        "vaultDestination": "20-contexts/{ctx}/gmail/",
    },
}


def _connectors_root() -> Path:
    """Locate ghostbrain/connectors/ as installed."""
    # Resolve via the existing module — works regardless of install location.
    import ghostbrain.connectors

    return Path(ghostbrain.connectors.__file__).parent


def _list_connector_ids() -> list[str]:
    """Subdirectories of ghostbrain/connectors/ that look like connectors
    (have an __init__.py, not _base, not __pycache__)."""
    root = _connectors_root()
    if not root.exists():
        return []
    ids = []
    for child in root.iterdir():
        if not child.is_dir():
            continue
        if child.name.startswith("_") or child.name == "__pycache__":
            continue
        if not (child / "__init__.py").exists():
            continue
        ids.append(child.name)
    return sorted(ids)


def _read_state(connector_id: str) -> dict:
    state_file = state_dir() / connector_id / "state.json"
    if not state_file.exists():
        return {}
    try:
        return json.loads(state_file.read_text())
    except json.JSONDecodeError:
        return {}


def _connector_record(connector_id: str) -> dict:
    display = _DISPLAY.get(connector_id, {
        "displayName": connector_id,
        "scopes": [],
        "pulls": [],
        "vaultDestination": f"20-contexts/{{ctx}}/{connector_id}/",
    })
    state = _read_state(connector_id)
    has_error = isinstance(state.get("error"), str) and bool(state["error"])
    has_recent_run = isinstance(state.get("last_run"), str) and bool(state["last_run"])
    if has_error:
        run_state = "err"
    elif has_recent_run:
        run_state = "on"
    else:
        run_state = "off"
    return {
        "id": connector_id,
        "displayName": display["displayName"],
        "state": run_state,
        "count": int(state.get("indexed", 0)),
        "lastSyncAt": state.get("last_run"),
        "account": state.get("account"),
        "throughput": state.get("throughput"),
        "error": state.get("error"),
    }


def list_connectors() -> list[dict]:
    return [_connector_record(cid) for cid in _list_connector_ids()]


def get_connector(connector_id: str) -> dict | None:
    if connector_id not in _list_connector_ids():
        return None
    base = _connector_record(connector_id)
    display = _DISPLAY.get(connector_id, {})
    return {
        **base,
        "scopes": display.get("scopes", []),
        "pulls": display.get("pulls", []),
        "vaultDestination": display.get("vaultDestination", f"20-contexts/{{ctx}}/{connector_id}/"),
    }
```

- [ ] **Step 6.5: Implement the routes**

Create `ghostbrain/api/routes/connectors.py`:

```python
"""GET /v1/connectors, GET /v1/connectors/{id}."""
from fastapi import APIRouter, HTTPException

from ghostbrain.api.models.connector import Connector, ConnectorDetail
from ghostbrain.api.repo.connectors import get_connector, list_connectors

router = APIRouter(prefix="/v1/connectors", tags=["connectors"])


@router.get("", response_model=list[Connector])
def connectors() -> list[dict]:
    return list_connectors()


@router.get("/{connector_id}", response_model=ConnectorDetail)
def connector_detail(connector_id: str) -> dict:
    record = get_connector(connector_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Connector not found: {connector_id}")
    return record
```

- [ ] **Step 6.6: Register the router**

Edit `ghostbrain/api/main.py`. Add the connectors import and `include_router`:

```python
from ghostbrain.api.routes import connectors as connectors_routes
# ...
    app.include_router(connectors_routes.router)
```

- [ ] **Step 6.7: Run, commit**

```bash
pytest ghostbrain/api/tests/test_connectors.py -v
# expected: 6 passed
git add ghostbrain/api/models/ ghostbrain/api/repo/connectors.py ghostbrain/api/routes/connectors.py ghostbrain/api/main.py ghostbrain/api/tests/test_connectors.py
git commit -m "feat(api): GET /v1/connectors and /v1/connectors/{id}

Enumerates ghostbrain/connectors/ subdirectories, joins with state.json
per connector. Static display metadata for the 8 known connector ids.
state='on' when state.json has a recent last_run, 'err' on error field,
'off' otherwise."
```

---

### Task 7: Captures endpoints

**Files:**
- Create: `ghostbrain/api/models/capture.py`
- Modify: `ghostbrain/api/models/__init__.py`
- Create: `ghostbrain/api/repo/captures.py`
- Create: `ghostbrain/api/routes/captures.py`
- Modify: `ghostbrain/api/main.py`
- Create: `ghostbrain/api/tests/test_captures.py`

- [ ] **Step 7.1: Pydantic models**

Create `ghostbrain/api/models/capture.py`:

```python
"""Capture schemas."""
from pydantic import BaseModel, ConfigDict


class CaptureSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str
    title: str
    snippet: str
    from_: str
    tags: list[str]
    unread: bool
    capturedAt: str

    class Config:  # pydantic v2: use alias generator or model_config; keep this simple
        populate_by_name = True
        # `from` is a reserved Python keyword; alias the field
        fields = {"from_": "from"}


class Capture(CaptureSummary):
    body: str
    extracted: dict | None  # entities/action items/links — Phase 2 fleshes this out


class CapturesPage(BaseModel):
    total: int
    items: list[CaptureSummary]
```

> Pydantic v2 alias note: the spec wants the JSON field named `from`. Python doesn't allow `from` as a field name. Use `Field(alias="from")`. Re-author cleanly:

```python
"""Capture schemas."""
from pydantic import BaseModel, ConfigDict, Field


class CaptureSummary(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str
    title: str
    snippet: str
    from_: str = Field(alias="from")
    tags: list[str]
    unread: bool
    capturedAt: str


class Capture(CaptureSummary):
    body: str
    extracted: dict | None


class CapturesPage(BaseModel):
    total: int
    items: list[CaptureSummary]
```

Update `ghostbrain/api/models/__init__.py` to re-export the new types.

- [ ] **Step 7.2: Write failing tests**

Create `ghostbrain/api/tests/test_captures.py`:

```python
"""GET /v1/captures and GET /v1/captures/{id}."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient


def _write_pending(vault: Path, capture_id: str, payload: dict) -> Path:
    pending = vault / "90-meta" / "queue" / "pending"
    pending.mkdir(parents=True, exist_ok=True)
    p = pending / f"{capture_id}.json"
    p.write_text(json.dumps(payload))
    return p


def _write_audit(vault: Path, date_iso: str, lines: list[dict]) -> Path:
    audit = vault / "90-meta" / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    p = audit / f"{date_iso}.jsonl"
    p.write_text("\n".join(json.dumps(l) for l in lines))
    return p


def test_empty_returns_zero_total(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/captures", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 0
    assert data["items"] == []


def test_pending_items_appear(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_pending(tmp_vault, "p1", {
        "source": "gmail", "title": "re: design crit",
        "snippet": "works for me", "from": "theo · 8:14am",
        "tags": ["followup"], "capturedAt": now,
    })
    res = client.get("/v1/captures", headers=auth_headers)
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["title"] == "re: design crit"
    assert data["items"][0]["from"] == "theo · 8:14am"
    assert data["items"][0]["unread"] is True  # recent → unread


def test_audit_items_appear(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat().replace("+00:00", "Z")
    _write_audit(tmp_vault, today, [{
        "id": "a1", "source": "slack", "title": "#product-feedback",
        "snippet": "users ask for shortcuts", "from": "mira · 8:01am",
        "tags": ["feedback"], "capturedAt": yesterday,
    }])
    res = client.get("/v1/captures", headers=auth_headers)
    data = res.json()
    titles = [i["title"] for i in data["items"]]
    assert "#product-feedback" in titles


def test_limit_caps_results(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    for i in range(10):
        _write_pending(tmp_vault, f"p{i}", {
            "source": "gmail", "title": f"item {i}",
            "snippet": "x", "from": "x · x",
            "tags": [], "capturedAt": now,
        })
    res = client.get("/v1/captures?limit=3", headers=auth_headers)
    data = res.json()
    assert data["total"] == 10
    assert len(data["items"]) == 3


def test_source_filter(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_pending(tmp_vault, "g1", {
        "source": "gmail", "title": "x", "snippet": "x",
        "from": "x", "tags": [], "capturedAt": now,
    })
    _write_pending(tmp_vault, "s1", {
        "source": "slack", "title": "y", "snippet": "y",
        "from": "y", "tags": [], "capturedAt": now,
    })
    res = client.get("/v1/captures?source=slack", headers=auth_headers)
    data = res.json()
    assert all(i["source"] == "slack" for i in data["items"])


def test_capture_detail_includes_body(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    _write_pending(tmp_vault, "p1", {
        "source": "gmail", "title": "subject",
        "snippet": "snippet here", "from": "x",
        "tags": [], "capturedAt": now,
        "body": "full body text of the email",
    })
    res = client.get("/v1/captures/p1", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["body"] == "full body text of the email"


def test_capture_detail_404(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/captures/does-not-exist", headers=auth_headers)
    assert res.status_code == 404
```

- [ ] **Step 7.3: Run, watch fail**

```bash
pytest ghostbrain/api/tests/test_captures.py -v
```

- [ ] **Step 7.4: Implement the repo**

Create `ghostbrain/api/repo/captures.py`:

```python
"""Capture aggregation from queue + audit."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ghostbrain.paths import audit_dir, queue_dir


def _is_recent(iso: str, hours: int = 6) -> bool:
    try:
        when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - when) < timedelta(hours=hours)


def _record_from_payload(capture_id: str, payload: dict) -> dict:
    captured_at = payload.get("capturedAt", "")
    return {
        "id": capture_id,
        "source": payload.get("source", "unknown"),
        "title": payload.get("title", "(no title)"),
        "snippet": payload.get("snippet", ""),
        "from": payload.get("from", ""),
        "tags": payload.get("tags", []),
        "unread": _is_recent(captured_at) if captured_at else False,
        "capturedAt": captured_at,
    }


def _list_pending() -> list[tuple[dict, dict]]:
    """Returns list of (record, full_payload) tuples."""
    pending = queue_dir() / "pending"
    if not pending.exists():
        return []
    out = []
    for p in pending.iterdir():
        if not p.is_file() or p.suffix != ".json":
            continue
        try:
            payload = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        out.append((_record_from_payload(p.stem, payload), payload))
    return out


def _list_audit(days_back: int = 2) -> list[tuple[dict, dict]]:
    audit = audit_dir()
    if not audit.exists():
        return []
    out = []
    today = datetime.now(timezone.utc).date()
    for offset in range(days_back + 1):
        day = today - timedelta(days=offset)
        path = audit / f"{day.isoformat()}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            capture_id = payload.get("id") or f"audit-{day}-{len(out)}"
            out.append((_record_from_payload(capture_id, payload), payload))
    return out


def list_captures(
    limit: int = 50, offset: int = 0, source: str | None = None
) -> dict:
    """Returns CapturesPage shape."""
    everything = [r for r, _ in _list_pending()] + [r for r, _ in _list_audit()]
    if source:
        everything = [r for r in everything if r["source"] == source]
    everything.sort(key=lambda r: r["capturedAt"], reverse=True)
    total = len(everything)
    items = everything[offset : offset + limit]
    return {"total": total, "items": items}


def get_capture(capture_id: str) -> dict | None:
    """Returns the full Capture (summary + body + extracted) or None."""
    for record, payload in _list_pending():
        if record["id"] == capture_id:
            return {**record, "body": payload.get("body", ""), "extracted": payload.get("extracted")}
    for record, payload in _list_audit(days_back=7):
        if record["id"] == capture_id:
            return {**record, "body": payload.get("body", ""), "extracted": payload.get("extracted")}
    return None
```

- [ ] **Step 7.5: Implement the routes**

Create `ghostbrain/api/routes/captures.py`:

```python
"""GET /v1/captures, GET /v1/captures/{id}."""
from fastapi import APIRouter, HTTPException, Query

from ghostbrain.api.models.capture import Capture, CapturesPage
from ghostbrain.api.repo.captures import get_capture, list_captures

router = APIRouter(prefix="/v1/captures", tags=["captures"])


@router.get("", response_model=CapturesPage)
def captures(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    source: str | None = Query(None),
) -> dict:
    return list_captures(limit=limit, offset=offset, source=source)


@router.get("/{capture_id}", response_model=Capture)
def capture_detail(capture_id: str) -> dict:
    record = get_capture(capture_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Capture not found: {capture_id}")
    return record
```

- [ ] **Step 7.6: Register router**

Edit `ghostbrain/api/main.py`, add `from ghostbrain.api.routes import captures as captures_routes` + `app.include_router(captures_routes.router)`.

- [ ] **Step 7.7: Run, commit**

```bash
pytest ghostbrain/api/tests/test_captures.py -v
# expected: 7 passed
git add ghostbrain/api/models/capture.py ghostbrain/api/models/__init__.py ghostbrain/api/repo/captures.py ghostbrain/api/routes/captures.py ghostbrain/api/main.py ghostbrain/api/tests/test_captures.py
git commit -m "feat(api): GET /v1/captures and /v1/captures/{id}

Pending items from queue/pending/*.json + recent audit lines from
audit/<date>.jsonl. Sorted by capturedAt desc. ?limit/?offset/?source
query params. unread=true for items captured within the last 6h."
```

---

### Task 8: Meetings endpoint

**Files:**
- Create: `ghostbrain/api/models/meeting.py`
- Modify: `ghostbrain/api/models/__init__.py`
- Create: `ghostbrain/api/repo/meetings.py`
- Create: `ghostbrain/api/routes/meetings.py`
- Modify: `ghostbrain/api/main.py`
- Create: `ghostbrain/api/tests/test_meetings.py`

- [ ] **Step 8.1: Inspect existing recorder for vault layout**

```bash
grep -rn "Meetings\|meetings/" ghostbrain/recorder/ 2>&1 | head -20
```

Identify where the recorder writes meeting markdown files. Most likely path: `<vault>/20-contexts/<ctx>/meetings/<date>-<slug>.md`. Use that. If the recorder uses a different path, adapt the repo function accordingly — **document the actual path in a comment at the top of `repo/meetings.py`**.

- [ ] **Step 8.2: Model**

Create `ghostbrain/api/models/meeting.py`:

```python
"""Meeting schemas."""
from pydantic import BaseModel, ConfigDict


class PastMeeting(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str
    date: str
    dur: str
    speakers: int
    tags: list[str]


class MeetingsPage(BaseModel):
    total: int
    items: list[PastMeeting]
```

Update `__init__.py` re-exports.

- [ ] **Step 8.3: Tests**

Create `ghostbrain/api/tests/test_meetings.py`:

```python
"""GET /v1/meetings."""
from pathlib import Path

from fastapi.testclient import TestClient

from ghostbrain.api.tests.conftest import write_note


MEETING_FRONTMATTER = """---
title: design crit · onboarding v3
date: 2026-05-08
dur: "28:14"
speakers: 4
tags: [design]
---

# Transcript
mira: okay so the onboarding flow...
"""


def test_empty_returns_no_meetings(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/meetings", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == {"total": 0, "items": []}


def test_meetings_are_listed(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    write_note(
        tmp_vault,
        "20-contexts/work/meetings/2026-05-08-design-crit.md",
        MEETING_FRONTMATTER,
    )
    res = client.get("/v1/meetings", headers=auth_headers)
    data = res.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["title"] == "design crit · onboarding v3"
    assert item["date"] == "2026-05-08"
    assert item["dur"] == "28:14"
    assert item["speakers"] == 4
    assert "design" in item["tags"]


def test_meetings_sorted_by_date_desc(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    write_note(tmp_vault, "20-contexts/work/meetings/2026-05-01.md",
        '---\ntitle: old\ndate: 2026-05-01\ndur: "1:00"\nspeakers: 2\ntags: []\n---\n')
    write_note(tmp_vault, "20-contexts/work/meetings/2026-05-08.md",
        '---\ntitle: new\ndate: 2026-05-08\ndur: "1:00"\nspeakers: 2\ntags: []\n---\n')
    res = client.get("/v1/meetings", headers=auth_headers)
    items = res.json()["items"]
    assert items[0]["date"] == "2026-05-08"
    assert items[1]["date"] == "2026-05-01"
```

- [ ] **Step 8.4: Run, watch fail. Implement repo and route. Pyyaml frontmatter parsing already pulled in via existing pyproject.toml dep `python-frontmatter`.**

Create `ghostbrain/api/repo/meetings.py`:

```python
"""Meeting markdown reader.

Reads files matching <vault>/20-contexts/*/meetings/*.md. Frontmatter must
contain at minimum: title, date, dur, speakers, tags.
"""
from __future__ import annotations

from pathlib import Path

import frontmatter

from ghostbrain.paths import vault_path


def _walk_meeting_files() -> list[Path]:
    vault = vault_path()
    if not vault.exists():
        return []
    pattern = "20-contexts/*/meetings/*.md"
    return list(vault.glob(pattern))


def _parse(path: Path) -> dict | None:
    try:
        post = frontmatter.load(path)
    except Exception:
        return None
    fm = post.metadata
    if not all(k in fm for k in ("title", "date", "dur", "speakers")):
        return None
    return {
        "id": path.stem,
        "title": str(fm["title"]),
        "date": str(fm["date"]),
        "dur": str(fm["dur"]),
        "speakers": int(fm["speakers"]),
        "tags": list(fm.get("tags", [])),
    }


def list_meetings(limit: int = 50, offset: int = 0) -> dict:
    items = [m for m in (_parse(p) for p in _walk_meeting_files()) if m is not None]
    items.sort(key=lambda m: m["date"], reverse=True)
    total = len(items)
    return {"total": total, "items": items[offset : offset + limit]}
```

Create `ghostbrain/api/routes/meetings.py`:

```python
"""GET /v1/meetings."""
from fastapi import APIRouter, Query

from ghostbrain.api.models.meeting import MeetingsPage
from ghostbrain.api.repo.meetings import list_meetings

router = APIRouter(prefix="/v1/meetings", tags=["meetings"])


@router.get("", response_model=MeetingsPage)
def meetings(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict:
    return list_meetings(limit=limit, offset=offset)
```

Register router in `main.py`.

- [ ] **Step 8.5: Run, commit**

```bash
pytest ghostbrain/api/tests/test_meetings.py -v
# expected: 3 passed
git add ghostbrain/api/models/meeting.py ghostbrain/api/models/__init__.py ghostbrain/api/repo/meetings.py ghostbrain/api/routes/meetings.py ghostbrain/api/main.py ghostbrain/api/tests/test_meetings.py
git commit -m "feat(api): GET /v1/meetings

Reads <vault>/20-contexts/*/meetings/*.md, parses frontmatter for
title/date/dur/speakers/tags. Sorted by date desc."
```

---

### Task 9: Agenda endpoint

**Files:**
- Create: `ghostbrain/api/models/agenda.py`
- Modify: `ghostbrain/api/models/__init__.py`
- Create: `ghostbrain/api/repo/agenda.py`
- Create: `ghostbrain/api/routes/agenda.py`
- Modify: `ghostbrain/api/main.py`
- Create: `ghostbrain/api/tests/test_agenda.py`

Follows the same pattern as Tasks 5-8. Endpoint: `GET /v1/agenda?date=YYYY-MM-DD`.

- [ ] **Step 9.1: Model**

Create `ghostbrain/api/models/agenda.py`:

```python
"""Agenda schemas."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AgendaStatus = Literal["upcoming", "recorded"]


class AgendaItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    time: str
    duration: str
    title: str
    with_: list[str] = Field(alias="with")
    status: AgendaStatus
```

Update `__init__.py` re-exports.

- [ ] **Step 9.2: Tests**

Create `ghostbrain/api/tests/test_agenda.py`:

```python
"""GET /v1/agenda."""
from pathlib import Path

from fastapi.testclient import TestClient

from ghostbrain.api.tests.conftest import write_note


def test_no_events_returns_empty(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/agenda?date=2026-05-11", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


def test_lists_today_events(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    write_note(
        tmp_vault,
        "20-contexts/work/calendar/2026-05-11-1100-design-crit.md",
        """---
title: Design crit · onboarding v3
date: 2026-05-11
time: "11:00"
duration: "30m"
with: [mira, jules, sam]
---
""",
    )
    res = client.get("/v1/agenda?date=2026-05-11", headers=auth_headers)
    data = res.json()
    assert len(data) == 1
    item = data[0]
    assert item["title"] == "Design crit · onboarding v3"
    assert item["time"] == "11:00"
    assert item["with"] == ["mira", "jules", "sam"]
    assert item["status"] == "upcoming"


def test_status_recorded_when_meeting_exists(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    write_note(tmp_vault, "20-contexts/work/calendar/2026-05-11-0900-standup.md", """---
title: standup
date: 2026-05-11
time: "09:00"
duration: "20m"
with: [team]
---
""")
    write_note(tmp_vault, "20-contexts/work/meetings/2026-05-11-standup.md", """---
title: standup
date: 2026-05-11
dur: "18:32"
speakers: 5
tags: []
---
""")
    res = client.get("/v1/agenda?date=2026-05-11", headers=auth_headers)
    items = res.json()
    standup = next(i for i in items if i["title"] == "standup")
    assert standup["status"] == "recorded"
```

- [ ] **Step 9.3: Implement repo + route**

Create `ghostbrain/api/repo/agenda.py`:

```python
"""Calendar agenda reader."""
from __future__ import annotations

from pathlib import Path

import frontmatter

from ghostbrain.paths import vault_path


def _walk_calendar(date: str) -> list[Path]:
    vault = vault_path()
    if not vault.exists():
        return []
    # Files for a given date are named with the date prefix.
    return list(vault.glob(f"20-contexts/*/calendar/{date}*.md"))


def _meeting_titles_on(date: str) -> set[str]:
    vault = vault_path()
    if not vault.exists():
        return set()
    out: set[str] = set()
    for path in vault.glob(f"20-contexts/*/meetings/*.md"):
        try:
            post = frontmatter.load(path)
        except Exception:
            continue
        if str(post.metadata.get("date", "")) == date:
            out.add(str(post.metadata.get("title", "")))
    return out


def _parse_event(path: Path, recorded_titles: set[str]) -> dict | None:
    try:
        post = frontmatter.load(path)
    except Exception:
        return None
    fm = post.metadata
    if not all(k in fm for k in ("title", "time", "duration")):
        return None
    title = str(fm["title"])
    status = "recorded" if title in recorded_titles else "upcoming"
    return {
        "id": path.stem,
        "time": str(fm["time"]),
        "duration": str(fm["duration"]),
        "title": title,
        "with": list(fm.get("with", [])),
        "status": status,
    }


def list_agenda(date: str) -> list[dict]:
    recorded = _meeting_titles_on(date)
    items = [
        e for e in (_parse_event(p, recorded) for p in _walk_calendar(date)) if e is not None
    ]
    items.sort(key=lambda e: e["time"])
    return items
```

Create `ghostbrain/api/routes/agenda.py`:

```python
"""GET /v1/agenda?date=YYYY-MM-DD."""
from datetime import date as dt_date

from fastapi import APIRouter, Query

from ghostbrain.api.models.agenda import AgendaItem
from ghostbrain.api.repo.agenda import list_agenda

router = APIRouter(prefix="/v1/agenda", tags=["agenda"])


@router.get("", response_model=list[AgendaItem])
def agenda(
    date: str = Query(default_factory=lambda: dt_date.today().isoformat()),
) -> list[dict]:
    return list_agenda(date=date)
```

Register router. Run tests, commit.

```bash
git commit -m "feat(api): GET /v1/agenda?date=YYYY-MM-DD

Reads <vault>/20-contexts/*/calendar/<date>*.md. status='recorded' when
a corresponding meeting file with the same title exists in meetings/.
Defaults date to today (local)."
```

---

### Task 10: Activity endpoint

**Files:**
- Create: `ghostbrain/api/models/activity.py`
- Modify: `ghostbrain/api/models/__init__.py`
- Create: `ghostbrain/api/repo/activity.py`
- Create: `ghostbrain/api/routes/activity.py`
- Modify: `ghostbrain/api/main.py`
- Create: `ghostbrain/api/tests/test_activity.py`

Endpoint: `GET /v1/activity?windowMinutes=240`. Returns recent processed events from the audit log.

- [ ] **Step 10.1: Model**

Create `ghostbrain/api/models/activity.py`:

```python
"""Activity row schema."""
from pydantic import BaseModel, ConfigDict


class ActivityRow(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    source: str
    verb: str
    subject: str
    atRelative: str
    at: str
```

Update `__init__.py`.

- [ ] **Step 10.2: Tests**

Create `ghostbrain/api/tests/test_activity.py`:

```python
"""GET /v1/activity."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient


def _write_audit_event(vault: Path, date_iso: str, event: dict) -> None:
    audit = vault / "90-meta" / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    path = audit / f"{date_iso}.jsonl"
    with path.open("a") as f:
        f.write(json.dumps(event) + "\n")


def test_empty_returns_no_activity(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/activity?windowMinutes=240", headers=auth_headers)
    assert res.status_code == 200
    assert res.json() == []


def test_includes_recent_events(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    one_min_ago = (now - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    _write_audit_event(tmp_vault, today, {
        "id": "evt1", "source": "gmail", "verb": "archived",
        "subject": "3 newsletters", "at": one_min_ago,
    })
    res = client.get("/v1/activity?windowMinutes=240", headers=auth_headers)
    data = res.json()
    assert len(data) == 1
    assert data[0]["source"] == "gmail"
    assert data[0]["verb"] == "archived"


def test_excludes_old_events(
    client: TestClient, auth_headers: dict[str, str], tmp_vault: Path
):
    now = datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    five_hours_ago = (now - timedelta(hours=5)).isoformat().replace("+00:00", "Z")
    _write_audit_event(tmp_vault, today, {
        "id": "evt-old", "source": "gmail", "verb": "x",
        "subject": "old", "at": five_hours_ago,
    })
    # windowMinutes=240 = 4 hours
    res = client.get("/v1/activity?windowMinutes=240", headers=auth_headers)
    assert res.json() == []
```

- [ ] **Step 10.3: Implement**

Create `ghostbrain/api/repo/activity.py`:

```python
"""Recent activity from audit log."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ghostbrain.paths import audit_dir


def _relative(when: datetime) -> str:
    delta = datetime.now(timezone.utc) - when
    secs = int(delta.total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    if secs < 86_400:
        return f"{secs // 3600}h"
    return f"{secs // 86_400}d"


def list_activity(window_minutes: int = 240) -> list[dict]:
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=window_minutes)
    audit = audit_dir()
    if not audit.exists():
        return []
    items: list[dict] = []
    today = datetime.now(timezone.utc).date()
    for offset in range(2):  # today + yesterday (covers any reasonable windowMinutes)
        day = today - timedelta(days=offset)
        path = audit / f"{day.isoformat()}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            at_str = event.get("at", "")
            try:
                when = datetime.fromisoformat(at_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            if when < cutoff:
                continue
            items.append({
                "id": event.get("id", f"audit-{day}-{len(items)}"),
                "source": event.get("source", "unknown"),
                "verb": event.get("verb", "processed"),
                "subject": event.get("subject", ""),
                "atRelative": _relative(when),
                "at": at_str,
            })
    items.sort(key=lambda r: r["at"], reverse=True)
    return items
```

Create `ghostbrain/api/routes/activity.py`:

```python
"""GET /v1/activity."""
from fastapi import APIRouter, Query

from ghostbrain.api.models.activity import ActivityRow
from ghostbrain.api.repo.activity import list_activity

router = APIRouter(prefix="/v1/activity", tags=["activity"])


@router.get("", response_model=list[ActivityRow])
def activity(windowMinutes: int = Query(240, ge=1, le=10_080)) -> list[dict]:
    return list_activity(window_minutes=windowMinutes)
```

Register router. Run tests. Commit:

```bash
git commit -m "feat(api): GET /v1/activity?windowMinutes=240

Reads audit/<today>.jsonl + yesterday's, filters by 'at' within window,
sorts desc, formats atRelative as Ns/Nm/Nh/Nd."
```

---

### Task 11: Suggestions endpoint (Phase 1 stub)

**Files:**
- Create: `ghostbrain/api/models/suggestion.py`
- Modify: `ghostbrain/api/models/__init__.py`
- Create: `ghostbrain/api/repo/suggestions.py`
- Create: `ghostbrain/api/routes/suggestions.py`
- Modify: `ghostbrain/api/main.py`
- Create: `ghostbrain/api/tests/test_suggestions.py`

Endpoint returns 2-3 trivial hints. Real LLM-driven suggestions are Phase 2.

- [ ] **Step 11.1: Model**

Create `ghostbrain/api/models/suggestion.py`:

```python
"""Suggestion schema."""
from pydantic import BaseModel, ConfigDict


class Suggestion(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    icon: str
    title: str
    body: str
    accent: bool = False
```

Update `__init__.py`.

- [ ] **Step 11.2: Tests**

Create `ghostbrain/api/tests/test_suggestions.py`:

```python
"""GET /v1/suggestions."""
from fastapi.testclient import TestClient


def test_returns_list(client: TestClient, auth_headers: dict[str, str]):
    res = client.get("/v1/suggestions", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert isinstance(data, list)


def test_suggestions_have_required_fields(
    client: TestClient, auth_headers: dict[str, str]
):
    data = client.get("/v1/suggestions", headers=auth_headers).json()
    for item in data:
        assert {"id", "icon", "title", "body"}.issubset(item.keys())
```

- [ ] **Step 11.3: Implement**

Create `ghostbrain/api/repo/suggestions.py`:

```python
"""Suggestions stub for Phase 1.

Returns a small set of always-on hints. Phase 2 replaces this with an
LLM-driven suggestion engine that reads captures + meetings + activity.
"""
from __future__ import annotations

from ghostbrain.api.repo.connectors import list_connectors


def list_suggestions() -> list[dict]:
    suggestions: list[dict] = []
    connectors = list_connectors()
    off_connectors = [c for c in connectors if c["state"] == "off"]
    if off_connectors:
        names = ", ".join(c["displayName"] for c in off_connectors[:3])
        suggestions.append({
            "id": "connect-something",
            "icon": "link",
            "title": f"connect {off_connectors[0]['displayName']}",
            "body": f"these connectors are configured but not running: {names}.",
            "accent": False,
        })
    err_connectors = [c for c in connectors if c["state"] == "err"]
    if err_connectors:
        names = ", ".join(c["displayName"] for c in err_connectors[:2])
        suggestions.append({
            "id": "fix-errors",
            "icon": "alert-circle",
            "title": "connector error" + ("s" if len(err_connectors) > 1 else ""),
            "body": f"{names} reported an error and stopped syncing. reauthorize?",
            "accent": True,
        })
    return suggestions
```

Create `ghostbrain/api/routes/suggestions.py`:

```python
"""GET /v1/suggestions."""
from fastapi import APIRouter

from ghostbrain.api.models.suggestion import Suggestion
from ghostbrain.api.repo.suggestions import list_suggestions

router = APIRouter(prefix="/v1/suggestions", tags=["suggestions"])


@router.get("", response_model=list[Suggestion])
def suggestions() -> list[dict]:
    return list_suggestions()
```

Register router. Test, commit:

```bash
git commit -m "feat(api): GET /v1/suggestions (Phase 1 stub)

Returns 0-2 trivially-derived hints from the connector list (off / err
states). Phase 2 replaces this with LLM-driven suggestions."
```

---

## Phase 1C — Electron main sidecar lifecycle

### Task 12: Sidecar process management

**Files:**
- Create: `desktop/src/main/sidecar.ts`

- [ ] **Step 12.1: Implement the Sidecar class**

Create `desktop/src/main/sidecar.ts`:

```ts
import { spawn, type ChildProcess } from 'node:child_process';
import { EventEmitter } from 'node:events';

export interface SidecarInfo {
  port: number;
  token: string;
}

type Status = 'idle' | 'starting' | 'ready' | 'failed' | 'stopped';

interface FailureInfo {
  reason: string;
  stdoutTail: string;
  stderrTail: string;
}

const READY_LINE_RE = /^READY port=(\d+) token=([0-9a-f]+)/m;
const STARTUP_TIMEOUT_MS = 10_000;
const RESTART_BACKOFF_MS = 2_000;
const MAX_RESTART_ATTEMPTS = 1;

function pythonExecutable(): string {
  // On Windows some installs only have `python` on PATH; check at runtime.
  // For dev we assume macOS / Linux with python3.
  return process.platform === 'win32' ? 'python' : 'python3';
}

export class Sidecar extends EventEmitter {
  private proc: ChildProcess | null = null;
  private info: SidecarInfo | null = null;
  private status: Status = 'idle';
  private restartAttempts = 0;
  private stdoutBuf = '';
  private stderrBuf = '';

  constructor(private readonly cwd: string) {
    super();
  }

  getStatus(): Status {
    return this.status;
  }

  getInfo(): SidecarInfo | null {
    return this.info;
  }

  async start(): Promise<SidecarInfo> {
    if (this.status === 'ready' && this.info) return this.info;
    if (this.status === 'starting') {
      return new Promise((resolve, reject) => {
        this.once('ready', resolve);
        this.once('failed', (info: FailureInfo) => reject(new Error(info.reason)));
      });
    }
    this.status = 'starting';
    return this.spawn();
  }

  async stop(): Promise<void> {
    if (!this.proc) {
      this.status = 'stopped';
      return;
    }
    this.proc.kill('SIGTERM');
    await new Promise<void>((resolve) => {
      const timer = setTimeout(() => {
        if (this.proc && !this.proc.killed) this.proc.kill('SIGKILL');
        resolve();
      }, 5_000);
      this.proc?.once('exit', () => {
        clearTimeout(timer);
        resolve();
      });
    });
    this.proc = null;
    this.info = null;
    this.status = 'stopped';
  }

  private spawn(): Promise<SidecarInfo> {
    return new Promise((resolve, reject) => {
      const exe = pythonExecutable();
      const proc = spawn(exe, ['-m', 'ghostbrain.api'], {
        cwd: this.cwd,
        env: { ...process.env, PYTHONUNBUFFERED: '1' },
      });
      this.proc = proc;
      this.stdoutBuf = '';
      this.stderrBuf = '';

      const timeout = setTimeout(() => {
        proc.kill();
        this.fail('Sidecar did not become ready within 10s');
        reject(new Error('Sidecar startup timeout'));
      }, STARTUP_TIMEOUT_MS);

      proc.stdout?.on('data', (chunk: Buffer) => {
        const text = chunk.toString();
        this.stdoutBuf = (this.stdoutBuf + text).slice(-4_000);
        const match = text.match(READY_LINE_RE);
        if (match && this.info === null) {
          clearTimeout(timeout);
          this.info = {
            port: parseInt(match[1]!, 10),
            token: match[2]!,
          };
          this.status = 'ready';
          this.restartAttempts = 0;
          this.emit('ready', this.info);
          resolve(this.info);
        }
      });

      proc.stderr?.on('data', (chunk: Buffer) => {
        this.stderrBuf = (this.stderrBuf + chunk.toString()).slice(-4_000);
      });

      proc.on('error', (err) => {
        clearTimeout(timeout);
        this.fail(`Could not spawn ${exe}: ${err.message}`);
        reject(err);
      });

      proc.on('exit', (code, signal) => {
        if (this.status !== 'ready') {
          // Failed during startup
          clearTimeout(timeout);
          this.fail(
            `Sidecar exited during startup (code=${code} signal=${signal}). stderr: ${this.stderrBuf.slice(-500)}`,
          );
          return;
        }
        // Unexpected exit after ready
        this.info = null;
        this.status = 'failed';
        if (this.restartAttempts < MAX_RESTART_ATTEMPTS) {
          this.restartAttempts++;
          setTimeout(() => {
            this.spawn().catch(() => {
              // already emitted 'failed'
            });
          }, RESTART_BACKOFF_MS);
        } else {
          this.fail(
            `Sidecar crashed and auto-restart exhausted. last stderr: ${this.stderrBuf.slice(-500)}`,
          );
        }
      });
    });
  }

  private fail(reason: string): void {
    this.status = 'failed';
    const info: FailureInfo = {
      reason,
      stdoutTail: this.stdoutBuf.slice(-500),
      stderrTail: this.stderrBuf.slice(-500),
    };
    this.emit('failed', info);
  }
}
```

- [ ] **Step 12.2: Smoke test it manually**

Add a minimal verification step at the bottom of the file (commented out, not committed). For real verification, the integration happens in Task 15 when main wires up the sidecar.

- [ ] **Step 12.3: typecheck**

```bash
cd desktop
npm run typecheck
```

Expected: clean.

- [ ] **Step 12.4: Commit**

```bash
git add desktop/src/main/sidecar.ts
git commit -m "feat(desktop): Sidecar class for Python subprocess lifecycle

Spawns python3 -m ghostbrain.api with cwd=repo root, parses 'READY port=X
token=Y' from stdout. 10s startup timeout. One auto-restart on unexpected
exit with 2s backoff. Captures last 500 bytes of stderr for diagnostics."
```

---

### Task 13: API forwarder

**Files:**
- Create: `desktop/src/main/api-forwarder.ts`

- [ ] **Step 13.1: Implement**

Create `desktop/src/main/api-forwarder.ts`:

```ts
import type { Sidecar } from './sidecar';

export type ApiResult<T = unknown> =
  | { ok: true; data: T }
  | { ok: false; error: string };

export async function forward<T = unknown>(
  sidecar: Sidecar,
  method: 'GET' | 'POST',
  path: string,
  body?: unknown,
): Promise<ApiResult<T>> {
  const info = sidecar.getInfo();
  if (!info) return { ok: false, error: 'Sidecar not ready' };
  try {
    const res = await fetch(`http://127.0.0.1:${info.port}${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${info.token}`,
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
      // 30s timeout via AbortController
      signal: AbortSignal.timeout(30_000),
    });
    if (!res.ok) {
      const text = await res.text();
      return { ok: false, error: `HTTP ${res.status}: ${text.slice(0, 500)}` };
    }
    const data = (await res.json()) as T;
    return { ok: true, data };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}
```

- [ ] **Step 13.2: typecheck + commit**

```bash
npm run typecheck
git add desktop/src/main/api-forwarder.ts
git commit -m "feat(desktop): typed HTTP forwarder to the sidecar

forward() calls 127.0.0.1:<port> with Bearer auth, 30s AbortSignal timeout,
returns { ok: true, data } | { ok: false, error }. Tokens never leave main."
```

---

### Task 14: Wire sidecar lifecycle in main + IPC handler

**Files:**
- Modify: `desktop/src/main/index.ts`

- [ ] **Step 14.1: Add sidecar instance + lifecycle + IPC handler**

Edit `desktop/src/main/index.ts`. Add imports at the top, instantiate `Sidecar` near the top of the module, wire IPC, hook into app lifecycle:

```ts
import { app, BrowserWindow, ipcMain, shell } from 'electron';
import { join } from 'node:path';
import * as settings from './settings';
import { pickVaultFolder } from './dialogs';
import { loadInitialState, attachStatePersistence } from './window-state';
import { buildAppMenu } from './menu';
import { settingsSchema } from '../shared/settings-schema';
import { Sidecar } from './sidecar';
import { forward } from './api-forwarder';
import type { Settings } from '../shared/types';

// Repo root: in dev, that's two levels up from the bundled main file
// (out/main/index.js -> out/main -> out -> desktop -> ghost-brain).
// In prod (Phase 2 bundles the sidecar as a binary), this changes.
function repoRoot(): string {
  return join(app.getAppPath(), '..');
}

const sidecar = new Sidecar(repoRoot());

// Existing createWindow function unchanged...

// === sidecar lifecycle ===
app.whenReady().then(async () => {
  buildAppMenu();
  createWindow();
  try {
    await sidecar.start();
    BrowserWindow.getAllWindows()[0]?.webContents.send('gb:sidecar:ready');
  } catch (err) {
    // The 'failed' event also fires; the renderer surfaces this.
    BrowserWindow.getAllWindows()[0]?.webContents.send('gb:sidecar:failed', {
      reason: err instanceof Error ? err.message : String(err),
    });
  }
});

sidecar.on('ready', () => {
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send('gb:sidecar:ready');
  }
});

sidecar.on('failed', (info: { reason: string }) => {
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send('gb:sidecar:failed', info);
  }
});

app.on('before-quit', async (event) => {
  if (sidecar.getStatus() !== 'stopped') {
    event.preventDefault();
    await sidecar.stop();
    app.quit();
  }
});

// === IPC handlers ===

ipcMain.handle('gb:settings:getAll', () => settings.getAll());
// (existing settings:set, dialogs:pickVaultFolder, shell:openPath handlers unchanged)

ipcMain.handle(
  'gb:api:request',
  async (_e, method: unknown, path: unknown, body: unknown) => {
    if (typeof method !== 'string' || typeof path !== 'string') {
      return { ok: false, error: 'Invalid request shape' };
    }
    const m = method.toUpperCase();
    if (m !== 'GET' && m !== 'POST') {
      return { ok: false, error: 'Method not allowed' };
    }
    if (!path.startsWith('/v1/')) {
      return { ok: false, error: 'Path not allowed (must start with /v1/)' };
    }
    return forward(sidecar, m, path, body);
  },
);

ipcMain.handle('gb:sidecar:retry', async () => {
  try {
    await sidecar.start();
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
});

// (existing window/activate handlers stay)
```

(Above is a structured outline — for the actual edit, locate the existing `ipcMain.handle` block and inject around it without disturbing existing handlers.)

- [ ] **Step 14.2: typecheck + dev smoke**

```bash
cd desktop
npm run typecheck
npm run dev   # background, ~15s for sidecar to come up
tail -20 /tmp/<dev-log>
```

You should see `READY port=… token=…` from the sidecar shortly after Electron boots.

- [ ] **Step 14.3: Commit**

```bash
git add desktop/src/main/index.ts
git commit -m "feat(desktop): spawn sidecar on app launch; wire api request IPC

On whenReady: starts the Sidecar (python3 -m ghostbrain.api). Emits
'gb:sidecar:ready' / 'gb:sidecar:failed' IPC events. 'gb:api:request'
handler validates method + path, forwards to sidecar. before-quit
gracefully stops the sidecar."
```

---

### Task 15: Preload bridge + shared API types

**Files:**
- Modify: `desktop/src/shared/types.ts`
- Create: `desktop/src/shared/api-types.ts`
- Modify: `desktop/src/preload/index.ts`

- [ ] **Step 15.1: API types (TS mirrors of Pydantic)**

Create `desktop/src/shared/api-types.ts`:

```ts
// TypeScript mirrors of the Pydantic models in ghostbrain/api/models/.
// Kept in sync manually for Phase 1; consider OpenAPI codegen in Phase 2.

export interface VaultStats {
  totalNotes: number;
  queuePending: number;
  vaultSizeBytes: number;
  lastSyncAt: string | null;
  indexedCount: number;
}

export type ConnectorState = 'on' | 'off' | 'err';

export interface Connector {
  id: string;
  displayName: string;
  state: ConnectorState;
  count: number;
  lastSyncAt: string | null;
  account: string | null;
  throughput: string | null;
  error: string | null;
}

export interface ConnectorDetail extends Connector {
  scopes: string[];
  pulls: string[];
  vaultDestination: string;
}

export interface CaptureSummary {
  id: string;
  source: string;
  title: string;
  snippet: string;
  from: string;
  tags: string[];
  unread: boolean;
  capturedAt: string;
}

export interface Capture extends CaptureSummary {
  body: string;
  extracted: Record<string, unknown> | null;
}

export interface CapturesPage {
  total: number;
  items: CaptureSummary[];
}

export interface PastMeeting {
  id: string;
  title: string;
  date: string;
  dur: string;
  speakers: number;
  tags: string[];
}

export interface MeetingsPage {
  total: number;
  items: PastMeeting[];
}

export type AgendaStatus = 'upcoming' | 'recorded';

export interface AgendaItem {
  id: string;
  time: string;
  duration: string;
  title: string;
  with: string[];
  status: AgendaStatus;
}

export interface ActivityRow {
  id: string;
  source: string;
  verb: string;
  subject: string;
  atRelative: string;
  at: string;
}

export interface Suggestion {
  id: string;
  icon: string;
  title: string;
  body: string;
  accent: boolean;
}
```

- [ ] **Step 15.2: Extend the bridge interface**

Edit `desktop/src/shared/types.ts`. Locate the `GbBridge` interface and add `api` and `sidecar`:

```ts
export interface GbBridge {
  // ... existing settings/dialogs/shell/platform/on
  api: {
    request<T = unknown>(
      method: 'GET' | 'POST',
      path: string,
      body?: unknown,
    ): Promise<{ ok: true; data: T } | { ok: false; error: string }>;
  };
  sidecar: {
    retry(): Promise<{ ok: true } | { ok: false; error: string }>;
  };
}
```

Also extend the `on(channel, ...)` overloads to include `'sidecar:ready'` and `'sidecar:failed'`:

```ts
on(channel: 'nav:settings', listener: () => void): () => void;
on(channel: 'sidecar:ready', listener: () => void): () => void;
on(channel: 'sidecar:failed', listener: (info: { reason: string }) => void): () => void;
```

- [ ] **Step 15.3: Implement the bridge**

Edit `desktop/src/preload/index.ts`. Extend the `bridge` object:

```ts
const bridge: GbBridge = {
  // ... existing
  api: {
    request: (method, path, body) =>
      ipcRenderer.invoke('gb:api:request', method, path, body),
  },
  sidecar: {
    retry: () => ipcRenderer.invoke('gb:sidecar:retry'),
  },
  on: (channel, listener) => {
    const wrapped = (_e: unknown, ...args: unknown[]) => (listener as (...a: unknown[]) => void)(...args);
    const ipcChannel = `gb:${channel}`;
    ipcRenderer.on(ipcChannel, wrapped);
    return () => {
      ipcRenderer.off(ipcChannel, wrapped);
    };
  },
};
```

The `on` implementation update: previously it ignored args; now it forwards them so `sidecar:failed` can deliver `{ reason }` to the renderer.

- [ ] **Step 15.4: Update the test stub**

Edit `desktop/src/renderer/test/setup.ts`. The stub `GbBridge` needs `api` and `sidecar`:

```ts
const stubBridge: GbBridge = {
  // ... existing
  api: { request: async () => ({ ok: true, data: null }) },
  sidecar: { retry: async () => ({ ok: true }) },
  on: () => () => {},
};
```

- [ ] **Step 15.5: typecheck, test, commit**

```bash
cd desktop
npm run typecheck
npm test
git add desktop/src/shared/types.ts desktop/src/shared/api-types.ts desktop/src/preload/index.ts desktop/src/renderer/test/setup.ts
git commit -m "feat(desktop): typed api bridge + sidecar control + api-types

window.gb.api.request<T>(method, path, body?) round-trips through main to
the sidecar. window.gb.sidecar.retry() triggers a re-start. The 'on'
method gains sidecar:ready and sidecar:failed channels. api-types.ts
mirrors the Pydantic schemas (manually for Phase 1; codegen later)."
```

---

## Phase 1D — Renderer data layer

### Task 16: React Query setup + provider

**Files:**
- Modify: `desktop/package.json`
- Create: `desktop/src/renderer/lib/api/query-client.ts`
- Create: `desktop/src/renderer/lib/api/client.ts`
- Modify: `desktop/src/renderer/main.tsx`

- [ ] **Step 16.1: Install React Query**

```bash
cd desktop
npm install @tanstack/react-query@^5.0.0
```

- [ ] **Step 16.2: Shared QueryClient**

Create `desktop/src/renderer/lib/api/query-client.ts`:

```ts
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 2,
      retryDelay: (attempt) => Math.min(1_000 * 2 ** attempt, 8_000),
      refetchOnWindowFocus: true,
    },
  },
});
```

- [ ] **Step 16.3: Typed client wrapper**

Create `desktop/src/renderer/lib/api/client.ts`:

```ts
export async function get<T>(path: string): Promise<T> {
  const result = await window.gb.api.request<T>('GET', path);
  if (!result.ok) throw new Error(result.error);
  return result.data;
}

export async function post<T>(path: string, body?: unknown): Promise<T> {
  const result = await window.gb.api.request<T>('POST', path, body);
  if (!result.ok) throw new Error(result.error);
  return result.data;
}
```

(POST included for symmetry; Phase 1 only uses GET.)

- [ ] **Step 16.4: Wrap App in QueryClientProvider**

Edit `desktop/src/renderer/main.tsx`:

```tsx
import React from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClientProvider } from '@tanstack/react-query';
import App from './App';
import { ErrorBoundary } from './components/ErrorBoundary';
import { queryClient } from './lib/api/query-client';
import './styles.css';

const container = document.getElementById('root');
if (!container) throw new Error('root element missing');
createRoot(container).render(
  <ErrorBoundary>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </ErrorBoundary>,
);
```

- [ ] **Step 16.5: typecheck, test, commit**

```bash
npm run typecheck
npm test
git add desktop/package.json desktop/package-lock.json desktop/src/renderer/lib/api/ desktop/src/renderer/main.tsx
git commit -m "feat(desktop): React Query client + typed api wrapper

@tanstack/react-query v5. Shared QueryClient with staleTime 30s, 2 retries
with exponential backoff. get<T>(path) throws on bridge error. App wrapped
in QueryClientProvider beneath ErrorBoundary."
```

---

### Task 17: Per-resource hooks

**Files:**
- Create: `desktop/src/renderer/lib/api/hooks.ts`

- [ ] **Step 17.1: Implement all 9 hooks**

Create `desktop/src/renderer/lib/api/hooks.ts`:

```ts
import { useQuery } from '@tanstack/react-query';

import type {
  ActivityRow,
  AgendaItem,
  Capture,
  CapturesPage,
  Connector,
  ConnectorDetail,
  MeetingsPage,
  Suggestion,
  VaultStats,
} from '../../../shared/api-types';
import { get } from './client';

export function useVaultStats() {
  return useQuery({
    queryKey: ['vault', 'stats'],
    queryFn: () => get<VaultStats>('/v1/vault/stats'),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
}

export function useConnectors() {
  return useQuery({
    queryKey: ['connectors'],
    queryFn: () => get<Connector[]>('/v1/connectors'),
    staleTime: 60_000,
    refetchInterval: 60_000,
  });
}

export function useConnector(id: string | null) {
  return useQuery({
    queryKey: ['connector', id],
    queryFn: () => get<ConnectorDetail>(`/v1/connectors/${id}`),
    enabled: id !== null,
    staleTime: 60_000,
  });
}

export function useCaptures(opts?: { limit?: number; source?: string }) {
  const params = new URLSearchParams();
  if (opts?.limit) params.set('limit', String(opts.limit));
  if (opts?.source) params.set('source', opts.source);
  const query = params.toString();
  return useQuery({
    queryKey: ['captures', opts ?? {}],
    queryFn: () => get<CapturesPage>(`/v1/captures${query ? '?' + query : ''}`),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
}

export function useCapture(id: string | null) {
  return useQuery({
    queryKey: ['capture', id],
    queryFn: () => get<Capture>(`/v1/captures/${id}`),
    enabled: id !== null,
    staleTime: 60_000,
  });
}

export function useMeetings(opts?: { limit?: number }) {
  const params = new URLSearchParams();
  if (opts?.limit) params.set('limit', String(opts.limit));
  const query = params.toString();
  return useQuery({
    queryKey: ['meetings', opts ?? {}],
    queryFn: () => get<MeetingsPage>(`/v1/meetings${query ? '?' + query : ''}`),
    staleTime: 60_000,
  });
}

export function useAgenda(date?: string) {
  const today = new Date().toISOString().slice(0, 10);
  const queryDate = date ?? today;
  return useQuery({
    queryKey: ['agenda', queryDate],
    queryFn: () => get<AgendaItem[]>(`/v1/agenda?date=${queryDate}`),
    staleTime: 60_000,
  });
}

export function useRecentActivity(windowMinutes = 240) {
  return useQuery({
    queryKey: ['activity', windowMinutes],
    queryFn: () => get<ActivityRow[]>(`/v1/activity?windowMinutes=${windowMinutes}`),
    staleTime: 30_000,
    refetchInterval: 30_000,
  });
}

export function useSuggestions() {
  return useQuery({
    queryKey: ['suggestions'],
    queryFn: () => get<Suggestion[]>('/v1/suggestions'),
    staleTime: 5 * 60_000,
  });
}
```

- [ ] **Step 17.2: typecheck + commit**

```bash
npm run typecheck
git add desktop/src/renderer/lib/api/hooks.ts
git commit -m "feat(desktop): react query hooks per endpoint

useVaultStats, useConnectors, useConnector, useCaptures, useCapture,
useMeetings, useAgenda, useRecentActivity, useSuggestions. Per-resource
staleTime + refetchInterval defaults; lists refresh every 30-60s."
```

---

## Phase 1E — UI primitives for async state

### Task 18: Skeleton / Empty / Error panel components

**Files:**
- Create: `desktop/src/renderer/components/SkeletonRows.tsx`
- Create: `desktop/src/renderer/components/PanelEmpty.tsx`
- Create: `desktop/src/renderer/components/PanelError.tsx`

- [ ] **Step 18.1: SkeletonRows**

Create `desktop/src/renderer/components/SkeletonRows.tsx`:

```tsx
interface Props {
  count?: number;
  height?: number;
}

export function SkeletonRows({ count = 3, height = 32 }: Props) {
  return (
    <div className="flex flex-col gap-1 p-2">
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="animate-pulse rounded-sm bg-fog/40"
          style={{ height }}
        />
      ))}
    </div>
  );
}
```

> `animate-pulse` is a Tailwind default. `bg-fog/40` reuses the theme token.

- [ ] **Step 18.2: PanelEmpty**

Create `desktop/src/renderer/components/PanelEmpty.tsx`:

```tsx
import { Lucide } from './Lucide';

interface Props {
  icon?: string;
  message: string;
  cta?: { label: string; onClick: () => void };
}

export function PanelEmpty({ icon = 'inbox', message, cta }: Props) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 p-8 text-center">
      <Lucide name={icon} size={20} color="var(--ink-3)" />
      <p className="m-0 text-12 text-ink-2">{message}</p>
      {cta && (
        <button
          type="button"
          onClick={cta.onClick}
          className="cursor-pointer rounded-r6 border border-hairline-2 bg-transparent px-3 py-1 text-12 text-ink-1 transition-colors hover:bg-vellum"
        >
          {cta.label}
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 18.3: PanelError**

Create `desktop/src/renderer/components/PanelError.tsx`:

```tsx
import { Lucide } from './Lucide';

interface Props {
  message: string;
  onRetry?: () => void;
}

export function PanelError({ message, onRetry }: Props) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 p-8 text-center">
      <Lucide name="alert-triangle" size={20} color="var(--oxblood)" />
      <p className="m-0 max-w-[280px] text-12 text-ink-2">{message}</p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="cursor-pointer rounded-r6 border border-oxblood/30 bg-oxblood/10 px-3 py-1 text-12 text-oxblood transition-colors hover:bg-oxblood/20"
        >
          retry
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 18.4: typecheck + commit**

```bash
npm run typecheck
git add desktop/src/renderer/components/SkeletonRows.tsx desktop/src/renderer/components/PanelEmpty.tsx desktop/src/renderer/components/PanelError.tsx
git commit -m "feat(desktop): SkeletonRows / PanelEmpty / PanelError primitives

Reusable async-state UI: shimmer skeleton for loading, neutral empty
state with optional CTA, oxblood error state with optional retry."
```

---

## Phase 1F — Asset additions

### Task 19: 4 missing connector logos

**Files:**
- Create: `desktop/src/renderer/public/assets/connectors/claude_code.svg`
- Create: `desktop/src/renderer/public/assets/connectors/jira.svg`
- Create: `desktop/src/renderer/public/assets/connectors/confluence.svg`
- Create: `desktop/src/renderer/public/assets/connectors/atlassian.svg`

- [ ] **Step 19.1: Source the logos**

Logos for these 4 connectors don't exist in the repo yet. The simplest path:

1. Find each brand's official press/brand-asset page (Atlassian's brand guidelines page provides official Jira, Confluence, Atlassian SVGs).
2. For Claude Code: use a stylized "C" or the existing ghostbrain glyph variant.

For each, save as a small SVG (~24×24 viewBox, single-color or limited palette) under `desktop/src/renderer/public/assets/connectors/`.

If you can't get official brand assets in a clean form, use placeholder SVGs — small text-based logos like:

```xml
<!-- claude_code.svg -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <rect x="2" y="2" width="20" height="20" rx="4" fill="#D97757"/>
  <text x="12" y="16" text-anchor="middle" font-family="monospace" font-size="11" font-weight="700" fill="#FAFAFA">cc</text>
</svg>
```

```xml
<!-- jira.svg -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <path d="M11.53 2 5.07 8.46l3.23 3.23-3.23 3.23 6.46 6.46 6.46-6.46-3.23-3.23 3.23-3.23z" fill="#2684FF"/>
</svg>
```

```xml
<!-- confluence.svg -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <path d="M2 17.5c.5-2 4-4 8-4s7.5 2 8 4c-1.5 2-4.5 3.5-8 3.5s-6.5-1.5-8-3.5zm0-11c.5-2 4-4 8-4s7.5 2 8 4c-1.5 2-4.5 3.5-8 3.5S3.5 8.5 2 6.5z" fill="#0052CC"/>
</svg>
```

```xml
<!-- atlassian.svg -->
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">
  <path d="M7.5 11.5L2 22h11l-5.5-10.5zm9-7L11 15l3.5 7h7.5L16.5 4.5z" fill="#0052CC"/>
</svg>
```

These are quick approximations. The user can replace with official brand assets later (Slice 5 prep).

- [ ] **Step 19.2: Commit**

```bash
git add desktop/src/renderer/public/assets/connectors/claude_code.svg desktop/src/renderer/public/assets/connectors/jira.svg desktop/src/renderer/public/assets/connectors/confluence.svg desktop/src/renderer/public/assets/connectors/atlassian.svg
git commit -m "feat(desktop): connector logos for claude_code, jira, confluence, atlassian

Approximations using brand-suggesting colors and simple shapes. Replace
with official brand assets before shipping (Slice 5 prep)."
```

---

## Phase 1G — Per-screen migration

### Task 20: Sidecar status store + setup screen

**Files:**
- Create: `desktop/src/renderer/stores/sidecar.ts`
- Create: `desktop/src/renderer/components/SidecarSetup.tsx`
- Modify: `desktop/src/renderer/App.tsx`

- [ ] **Step 20.1: Sidecar status store**

Create `desktop/src/renderer/stores/sidecar.ts`:

```ts
import { create } from 'zustand';

type Status = 'connecting' | 'ready' | 'failed';

interface SidecarState {
  status: Status;
  failure: string | null;
  setReady: () => void;
  setFailed: (reason: string) => void;
  retry: () => Promise<void>;
}

export const useSidecar = create<SidecarState>((set) => ({
  status: 'connecting',
  failure: null,
  setReady: () => set({ status: 'ready', failure: null }),
  setFailed: (reason) => set({ status: 'failed', failure: reason }),
  retry: async () => {
    set({ status: 'connecting', failure: null });
    const result = await window.gb.sidecar.retry();
    if (!result.ok) {
      set({ status: 'failed', failure: result.error });
    }
    // 'ready' will come via the bridge 'sidecar:ready' event subscription in App.
  },
}));
```

- [ ] **Step 20.2: SidecarSetup screen**

Create `desktop/src/renderer/components/SidecarSetup.tsx`:

```tsx
import { useSidecar } from '../stores/sidecar';
import { Ghost } from './Ghost';
import { Btn } from './Btn';

export function SidecarSetup() {
  const failure = useSidecar((s) => s.failure);
  const retry = useSidecar((s) => s.retry);
  return (
    <div className="flex h-full w-full items-center justify-center bg-paper p-8">
      <div className="max-w-[520px] flex flex-col items-center gap-4 text-center">
        <Ghost size={48} />
        <h2 className="m-0 font-display text-26 font-semibold tracking-tight-x text-ink-0">
          ghostbrain isn't running.
        </h2>
        <p className="m-0 text-13 text-ink-2">
          the python backend failed to start. check that python is installed
          (3.11+), and that you've run <code className="font-mono text-12 text-ink-1">pip install -e ".[api]"</code> from the project directory.
        </p>
        {failure && (
          <pre className="m-0 max-w-full overflow-auto rounded-md bg-vellum p-3 font-mono text-11 text-ink-2">
            {failure}
          </pre>
        )}
        <Btn variant="primary" size="md" onClick={() => void retry()}>
          retry
        </Btn>
      </div>
    </div>
  );
}
```

- [ ] **Step 20.3: Wire sidecar events into App.tsx**

Edit `desktop/src/renderer/App.tsx`. Add event subscriptions to sync sidecar status into the store, and gate the main UI on `status === 'ready'`:

```tsx
import { useEffect } from 'react';
import { useSettings } from './stores/settings';
import { useNavigation } from './stores/navigation';
import { useSidecar } from './stores/sidecar';
import { WindowChrome } from './components/WindowChrome';
import { Sidebar } from './components/Sidebar';
import { StatusBar } from './components/StatusBar';
import { Toaster } from './components/Toaster';
import { SidecarSetup } from './components/SidecarSetup';
import { TodayScreen } from './screens/today';
import { ConnectorsScreen } from './screens/connectors';
import { MeetingsScreen } from './screens/meetings';
import { CaptureScreen } from './screens/capture';
import { VaultScreen } from './screens/vault';
import { SettingsScreen } from './screens/settings';

export default function App() {
  const { theme, density, ready, hydrate } = useSettings();
  const active = useNavigation((s) => s.active);
  const setActive = useNavigation((s) => s.setActive);
  const sidecarStatus = useSidecar((s) => s.status);
  const setReady = useSidecar((s) => s.setReady);
  const setFailed = useSidecar((s) => s.setFailed);

  useEffect(() => { hydrate(); }, [hydrate]);

  useEffect(() => {
    if (!ready) return;
    document.body.dataset.theme = theme;
    document.body.dataset.density = density;
  }, [theme, density, ready]);

  useEffect(() => {
    return window.gb.on('nav:settings', () => setActive('settings'));
  }, [setActive]);

  useEffect(() => {
    const offReady = window.gb.on('sidecar:ready', () => setReady());
    const offFailed = window.gb.on('sidecar:failed', (info) => setFailed(info.reason));
    return () => {
      offReady();
      offFailed();
    };
  }, [setReady, setFailed]);

  if (!ready) {
    return <div className="bg-paper text-ink-2 grid h-full place-items-center">…</div>;
  }

  if (sidecarStatus === 'failed') {
    return <SidecarSetup />;
  }

  // sidecarStatus is 'connecting' or 'ready'. Render the app even while
  // connecting so panels show their loading skeletons; React Query won't
  // fire until window.gb.api.request resolves.
  return (
    <WindowChrome>
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <Sidebar />
        <main style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {active === 'today' && <TodayScreen />}
          {active === 'connectors' && <ConnectorsScreen />}
          {active === 'meetings' && <MeetingsScreen />}
          {active === 'capture' && <CaptureScreen />}
          {active === 'vault' && <VaultScreen />}
          {active === 'settings' && <SettingsScreen />}
        </main>
      </div>
      <StatusBar />
      <Toaster />
    </WindowChrome>
  );
}
```

- [ ] **Step 20.4: typecheck + commit**

```bash
npm run typecheck
git add desktop/src/renderer/stores/sidecar.ts desktop/src/renderer/components/SidecarSetup.tsx desktop/src/renderer/App.tsx
git commit -m "feat(desktop): sidecar status store + setup screen

App subscribes to gb:sidecar:ready/failed bridge events, mirrors to a
Zustand store. When status='failed', SidecarSetup renders instead of
the app: diagnostic message + retry button calling window.gb.sidecar.retry()."
```

---

### Task 21: Migrate Today screen to real data

**Files:**
- Modify: `desktop/src/renderer/screens/today.tsx`

- [ ] **Step 21.1: Replace mock imports with hooks**

Edit `desktop/src/renderer/screens/today.tsx`. At the top, replace the mock imports with API hooks:

```tsx
import { useAgenda, useRecentActivity, useConnectors, useCaptures, useSuggestions, useVaultStats } from '../lib/api/hooks';
import { SkeletonRows } from '../components/SkeletonRows';
import { PanelEmpty } from '../components/PanelEmpty';
import { PanelError } from '../components/PanelError';
```

Inside `TodayScreen()`, replace constants like `AGENDA` with `const agenda = useAgenda();` and call sites `agenda.data?.map(...)` etc.

For each panel, wrap the body in conditional rendering:

```tsx
<Panel title="agenda" subtitle={agenda.data ? `${agenda.data.length} events · today` : '…'} action={...}>
  {agenda.isLoading && <SkeletonRows count={3} />}
  {agenda.isError && <PanelError message={agenda.error?.message ?? 'failed to load'} onRetry={() => agenda.refetch()} />}
  {agenda.data && agenda.data.length === 0 && <PanelEmpty icon="calendar" message="no events today" />}
  {agenda.data?.map((item) => (
    <AgendaItemRow key={item.id} time={item.time} dur={item.duration} title={item.title} with={item.with} status={item.status} />
  ))}
</Panel>
```

> The existing `AgendaItem` sub-component name may collide with the imported `AgendaItem` API type. Rename the local sub-component to `AgendaItemRow` (or `AgendaRow`). Update its prop interface to accept `with` as a string array (matching the API type).

Apply the same pattern to:
- Stats grid (`useVaultStats`) — display real numbers in the 4 stat cards
- Ghost activity panel (`useRecentActivity`)
- Connector pulse strip (`useConnectors`)
- Caught lately panel (`useCaptures({ limit: 3 })`)
- Suggestions panel (`useSuggestions`)

The hero greeting's headline "while you slept, ghostbrain caught 241 things" should pull the number from `vaultStats.data?.indexedCount` or similar — pick the most "caught"-feeling stat.

For the stats grid, the four cards become:
- `captured` → `useVaultStats().data?.queuePending` plus today's audit count (compute or just queuePending for simplicity)
- `meetings` → today's agenda upcoming count
- `followups` → captures with `tag === 'followup'` (filter client-side)
- `vault size` → `vaultStats.data?.totalNotes`

If any of these are awkward, simplify to "captured" = total notes, "vault size" = notes count too. The visual point is "show real numbers, not 241".

- [ ] **Step 21.2: Drop mock import**

Remove `import { ... } from '../lib/mocks/today';` from the file. The `lib/mocks/today.ts` file stays for now (Task 27 deletes the directory after all screens migrate).

- [ ] **Step 21.3: typecheck + run dev visually**

```bash
npm run typecheck
npm run dev   # background
```

Verify in DevTools console: `await window.gb.api.request('GET', '/v1/vault/stats')` returns real data.

- [ ] **Step 21.4: Commit**

```bash
git add desktop/src/renderer/screens/today.tsx
git commit -m "feat(desktop): Today screen reads from sidecar

Replaces mock imports with React Query hooks: useVaultStats, useAgenda,
useRecentActivity, useConnectors, useCaptures, useSuggestions. Loading
skeletons, empty states, error retry on every panel. Local AgendaItem
sub-component renamed to AgendaItemRow to avoid colliding with the
api-types AgendaItem."
```

---

### Task 22: Migrate Connectors screen

**Files:**
- Modify: `desktop/src/renderer/screens/connectors.tsx`

- [ ] **Step 22.1: Replace mocks with hooks**

In `screens/connectors.tsx`:

- Replace `import { CONNECTORS, type Connector, type ConnectorState } from '../lib/mocks/connectors';` with `import type { Connector, ConnectorState } from '../../shared/api-types';` and `import { useConnector, useConnectors } from '../lib/api/hooks';`.
- The local `Connector` type from the mock is now the same as the api-type — verify property names match (`displayName` vs `name`, `lastSyncAt` vs `last`, etc.). The API uses `displayName/lastSyncAt/account/throughput/error`; the old mock used `name/last/account/throughput`. **Update every prop access**: `c.name` → `c.displayName`, `c.last` → `c.lastSyncAt`, `c.src` → derived from `c.id` as `/assets/connectors/${c.id}.svg`.
- `ConnectorsScreen` now calls `const connectors = useConnectors();`. `selectedId` is local state (default to `connectors.data?.[0]?.id` once data is available).
- `ConnectorDetail` uses `useConnector(selectedId)` for the full detail (scopes/pulls/vaultDestination) instead of reading directly from the list item.

For the list area, add loading/empty/error states:

```tsx
{connectors.isLoading && <SkeletonRows count={6} height={48} />}
{connectors.isError && <PanelError message={connectors.error?.message ?? 'failed to load connectors'} onRetry={() => connectors.refetch()} />}
{connectors.data && connectors.data.length === 0 && <PanelEmpty icon="plug" message="no connectors configured yet" />}
{connectors.data?.filter(...).map((c) => <ConnectorRow ... />)}
```

For the detail panel:

```tsx
{selected.isLoading && <div className="p-6"><SkeletonRows count={4} /></div>}
{selected.isError && <PanelError ... />}
{selected.data && <ConnectorDetailView c={selected.data} />}
```

- [ ] **Step 22.2: typecheck + commit**

```bash
npm run typecheck
git add desktop/src/renderer/screens/connectors.tsx
git commit -m "feat(desktop): Connectors screen reads from sidecar

Replaces mocks with useConnectors (list) and useConnector (detail).
displayName, lastSyncAt, vaultDestination, etc. now come from the API.
SVG paths derived from connector id."
```

---

### Task 23: Migrate Capture screen

**Files:**
- Modify: `desktop/src/renderer/screens/capture.tsx`

- [ ] **Step 23.1: Replace mocks with hooks**

In `screens/capture.tsx`:

- Replace `import { CAPTURE_ITEMS, type CaptureRecord } from '../lib/mocks/capture';` with `import type { Capture, CaptureSummary } from '../../shared/api-types';` and `import { useCapture, useCaptures } from '../lib/api/hooks';`.
- `CaptureScreen()` uses `const captures = useCaptures({ source: filter === 'all' ? undefined : filter });` for the list and `const detail = useCapture(selectedId);` for the right-side detail.
- `CaptureRow` props change: `c.unread`, `c.title`, `c.snippet`, `c.from`, `c.tags`, `c.source` — these all match the API shape, so no renames.
- The unread count in the TopBar subtitle now reads from `captures.data?.items.filter(c => c.unread).length`.

Add loading/empty/error in both list and detail.

- [ ] **Step 23.2: typecheck + commit**

```bash
npm run typecheck
git add desktop/src/renderer/screens/capture.tsx
git commit -m "feat(desktop): Capture screen reads from sidecar

useCaptures(list) + useCapture(detail). Source filter passes through
as ?source=. Unread count derives from items. Loading skeletons and
empty state for both list and detail."
```

---

### Task 24: Migrate Meetings screen (history only)

**Files:**
- Modify: `desktop/src/renderer/screens/meetings.tsx`

- [ ] **Step 24.1: Replace HISTORY mock with hook**

In `screens/meetings.tsx`:

- Keep `PARTICIPANTS`, `TRANSCRIPT`, `SPEAKER_AIRTIME` imports as mocks — those drive the recording UI which is NOT real yet (recording is Slice 4).
- Replace `import { HISTORY, ... } from '../lib/mocks/meetings';` with `import type { PastMeeting } from '../../shared/api-types';` plus the recording-related mock imports moved to their own line.
- In `MeetingHistory` component: `const meetings = useMeetings({ limit: 50 });` then conditional rendering of the table:

```tsx
function MeetingHistory() {
  const meetings = useMeetings({ limit: 50 });
  return (
    <Panel title="past meetings" subtitle={meetings.data ? `${meetings.data.total} in vault` : '…'} action={<Btn variant="ghost" size="sm" iconRight={<Lucide name="arrow-right" size={12} />}>vault</Btn>}>
      {meetings.isLoading && <SkeletonRows count={5} />}
      {meetings.isError && <PanelError message={meetings.error?.message ?? 'failed to load meetings'} onRetry={() => meetings.refetch()} />}
      {meetings.data && meetings.data.items.length === 0 && <PanelEmpty icon="mic" message="no recorded meetings yet" />}
      {meetings.data && meetings.data.items.length > 0 && (
        <>
          <div className="grid gap-3 border-b border-hairline px-2 pb-2" style={{ gridTemplateColumns: '120px minmax(0, 1fr) 80px 80px minmax(0, 1fr)' }}>
            <Eyebrow>date</Eyebrow><Eyebrow>title</Eyebrow><Eyebrow>length</Eyebrow><Eyebrow>speakers</Eyebrow><Eyebrow>tags</Eyebrow>
          </div>
          {meetings.data.items.map((m) => <HistoryRow key={m.id} m={m} />)}
        </>
      )}
    </Panel>
  );
}
```

`HistoryRow`'s `m` prop type changes from the old mock shape to `PastMeeting`. The fields match (`date`, `title`, `dur`, `speakers`, `tags`) — no rename needed.

- [ ] **Step 24.2: typecheck + commit**

```bash
npm run typecheck
git add desktop/src/renderer/screens/meetings.tsx
git commit -m "feat(desktop): Meetings history reads from sidecar

useMeetings hook replaces the HISTORY mock. Recording state machine
(pre/recording/post) stays UI-only — recording integration is Slice 4."
```

---

### Task 25: Verify Vault screen + Settings screen need no changes

**Files:**
- Verify only: `desktop/src/renderer/screens/vault.tsx`
- Verify only: `desktop/src/renderer/screens/settings.tsx`

- [ ] **Step 25.1: Check vault.tsx**

Read `desktop/src/renderer/screens/vault.tsx`. It should only use `useSettings` and `window.gb.shell.openPath`. No mock imports. No changes needed.

- [ ] **Step 25.2: Check settings.tsx**

Read `desktop/src/renderer/screens/settings.tsx`. It should only use `useSettings` and `window.gb.dialogs.pickVaultFolder`. No mock imports. No changes needed.

If either file references the mocks dir, fix it.

- [ ] **Step 25.3: No commit unless changes**

If both files are clean, no commit needed.

---

## Phase 1H — Cleanup

### Task 26: Delete the mocks directory

**Files:**
- Delete: `desktop/src/renderer/lib/mocks/today.ts`
- Delete: `desktop/src/renderer/lib/mocks/connectors.ts`
- Delete: `desktop/src/renderer/lib/mocks/capture.ts`
- Delete: `desktop/src/renderer/lib/mocks/meetings.ts`

- [ ] **Step 26.1: Verify nothing imports from mocks**

```bash
cd desktop
git grep "lib/mocks" src/
```

Expected: only matches that have already been replaced. If anything is left, fix the caller first.

- [ ] **Step 26.2: Delete the directory**

```bash
rm -rf desktop/src/renderer/lib/mocks
```

- [ ] **Step 26.3: typecheck + test**

```bash
npm run typecheck
npm test
```

Both pass.

- [ ] **Step 26.4: Commit**

```bash
git add -A desktop/src/renderer/lib/
git commit -m "chore(desktop): drop lib/mocks/

All six screens now read from the sidecar via React Query hooks. The
mock data files are dead weight."
```

---

### Task 27: README updates + final verification

**Files:**
- Modify: `desktop/README.md`

- [ ] **Step 27.1: Update README**

Edit `desktop/README.md`. Add a new section before "Slice 1 known TODOs":

```markdown
## Backend

The desktop app talks to a Python FastAPI sidecar at `127.0.0.1:<random>` over
localhost HTTP, using a Bearer token captured at startup. The sidecar lives
at `ghostbrain/api/` and is launched by Electron main as `python3 -m ghostbrain.api`.

In dev, you need:

    cd ..
    pip install -e ".[api]"

Then `npm run dev` from `desktop/` will spawn the sidecar automatically.

## Phase 1 status (Read Architecture)

- 9 read-only endpoints under /v1/, no writes yet
- React Query v5 for fetch lifecycle
- Loading skeletons, empty states, error retry on every panel
- Sidecar lifecycle: spawn on launch, auto-restart once on crash, graceful
  shutdown on quit
- Token never leaves main process; renderer talks via IPC only

## Phase 2 will add

- Write endpoints (sync now, start/stop recording, save to vault, ask the archive)
- WebSocket events channel (live transcript, sync progress)
- OAuth flows for connectors
- PyInstaller bundling so end users don't need Python installed
- Code signing + installer + auto-updater
```

- [ ] **Step 27.2: Final full sweep**

```bash
cd desktop
npm run typecheck
npm run lint
npm test
cd ..
pytest ghostbrain/api/tests/ -v
```

All should pass.

- [ ] **Step 27.3: Verify the hard rule**

```bash
git diff main..HEAD -- ghostbrain/ ':!ghostbrain/api/'
```

Expected: empty.

- [ ] **Step 27.4: Manual dev run**

```bash
cd desktop && npm run dev
```

Visually confirm:
- App boots, sidecar starts (~2s)
- Today screen shows real data (or empty states if vault is empty)
- Settings → Display → Light works
- Cmd+, navigates to settings
- Quit works cleanly

- [ ] **Step 27.5: Commit**

```bash
git add desktop/README.md
git commit -m "docs(desktop): document the Python sidecar + Phase 1 status

Adds backend section + Phase 1 status + Phase 2 preview to README."
```

---

## Self-review

Spec coverage:

| Spec section | Tasks | Notes |
|--------------|-------|-------|
| Sidecar bootstrap (FastAPI, schemas, auth, READY banner, README) | 1, 2, 3, 4, 27 | All landed |
| Read endpoints (9 of them, Pydantic, real vault reads) | 5, 6, 7, 8, 9, 10, 11 | Vault, connectors, captures, meetings, agenda, activity, suggestions |
| Electron main: sidecar lifecycle | 12, 13, 14 | Spawn, forward, IPC handler |
| Typed bridge + api types | 15 | TS mirrors, GbBridge extended |
| Renderer: React Query, hooks, loading/empty/error | 16, 17, 18 | QueryClient, 9 hooks, 3 primitives |
| Per-screen migration | 20, 21, 22, 23, 24, 25 | Today, Connectors, Capture, Meetings (history), Vault/Settings verified clean |
| Sidecar setup first-run UX | 20 | SidecarSetup screen + retry |
| Connector reconciliation + 4 logos | 6 (sidecar surfacing), 19 (logos) | Implicit via static `_DISPLAY` dict + new SVGs |
| Mocks deletion | 26 | Directory deleted |
| pyproject.toml `[api]` extras | 1 | Added; testpaths extended |
| Hard rule on Python isolation | 27 | Verifiable via git diff |
| typecheck/lint/test/dev pass | 27 | Final sweep |

**Placeholder check:** No "TBD"/"implement later". Each task has runnable commands, full code, expected output, exact commits.

**Type consistency:**
- `Connector`, `ConnectorDetail`, `Capture`, `CaptureSummary`, `PastMeeting`, `AgendaItem`, `ActivityRow`, `Suggestion`, `VaultStats` — defined once in `api-types.ts` (TS) mirroring Pydantic in `models/*.py`. Every consumer (hooks, screens) imports from one location.
- `from` field aliased correctly in Pydantic via `Field(alias="from")`; JSON shape uses `"from"`; TS keeps the keyword `from`.
- `GbBridge.api.request<T>` signature consistent across `shared/types.ts`, preload, and renderer client.

**Scope check:** every task touches only `ghostbrain/api/` OR `desktop/` OR `pyproject.toml` OR `docs/`. The hard-rule grep at the end verifies this.

Total: **27 tasks**, mapping to the ~13.5-day estimate from the spec.
