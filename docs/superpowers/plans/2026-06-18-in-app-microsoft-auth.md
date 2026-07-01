# In-App Microsoft Sign-In Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sign in to Microsoft Graph from inside the Poltergeist desktop app with a seamless, no-code system-browser flow, authorizing all Microsoft connectors in one click.

**Architecture:** The Python sidecar drives MSAL `acquire_token_interactive` (system browser + ephemeral localhost loopback) on a background thread, exposing start/status/disconnect over the existing local HTTP API. The renderer triggers the flow and polls status; a Settings card shows connection state. Token handling stays entirely in MSAL's existing shared encrypted cache.

**Tech Stack:** Python 3 / FastAPI / MSAL (`msal`, `msal-extensions`) on the sidecar; React + TypeScript + `@tanstack/react-query` + Vitest in the Electron renderer. Pytest for Python.

## Global Constraints

- Interactive flow runs in the **Python sidecar**, reusing `_build_app`, `resolve_scopes`, `have_token`, `cache_location` from `ghostbrain/connectors/microsoft/graph/auth.py`. No OAuth in the Electron main process.
- Scopes come from `resolve_scopes(config)`; the union default in `auth.py` `SCOPES` is `Mail.Read, Chat.Read, Calendars.Read, OnlineMeetings.Read, OnlineMeetingTranscript.Read.All`.
- MSAL must never be invoked for real in tests — always inject a fake app (`app_factory`) or monkeypatch `have_token`.
- Renderer talks to the sidecar only via `get`/`post` from `desktop/src/renderer/lib/api/client.ts` (which routes through `window.gb.api.request`). No new preload/main changes.
- Auth state vocabulary is exactly `"idle" | "pending" | "connected" | "error"` on both sides.
- The headless `ghostbrain-microsoft-auth` CLI stays; do not remove or modify it.

---

### Task 1: `InteractiveAuth` holder (sidecar)

**Files:**
- Create: `ghostbrain/connectors/microsoft/graph/interactive_auth.py`
- Test: `tests/test_microsoft_interactive_auth.py`

**Interfaces:**
- Consumes: `_build_app(config) -> msal.PublicClientApplication`, `resolve_scopes(config) -> list[str]`, `have_token(config) -> bool`, `cache_location() -> Path` (all from `ghostbrain.connectors.microsoft.graph.auth`).
- Produces:
  - `AuthState(state: str, account: str | None = None, error: str | None = None)` dataclass.
  - `class AlreadyRunning(RuntimeError)`.
  - `class InteractiveAuth(app_factory=_build_app)` with `start(config: dict) -> None`, `status(config: dict) -> AuthState`, `disconnect(config: dict) -> None`, and `wait()` (test helper that joins the worker thread).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_microsoft_interactive_auth.py
"""InteractiveAuth holder. MSAL app is injected; no real browser/network."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from ghostbrain.connectors.microsoft.graph.interactive_auth import (
    AlreadyRunning,
    AuthState,
    InteractiveAuth,
)

CFG = {"client_id": "c", "tenant_id": "t"}


def _fake_app(*, token=True, accounts=("me@tenant",), error=None):
    app = MagicMock()
    app.acquire_token_interactive.return_value = (
        {"access_token": "x"} if token else {"error": "access_denied",
                                             "error_description": error or "denied"}
    )
    app.get_accounts.return_value = [{"username": u} for u in accounts]
    return app


def test_start_then_connected_sets_account(monkeypatch):
    app = _fake_app()
    auth = InteractiveAuth(app_factory=lambda cfg: app)
    auth.start(CFG)
    auth.wait()
    monkeypatch.setattr(
        "ghostbrain.connectors.microsoft.graph.interactive_auth.have_token",
        lambda cfg: True,
    )
    st = auth.status(CFG)
    assert st == AuthState(state="connected", account="me@tenant")


def test_failed_signin_maps_to_error(monkeypatch):
    app = _fake_app(token=False, error="consent required")
    auth = InteractiveAuth(app_factory=lambda cfg: app)
    auth.start(CFG)
    auth.wait()
    st = auth.status(CFG)
    assert st.state == "error"
    assert "consent required" in st.error


def test_second_start_while_running_raises(monkeypatch):
    import threading

    gate = threading.Event()
    app = MagicMock()
    app.acquire_token_interactive.side_effect = lambda *a, **k: (gate.wait(2)
                                                                 or {"access_token": "x"})
    app.get_accounts.return_value = [{"username": "me@tenant"}]
    auth = InteractiveAuth(app_factory=lambda cfg: app)
    auth.start(CFG)
    try:
        with pytest.raises(AlreadyRunning):
            auth.start(CFG)
    finally:
        gate.set()
        auth.wait()


def test_status_idle_when_no_flow_and_no_token(monkeypatch):
    auth = InteractiveAuth(app_factory=lambda cfg: _fake_app())
    monkeypatch.setattr(
        "ghostbrain.connectors.microsoft.graph.interactive_auth.have_token",
        lambda cfg: False,
    )
    assert auth.status(CFG) == AuthState(state="idle")


def test_disconnect_removes_accounts_and_clears_cache(tmp_path, monkeypatch):
    app = _fake_app()
    cache = tmp_path / "token_cache.bin"
    cache.write_text("blob")
    monkeypatch.setattr(
        "ghostbrain.connectors.microsoft.graph.interactive_auth.cache_location",
        lambda: cache,
    )
    monkeypatch.setattr(
        "ghostbrain.connectors.microsoft.graph.interactive_auth.have_token",
        lambda cfg: False,
    )
    auth = InteractiveAuth(app_factory=lambda cfg: app)
    auth.disconnect(CFG)
    app.remove_account.assert_called_once()
    assert not cache.exists()
    assert auth.status(CFG).state == "idle"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_microsoft_interactive_auth.py -v`
Expected: FAIL with `ModuleNotFoundError: ghostbrain.connectors.microsoft.graph.interactive_auth`.

- [ ] **Step 3: Write minimal implementation**

```python
# ghostbrain/connectors/microsoft/graph/interactive_auth.py
"""Drives the MSAL interactive (system-browser loopback) sign-in from the
sidecar, exposing observable state so the desktop UI can trigger + poll it.

One process-singleton holder runs the blocking MSAL call on a worker thread.
The MSAL PublicClientApplication is injectable so tests never open a browser."""
from __future__ import annotations

import threading
from dataclasses import dataclass

from ghostbrain.connectors.microsoft.graph.auth import (
    _build_app,
    cache_location,
    have_token,
    resolve_scopes,
)


@dataclass
class AuthState:
    state: str  # "idle" | "pending" | "connected" | "error"
    account: str | None = None
    error: str | None = None


class AlreadyRunning(RuntimeError):
    """Raised when start() is called while a sign-in is already in flight."""


def _result_error(result: dict) -> str:
    return (
        result.get("error_description")
        or result.get("error")
        or "Microsoft sign-in failed."
    )


class InteractiveAuth:
    def __init__(self, app_factory=_build_app) -> None:
        self._app_factory = app_factory
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state = AuthState(state="idle")

    def start(self, config: dict) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                raise AlreadyRunning("a Microsoft sign-in is already in progress")
            self._state = AuthState(state="pending")
            self._thread = threading.Thread(
                target=self._run, args=(config,), daemon=True
            )
            self._thread.start()

    def _run(self, config: dict) -> None:
        try:
            app = self._app_factory(config)
            result = app.acquire_token_interactive(
                resolve_scopes(config), prompt="select_account"
            )
            if "access_token" not in result:
                self._set(AuthState(state="error", error=_result_error(result)))
                return
            accounts = app.get_accounts()
            username = accounts[0].get("username") if accounts else None
            self._set(AuthState(state="connected", account=username))
        except Exception as e:  # noqa: BLE001
            self._set(AuthState(state="error", error=str(e) or "Sign-in failed."))

    def _set(self, state: AuthState) -> None:
        with self._lock:
            self._state = state

    def _running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self, config: dict) -> AuthState:
        with self._lock:
            running = self._running()
            snapshot = self._state
        if running or snapshot.state == "error":
            return snapshot
        if have_token(config):
            account = snapshot.account or self._account(config)
            return AuthState(state="connected", account=account)
        return AuthState(state="idle")

    def _account(self, config: dict) -> str | None:
        try:
            accounts = self._app_factory(config).get_accounts()
        except Exception:  # noqa: BLE001
            return None
        return accounts[0].get("username") if accounts else None

    def disconnect(self, config: dict) -> None:
        try:
            app = self._app_factory(config)
            for acct in app.get_accounts():
                app.remove_account(acct)
        except Exception:  # noqa: BLE001
            pass
        try:
            cache_location().unlink(missing_ok=True)
        except OSError:
            pass
        self._set(AuthState(state="idle"))

    def wait(self, timeout: float = 5.0) -> None:
        """Test helper: join the worker thread if one is running."""
        t = self._thread
        if t is not None:
            t.join(timeout)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_microsoft_interactive_auth.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/connectors/microsoft/graph/interactive_auth.py tests/test_microsoft_interactive_auth.py
git commit -m "feat(auth): InteractiveAuth holder for MSAL system-browser sign-in"
```

---

### Task 2: Auth API routes + wiring

**Files:**
- Create: `ghostbrain/api/routes/ms_auth.py`
- Modify: `ghostbrain/api/main.py` (add import + `include_router`)
- Test: `ghostbrain/api/tests/test_ms_auth_routes.py`

**Interfaces:**
- Consumes: `InteractiveAuth`, `AlreadyRunning`, `AuthState` (Task 1); `load_routing()` from `ghostbrain.connectors._runner`.
- Produces: router at prefix `/v1/connectors/microsoft/auth` with `POST /start`, `GET /status`, `POST /disconnect`. The `InteractiveAuth` singleton lives on `request.app.state.ms_auth`.

- [ ] **Step 1: Write the failing tests**

```python
# ghostbrain/api/tests/test_ms_auth_routes.py
from __future__ import annotations

from ghostbrain.connectors.microsoft.graph.interactive_auth import AuthState


def _install_fake_holder(client, *, status_state, started=None):
    """Replace the route's holder with a stub on the live app.state."""
    app = client.app

    class Holder:
        def __init__(self):
            self.started = False

        def start(self, config):
            self.started = True
            if started == "already":
                from ghostbrain.connectors.microsoft.graph.interactive_auth import (
                    AlreadyRunning,
                )
                raise AlreadyRunning("already")

        def status(self, config):
            return status_state

        def disconnect(self, config):
            self.disconnected = True

    holder = Holder()
    app.state.ms_auth = holder
    return holder


def test_status_reports_connected(client, auth_headers):
    _install_fake_holder(client, status_state=AuthState("connected", "me@tenant"))
    r = client.get("/v1/connectors/microsoft/auth/status", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"state": "connected", "account": "me@tenant", "error": None}


def test_start_returns_pending(client, auth_headers):
    h = _install_fake_holder(client, status_state=AuthState("pending"))
    r = client.post("/v1/connectors/microsoft/auth/start", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["state"] == "pending"
    assert h.started is True


def test_start_conflict_when_already_running(client, auth_headers):
    _install_fake_holder(client, status_state=AuthState("pending"), started="already")
    r = client.post("/v1/connectors/microsoft/auth/start", headers=auth_headers)
    assert r.status_code == 409


def test_disconnect_resets(client, auth_headers):
    h = _install_fake_holder(client, status_state=AuthState("idle"))
    r = client.post("/v1/connectors/microsoft/auth/disconnect", headers=auth_headers)
    assert r.status_code == 200
    assert r.json() == {"state": "idle"}
    assert getattr(h, "disconnected", False) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest ghostbrain/api/tests/test_ms_auth_routes.py -v`
Expected: FAIL with `404` (route not registered) on every test.

- [ ] **Step 3: Write the route module**

```python
# ghostbrain/api/routes/ms_auth.py
"""POST /start, GET /status, POST /disconnect for Microsoft interactive sign-in.

The MSAL flow runs in the sidecar; the renderer triggers + polls these. A single
InteractiveAuth instance is held on app.state so /start and /status share it."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ghostbrain.connectors._runner import load_routing
from ghostbrain.connectors.microsoft.graph.interactive_auth import (
    AlreadyRunning,
    InteractiveAuth,
)

router = APIRouter(prefix="/v1/connectors/microsoft/auth", tags=["microsoft-auth"])


def _holder(request: Request) -> InteractiveAuth:
    holder = getattr(request.app.state, "ms_auth", None)
    if holder is None:
        holder = InteractiveAuth()
        request.app.state.ms_auth = holder
    return holder


def _config() -> dict:
    return load_routing().get("microsoft") or {}


@router.post("/start")
def start(request: Request) -> dict:
    try:
        _holder(request).start(_config())
    except AlreadyRunning as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"state": "pending"}


@router.get("/status")
def status(request: Request) -> dict:
    st = _holder(request).status(_config())
    return {"state": st.state, "account": st.account, "error": st.error}


@router.post("/disconnect")
def disconnect(request: Request) -> dict:
    _holder(request).disconnect(_config())
    return {"state": "idle"}
```

- [ ] **Step 4: Wire the router into the app**

In `ghostbrain/api/main.py`, add the import alongside the other route imports (after line 18, `meetings as meetings_routes`):

```python
from ghostbrain.api.routes import ms_auth as ms_auth_routes
```

And inside `create_app`, after `app.include_router(connectors_routes.router)` (line 34):

```python
    app.include_router(ms_auth_routes.router)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest ghostbrain/api/tests/test_ms_auth_routes.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Commit**

```bash
git add ghostbrain/api/routes/ms_auth.py ghostbrain/api/main.py ghostbrain/api/tests/test_ms_auth_routes.py
git commit -m "feat(auth): /v1/connectors/microsoft/auth start|status|disconnect routes"
```

---

### Task 3: Widen scopes in routing config

**Files:**
- Modify: `~/ghostbrain/vault/90-meta/routing.yaml` (user vault — not in repo)

**Interfaces:** none (operational config change). After this, `resolve_scopes` returns the full `SCOPES` union, so one sign-in authorizes meetings + chat + mail.

- [ ] **Step 1: Remove the `microsoft.scopes` override**

Delete the entire `scopes:` block under `microsoft:` in `~/ghostbrain/vault/90-meta/routing.yaml` (the three/four lines listing `OnlineMeetings.Read`, `OnlineMeetingTranscript.Read.All`, `Calendars.Read`). Leave `client_id`, `tenant_id`, and the per-connector blocks intact. With no override, `resolve_scopes` falls back to the `SCOPES` union in `auth.py`.

- [ ] **Step 2: Verify it parses and resolves to the union**

Run:
```bash
python3 - <<'PY'
import yaml
from ghostbrain.connectors.microsoft.graph.auth import resolve_scopes, SCOPES
ms = yaml.safe_load(open('/Users/jannik/ghostbrain/vault/90-meta/routing.yaml'))['microsoft']
assert ms.get('scopes') is None, "scopes override still present"
assert resolve_scopes(ms) == SCOPES, resolve_scopes(ms)
print("OK union:", resolve_scopes(ms))
PY
```
Expected: `OK union: ['Mail.Read', 'Chat.Read', 'Calendars.Read', 'OnlineMeetings.Read', 'OnlineMeetingTranscript.Read.All']`

- [ ] **Step 3: Commit** — none (vault is not under repo version control). Note completion in the task tracker.

---

### Task 4: Renderer types + React Query hooks

**Files:**
- Modify: `desktop/src/shared/api-types.ts` (append types)
- Modify: `desktop/src/renderer/lib/api/hooks.ts` (append hooks + import)
- Test: `desktop/src/renderer/__tests__/microsoft-auth-hooks.test.tsx`

**Interfaces:**
- Consumes: `get`, `post` from `../lib/api/client`; routes from Task 2.
- Produces:
  - Type `MicrosoftAuthStatus { state: 'idle'|'pending'|'connected'|'error'; account: string | null; error: string | null }`.
  - `useMicrosoftAuthStatus()` (query, polls every 1s while `state === 'pending'`).
  - `useStartMicrosoftAuth()` (mutation → POST `/start`).
  - `useDisconnectMicrosoft()` (mutation → POST `/disconnect`).

- [ ] **Step 1: Write the failing test**

```tsx
// desktop/src/renderer/__tests__/microsoft-auth-hooks.test.tsx
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { useMicrosoftAuthStatus, useStartMicrosoftAuth } from '../lib/api/hooks';

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

describe('microsoft auth hooks', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('fetches status', async () => {
    vi.spyOn(client, 'get').mockResolvedValue({
      state: 'connected', account: 'me@tenant', error: null,
    });
    const { result } = renderHook(() => useMicrosoftAuthStatus(), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.data?.state).toBe('connected'));
    expect(result.current.data?.account).toBe('me@tenant');
  });

  it('start posts to the start endpoint', async () => {
    const post = vi.spyOn(client, 'post').mockResolvedValue({ state: 'pending' });
    const { result } = renderHook(() => useStartMicrosoftAuth(), { wrapper: wrapper() });
    await result.current.mutateAsync();
    expect(post).toHaveBeenCalledWith('/v1/connectors/microsoft/auth/start');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/microsoft-auth-hooks.test.tsx`
Expected: FAIL — `useMicrosoftAuthStatus`/`useStartMicrosoftAuth` not exported.

- [ ] **Step 3: Add the type**

Append to `desktop/src/shared/api-types.ts`:

```typescript
export type MicrosoftAuthPhase = 'idle' | 'pending' | 'connected' | 'error';

export interface MicrosoftAuthStatus {
  state: MicrosoftAuthPhase;
  account: string | null;
  error: string | null;
}
```

- [ ] **Step 4: Add the hooks**

In `desktop/src/renderer/lib/api/hooks.ts`, add `MicrosoftAuthStatus` to the existing type import block (the `import type { ... }` that already lists `Connector, ConnectorDetail`), then append:

```typescript
export function useMicrosoftAuthStatus() {
  return useQuery({
    queryKey: ['microsoft', 'auth', 'status'],
    queryFn: () => get<MicrosoftAuthStatus>('/v1/connectors/microsoft/auth/status'),
    refetchInterval: (query) =>
      query.state.data?.state === 'pending' ? 1_000 : false,
    staleTime: 0,
  });
}

export function useStartMicrosoftAuth() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => post<{ state: string }>('/v1/connectors/microsoft/auth/start'),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: ['microsoft', 'auth', 'status'] }),
  });
}

export function useDisconnectMicrosoft() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => post<{ state: string }>('/v1/connectors/microsoft/auth/disconnect'),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['microsoft', 'auth', 'status'] });
      qc.invalidateQueries({ queryKey: ['connectors'] });
    },
  });
}
```

Confirm `get`, `post`, `useQuery`, `useMutation`, `useQueryClient` are already imported at the top of the file (they are — used by existing hooks).

- [ ] **Step 5: Run test to verify it passes**

Run: `cd desktop && npx vitest run src/renderer/__tests__/microsoft-auth-hooks.test.tsx`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add desktop/src/shared/api-types.ts desktop/src/renderer/lib/api/hooks.ts desktop/src/renderer/__tests__/microsoft-auth-hooks.test.tsx
git commit -m "feat(auth): renderer hooks for microsoft sign-in status/start/disconnect"
```

---

### Task 5: Microsoft connect card + Settings integration

**Files:**
- Create: `desktop/src/renderer/components/MicrosoftConnectCard.tsx`
- Modify: `desktop/src/renderer/screens/settings.tsx` (render the card in the connectors/background area)
- Test: `desktop/src/renderer/__tests__/MicrosoftConnectCard.test.tsx`

**Interfaces:**
- Consumes: `useMicrosoftAuthStatus`, `useStartMicrosoftAuth`, `useDisconnectMicrosoft` (Task 4).
- Produces: `<MicrosoftConnectCard />` default export — presentational card.

- [ ] **Step 1: Write the failing test**

```tsx
// desktop/src/renderer/__tests__/MicrosoftConnectCard.test.tsx
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import * as hooks from '../lib/api/hooks';
import MicrosoftConnectCard from '../components/MicrosoftConnectCard';

function stubStatus(data: { state: string; account: string | null; error: string | null }) {
  vi.spyOn(hooks, 'useMicrosoftAuthStatus').mockReturnValue({ data } as never);
}

describe('MicrosoftConnectCard', () => {
  const start = vi.fn().mockResolvedValue({ state: 'pending' });
  const disconnect = vi.fn().mockResolvedValue({ state: 'idle' });

  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(hooks, 'useStartMicrosoftAuth').mockReturnValue({ mutateAsync: start } as never);
    vi.spyOn(hooks, 'useDisconnectMicrosoft').mockReturnValue({ mutateAsync: disconnect } as never);
  });

  it('shows connected account', () => {
    stubStatus({ state: 'connected', account: 'me@tenant', error: null });
    render(<MicrosoftConnectCard />);
    expect(screen.getByText(/me@tenant/)).toBeInTheDocument();
  });

  it('connect button triggers start when not connected', () => {
    stubStatus({ state: 'idle', account: null, error: null });
    render(<MicrosoftConnectCard />);
    fireEvent.click(screen.getByRole('button', { name: /connect microsoft/i }));
    expect(start).toHaveBeenCalled();
  });

  it('renders the error message', () => {
    stubStatus({ state: 'error', account: null, error: 'consent denied' });
    render(<MicrosoftConnectCard />);
    expect(screen.getByText(/consent denied/)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd desktop && npx vitest run src/renderer/__tests__/MicrosoftConnectCard.test.tsx`
Expected: FAIL — cannot find `../components/MicrosoftConnectCard`.

- [ ] **Step 3: Write the component**

```tsx
// desktop/src/renderer/components/MicrosoftConnectCard.tsx
import {
  useDisconnectMicrosoft,
  useMicrosoftAuthStatus,
  useStartMicrosoftAuth,
} from '../lib/api/hooks';

export default function MicrosoftConnectCard() {
  const status = useMicrosoftAuthStatus();
  const start = useStartMicrosoftAuth();
  const disconnect = useDisconnectMicrosoft();

  const state = status.data?.state ?? 'idle';
  const account = status.data?.account ?? null;
  const error = status.data?.error ?? null;
  const pending = state === 'pending';

  return (
    <div className="mb-4 rounded-r6 border border-ink-4/40 p-3">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-12 font-medium text-ink-1">Microsoft 365</div>
          <div className="mt-[2px] text-11 text-ink-2">
            {state === 'connected' && account
              ? `Connected as ${account}`
              : pending
                ? 'Waiting for sign-in in your browser…'
                : 'Not connected'}
          </div>
        </div>
        {state === 'connected' ? (
          <button
            className="text-11 text-ink-2 underline"
            onClick={() => void disconnect.mutateAsync()}
          >
            Disconnect
          </button>
        ) : (
          <button
            className="rounded-r6 bg-ink-1 px-3 py-1 text-11 text-paper disabled:opacity-50"
            disabled={pending}
            onClick={() => void start.mutateAsync()}
          >
            {pending ? 'Signing in…' : state === 'error' ? 'Retry' : 'Connect Microsoft'}
          </button>
        )}
      </div>
      {error ? (
        <div className="mt-2 text-11 text-oxblood">{error}</div>
      ) : null}
    </div>
  );
}
```

(Class names mirror existing Settings cards — `rounded-r6`, `text-ink-*`, `text-oxblood`, `bg-ink-1`. If a token differs in this codebase, match the nearest existing card in `settings.tsx`.)

- [ ] **Step 4: Render it in Settings**

In `desktop/src/renderer/screens/settings.tsx`, import at the top:

```typescript
import MicrosoftConnectCard from '../components/MicrosoftConnectCard';
```

Render `<MicrosoftConnectCard />` inside the `BackgroundSettings` component (the connectors/scheduler section), immediately after its `<SectionHeader title="background" … />` element.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd desktop && npx vitest run src/renderer/__tests__/MicrosoftConnectCard.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add desktop/src/renderer/components/MicrosoftConnectCard.tsx desktop/src/renderer/screens/settings.tsx desktop/src/renderer/__tests__/MicrosoftConnectCard.test.tsx
git commit -m "feat(auth): Microsoft connect card in Settings"
```

---

### Task 6: Azure registration + end-to-end verification (runbook)

**Files:**
- Modify: `docs/superpowers/specs/2026-06-18-in-app-microsoft-auth-design.md` (only if steps change) — otherwise none.

**Interfaces:** none. This task makes the seamless flow actually work and proves it.

- [ ] **Step 1: Update the Azure app registration**

In Entra ID → App registrations → the app (`client_id` from routing.yaml) → **Authentication**:
- Under **Mobile and desktop applications**, add redirect URI **`http://localhost`**.
- Under **Advanced settings**, set **Allow public client flows = Yes**.
- Save.

- [ ] **Step 2: Confirm consent covers the union**

Ensure the app has (admin or user) consent for `Mail.Read`, `Chat.Read`, `Calendars.Read`, `OnlineMeetings.Read`, `OnlineMeetingTranscript.Read.All`. If `Mail.Read` is not consented, either grant it or temporarily keep a narrowed `microsoft.scopes` in routing.yaml that omits it (re-adding Task 3's removal partially) — the combined interactive sign-in fails if any requested scope lacks consent.

- [ ] **Step 3: Verify the full flow in the app**

1. Launch the desktop app (with the sidecar). In Settings → background, the card shows **Not connected**.
2. Click **Connect Microsoft** → system browser opens → sign in → card flips to **Connected as you@tenant** (within a couple of poll cycles).
3. Confirm the token cache is non-empty: `ls -la ~/.ghostbrain/state/microsoft/token_cache.bin` shows a non-zero size.
4. From the connectors UI, trigger a `teams_meetings` sync (POST `/v1/connectors/teams_meetings/sync`), then confirm a transcript landed: `ls ~/.ghostbrain/queue/pending | grep teams`.
5. Click **Disconnect** → card returns to **Not connected**; token cache cleared.

- [ ] **Step 4: Commit** — none unless docs changed. Record completion in the task tracker.

---

## Self-Review

**Spec coverage:**
- Seamless interactive flow in sidecar → Task 1. ✓
- API start/status/disconnect → Task 2. ✓
- Scope union via routing.yaml → Task 3. ✓
- Azure redirect URI + public-client flows → Task 6. ✓
- Settings card (connected/not-connected/error/retry, disconnect) → Task 5. ✓
- Hooks + types → Task 4. ✓
- `status` reflects `have_token` when idle → Task 1 (`test_status_idle_*`) + status() logic. ✓
- Single-flight `409` → Task 1 (`AlreadyRunning`) + Task 2 (409 test). ✓
- TDD on every code task; CLI fallback untouched (no task modifies it). ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. The one judgment note (Tailwind token names in Task 5) instructs matching the nearest existing card rather than leaving a blank.

**Type consistency:** `AuthState(state, account, error)` and the `{state, account, error}` JSON match the renderer `MicrosoftAuthStatus` shape; state vocabulary `idle|pending|connected|error` is identical across Python, route JSON, TS type, and component. Hook names (`useMicrosoftAuthStatus`, `useStartMicrosoftAuth`, `useDisconnectMicrosoft`) are referenced identically in Tasks 4 and 5.
