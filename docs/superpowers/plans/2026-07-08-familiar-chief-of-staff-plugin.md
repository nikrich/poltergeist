# Familiar — Chief-of-Staff Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A first-party plugin (`plugins/familiar/`) that runs a weekly LLM sweep over vault deltas, maintains rolling memory + open-loop/decision tracker notes, and renders briefings in a plugin screen — plus the two core capabilities it needs: an `api.fetch` plugin bridge and `POST /v1/llm/run` / `PUT /v1/notes` sidecar endpoints.

**Architecture:** The plugin is the agent: `main.cjs` owns the timer and the sweep pipeline, calling the Python sidecar over the new raw-passthrough bridge (`ctx.api.fetch` in main, `api.fetch` via host IPC in the renderer, both riding `api-forwarder.ts`). All output is real vault notes under `Familiar/`; the renderer screen reads/edits those notes. Pure logic (scheduling, delta, budget, trackers, prompt, output parsing, sweep orchestration) lives in `plugins/familiar/src/lib/*` as dependency-injected modules with vitest coverage; `main.js`/`renderer.js` are thin wiring.

**Tech Stack:** Python FastAPI sidecar (pytest), Electron main/preload TS (vitest), plugin: plain JS bundled with esbuild (vitest for lib), `marked` bundled for markdown rendering.

**Spec:** `docs/superpowers/specs/2026-07-08-familiar-chief-of-staff-plugin-design.md`

## Global Constraints

- Plugin id `familiar`, icon `ghost`, `apiVersion: 1`; manifest must satisfy the existing zod `manifestSchema`.
- Plugins ship pre-built: `dist/main.cjs` (CJS) and `dist/renderer.mjs` (ESM) are committed; install never runs npm.
- Plugin errors must never crash the app: activate failures → `errored`; IPC handler throws reject only that call.
- All sweep output lives under `Familiar/` in the vault; delta assembly must exclude paths starting with `Familiar/` (no self-feeding).
- Merge rule: user edits win. `dismissed` is user-only — model output never sets, clears, or resurrects it. Loops the model omits are kept, never lost.
- LLM calls go through `ghostbrain.llm.client.run` (`claude -p`); never the Anthropic API.
- `api.fetch` paths must start with `/` and contain no `..`; only methods GET/POST/PATCH/DELETE/PUT.
- Python: follow `answer.py` error pattern — catch everything, return structured `error`, log traceback.
- Desktop tests: vitest in `desktop/` (`npm test`); Python tests: `pytest` from repo root (`.venv`); plugin tests: vitest in `plugins/familiar/`.
- Commit after every task (conventional commits, `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`).

---

### Task 1: `PUT` method + path guard + timeout override in the API forwarder

**Files:**
- Modify: `desktop/src/main/api-forwarder.ts`
- Modify: `desktop/src/shared/types.ts` (only if `HttpMethod` lacks `PUT`; check first)
- Test: `desktop/src/main/__tests__/api-forwarder.test.ts` (create if absent)

**Interfaces:**
- Consumes: existing `forward(sidecar, method, path, body)`, `ALLOWED_METHODS`, `HttpMethod`.
- Produces: `isSafeApiPath(path: string): boolean` export; `forward(sidecar, method, path, body?, timeoutMs = 300_000)`; `'PUT'` in `ALLOWED_METHODS` and `HttpMethod`.

- [ ] **Step 1: Check the `HttpMethod` type**

Run: `grep -n "HttpMethod" desktop/src/shared/types.ts`
If it's a union without `'PUT'`, add `'PUT'` to the union.

- [ ] **Step 2: Write failing tests**

```ts
// desktop/src/main/__tests__/api-forwarder.test.ts
import { describe, expect, it } from 'vitest';
import { isAllowedMethod, isSafeApiPath } from '../api-forwarder';

describe('isSafeApiPath', () => {
  it('accepts vault-relative api paths', () => {
    expect(isSafeApiPath('/v1/notes?path=Familiar/memory.md')).toBe(true);
  });
  it('rejects paths not starting with /', () => {
    expect(isSafeApiPath('v1/notes')).toBe(false);
    expect(isSafeApiPath('http://evil/v1')).toBe(false);
  });
  it('rejects traversal', () => {
    expect(isSafeApiPath('/v1/../admin')).toBe(false);
  });
});

describe('isAllowedMethod', () => {
  it('includes PUT', () => {
    expect(isAllowedMethod('PUT')).toBe(true);
  });
});
```

- [ ] **Step 3: Run to verify failure**

Run: `cd desktop && npx vitest run src/main/__tests__/api-forwarder.test.ts`
Expected: FAIL — `isSafeApiPath` not exported; PUT not allowed.

- [ ] **Step 4: Implement**

In `api-forwarder.ts`:

```ts
export const ALLOWED_METHODS: readonly HttpMethod[] = [
  'GET',
  'POST',
  'PATCH',
  'DELETE',
  'PUT',
];

/** Plugin-facing guard: sidecar paths only — absolute-from-root, no traversal. */
export function isSafeApiPath(path: string): boolean {
  return path.startsWith('/') && !path.includes('..');
}
```

And extend `forward` with a timeout parameter (sweep LLM calls exceed 5 min):

```ts
export async function forward<T = unknown>(
  sidecar: Sidecar,
  method: HttpMethod,
  path: string,
  body?: unknown,
  timeoutMs = 300_000,
): Promise<ApiResult<T>> {
```

and replace `signal: AbortSignal.timeout(300_000)` with `signal: AbortSignal.timeout(timeoutMs)`. Keep the existing comment, noting plugins may raise it.

- [ ] **Step 5: Run tests + typecheck**

Run: `cd desktop && npx vitest run src/main/__tests__/api-forwarder.test.ts && npx tsc --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 6: Commit**

```bash
git add desktop/src/main/api-forwarder.ts desktop/src/main/__tests__/api-forwarder.test.ts desktop/src/shared/types.ts
git commit -m "feat(plugins): PUT method, path guard, timeout override in api forwarder"
```

---

### Task 2: `ctx.api.fetch` on the main-process plugin bridge

**Files:**
- Modify: `desktop/src/main/plugins/loader.ts` (PluginContext, LoaderDeps, makeContext)
- Modify: `desktop/src/main/index.ts` (`installPlugins()` — pass `fetchApi`)
- Test: `desktop/src/main/plugins/__tests__/loader.test.ts` (extend)

**Interfaces:**
- Consumes: `forward`, `isAllowedMethod`, `isSafeApiPath`, `ApiResult` from Task 1; module-level `sidecar` in `index.ts`.
- Produces: `PluginContext.api.fetch(method: string, path: string, body?: unknown): Promise<ApiResult>`; `LoaderDeps.fetchApi(method: HttpMethod, path: string, body?: unknown): Promise<ApiResult>`.

- [ ] **Step 1: Write failing test**

Follow the existing fixture pattern in `loader.test.ts` (fixture plugins under `__tests__/fixtures/`). Add a test that a plugin's context exposes `api.fetch`, that it delegates to `deps.fetchApi`, and that bad input short-circuits without calling `fetchApi`:

```ts
it('exposes api.fetch that validates and delegates to deps.fetchApi', async () => {
  const calls: unknown[][] = [];
  // build deps as the existing tests do, plus:
  const deps = makeTestDeps({
    fetchApi: async (...args: unknown[]) => {
      calls.push(args);
      return { ok: true, data: { hello: 1 } };
    },
  });
  // activate a fixture plugin whose activate(ctx) stashes ctx (existing
  // fixtures do this via module side-effects; follow that pattern)
  const ctx = await activateFixtureAndGetContext(deps);

  const ok = await ctx.api.fetch('GET', '/v1/vault/stats');
  expect(ok).toEqual({ ok: true, data: { hello: 1 } });
  expect(calls).toEqual([['GET', '/v1/vault/stats', undefined]]);

  const badMethod = await ctx.api.fetch('TRACE', '/v1/x');
  expect(badMethod.ok).toBe(false);

  const badPath = await ctx.api.fetch('GET', 'v1/../x');
  expect(badPath.ok).toBe(false);
  expect(calls.length).toBe(1); // invalid calls never reach fetchApi
});
```

(Adapt helper names to what `loader.test.ts` actually uses — read it first; if there is no context-capturing fixture, add one: a fixture plugin whose `main.cjs` does `module.exports = { activate(ctx){ globalThis.__lastCtx = ctx; } }`.)

- [ ] **Step 2: Run to verify failure**

Run: `cd desktop && npx vitest run src/main/plugins/__tests__/loader.test.ts`
Expected: FAIL — `api` missing on context / `fetchApi` not a known dep.

- [ ] **Step 3: Implement in `loader.ts`**

```ts
import { isAllowedMethod, isSafeApiPath, type ApiResult, type HttpMethod } from '../api-forwarder';

export interface PluginContext {
  // ...existing fields...
  api: {
    fetch(method: string, path: string, body?: unknown): Promise<ApiResult>;
  };
}

export interface LoaderDeps {
  // ...existing fields...
  fetchApi(method: HttpMethod, path: string, body?: unknown): Promise<ApiResult>;
}
```

In `makeContext`, after `ipc`:

```ts
api: {
  fetch: async (method, path, body) => {
    if (!isAllowedMethod(method)) {
      return { ok: false, error: `method not allowed: ${method}` };
    }
    if (typeof path !== 'string' || !isSafeApiPath(path)) {
      return { ok: false, error: 'invalid api path' };
    }
    return deps.fetchApi(method, path, body);
  },
},
```

- [ ] **Step 4: Wire in `index.ts`**

In `installPlugins()`, add to the `createLoader({...})` deps (the `sidecar` const is in scope; 15-minute ceiling covers long LLM sweeps):

```ts
fetchApi: (method, path, body) => forward(sidecar, method, path, body, 900_000),
```

with `import { forward } from './api-forwarder';` added to the imports.

- [ ] **Step 5: Run tests + typecheck**

Run: `cd desktop && npx vitest run src/main/plugins && npx tsc --noEmit`
Expected: PASS. (Other loader tests will need the new `fetchApi` dep added to their shared deps helper — do that, don't stub per-test.)

- [ ] **Step 6: Commit**

```bash
git add desktop/src/main/plugins/loader.ts desktop/src/main/index.ts desktop/src/main/plugins/__tests__/
git commit -m "feat(plugins): ctx.api.fetch raw passthrough to sidecar for main-process plugins"
```

---

### Task 3: Renderer-side `api.fetch` (host IPC + preload + PluginHost)

**Files:**
- Modify: `desktop/src/main/plugins/ipc.ts` (new `gb:plugins:api-fetch` handler; `fetchApi` in opts)
- Modify: `desktop/src/main/index.ts` (pass `fetchApi` to `installPluginsIpc`)
- Modify: `desktop/src/preload/index.ts` (`plugin(id)` gains `api.fetch`) and the preload type declarations (find with `grep -rn "plugin(" desktop/src/preload desktop/src/renderer/global.d.ts desktop/src/shared` — update wherever the `gb.plugin` type lives)
- Modify: `desktop/src/renderer/components/PluginHost.tsx` (`PluginApi.api`)
- Test: `desktop/src/main/plugins/__tests__/ipc.test.ts` (create; direct-call style like existing plugin tests)

**Interfaces:**
- Consumes: `isAllowedMethod`, `isSafeApiPath`, `forward` (Task 1).
- Produces: renderer `PluginApi.api.fetch(method: string, path: string, body?: unknown): Promise<ApiResult>`; IPC channel `gb:plugins:api-fetch` with args `(pluginId, method, path, body)`.

- [ ] **Step 1: Write failing test**

`ipc.ts` registers via `ipcMain.handle`, which is awkward to unit-test; follow the codebase's existing approach (check how `loader.test.ts`/`store.test.ts` isolate electron — there may be a vi.mock of `electron`). Extract the handler body as a testable function:

```ts
// in ipc.ts
export function makeApiFetchHandler(fetchApi: FetchApi) {
  return async (id: unknown, method: unknown, path: unknown, body: unknown): Promise<ApiResult> => {
    if (typeof id !== 'string' || typeof method !== 'string' || typeof path !== 'string') {
      return { ok: false, error: 'invalid arguments' };
    }
    if (!isAllowedMethod(method)) return { ok: false, error: `method not allowed: ${method}` };
    if (!isSafeApiPath(path)) return { ok: false, error: 'invalid api path' };
    return fetchApi(method, path, body);
  };
}
```

Test:

```ts
// desktop/src/main/plugins/__tests__/ipc.test.ts
import { describe, expect, it } from 'vitest';
import { makeApiFetchHandler } from '../ipc';

describe('gb:plugins:api-fetch handler', () => {
  it('forwards valid calls', async () => {
    const h = makeApiFetchHandler(async (m, p, b) => ({ ok: true, data: [m, p, b] }));
    expect(await h('familiar', 'GET', '/v1/vault/stats', undefined)).toEqual({
      ok: true,
      data: ['GET', '/v1/vault/stats', undefined],
    });
  });
  it('rejects bad method, path, and arg types', async () => {
    const h = makeApiFetchHandler(async () => ({ ok: true, data: null }));
    expect((await h('familiar', 'TRACE', '/v1/x', undefined)).ok).toBe(false);
    expect((await h('familiar', 'GET', '../x', undefined)).ok).toBe(false);
    expect((await h(7, 'GET', '/v1/x', undefined)).ok).toBe(false);
  });
});
```

(If `ipc.test.ts` needs an electron mock to import the module, copy the mock preamble from a sibling test.)

- [ ] **Step 2: Run to verify failure**

Run: `cd desktop && npx vitest run src/main/plugins/__tests__/ipc.test.ts`
Expected: FAIL — `makeApiFetchHandler` not exported.

- [ ] **Step 3: Implement**

In `ipc.ts`: add `makeApiFetchHandler` (above), define `type FetchApi = (method: HttpMethod, path: string, body?: unknown) => Promise<ApiResult>` (import types from `../api-forwarder`), extend opts, and register:

```ts
export function installPluginsIpc(opts: {
  loader: PluginLoader;
  pluginsRoot: string;
  fetchApi: FetchApi;
}): void {
  // ...existing handlers...
  const apiFetch = makeApiFetchHandler(opts.fetchApi);
  ipcMain.handle('gb:plugins:api-fetch', (_e, id, method, path, body) =>
    apiFetch(id, method, path, body),
  );
}
```

In `index.ts` `installPlugins()`:

```ts
installPluginsIpc({
  loader,
  pluginsRoot,
  fetchApi: (method, path, body) => forward(sidecar, method, path, body, 900_000),
});
```

In `preload/index.ts`, inside `plugin: (id: string) => ({ ... })` add:

```ts
api: {
  fetch: (method: string, path: string, body?: unknown) =>
    ipcRenderer.invoke('gb:plugins:api-fetch', id, method, path, body),
},
```

and mirror it in the `gb.plugin` type declaration.

In `PluginHost.tsx`:

```ts
export interface PluginApi {
  // ...existing fields...
  api: {
    fetch(method: string, path: string, body?: unknown): Promise<unknown>;
  };
}
```

and in the `api` object construction: `api: { fetch: bridge.api.fetch },`.

- [ ] **Step 4: Run tests + typecheck**

Run: `cd desktop && npx vitest run && npx tsc --noEmit`
Expected: PASS (full desktop suite — the `installPluginsIpc` signature change may touch other tests).

- [ ] **Step 5: Commit**

```bash
git add desktop/src/main/plugins/ipc.ts desktop/src/main/index.ts desktop/src/preload/ desktop/src/renderer/components/PluginHost.tsx desktop/src/main/plugins/__tests__/ipc.test.ts
git commit -m "feat(plugins): renderer api.fetch bridge via gb:plugins:api-fetch"
```

---

### Task 4: `PUT /v1/notes` — path-addressed note upsert

**Files:**
- Modify: `ghostbrain/api/repo/note.py` (add `save_note_at_path`)
- Modify: `ghostbrain/api/models/note.py` (add `UpsertNoteRequest`)
- Modify: `ghostbrain/api/routes/notes.py` (add `PUT` route)
- Test: `ghostbrain/api/tests/test_routes_notes_upsert.py` (create)

**Interfaces:**
- Consumes: `_resolve_safe` path guard, existing route/module conventions.
- Produces: `PUT /v1/notes` body `{"path": str, "content": str}` → `{"path": str, "created": bool}`. `content` is the **verbatim full file** (frontmatter included if the caller wants any). 400 invalid path, 422 empty content.

- [ ] **Step 1: Write failing tests**

```python
# ghostbrain/api/tests/test_routes_notes_upsert.py
"""PUT /v1/notes — path-addressed upsert (Familiar plugin write-back)."""


def test_upsert_creates_nested_note(client, tmp_vault):
    r = client.put(
        "/v1/notes",
        json={"path": "Familiar/briefings/2026-07-08.md", "content": "---\ntype: familiar-briefing\n---\n\n# Briefing\n"},
    )
    assert r.status_code == 200
    assert r.json() == {"path": "Familiar/briefings/2026-07-08.md", "created": True}
    on_disk = (tmp_vault / "Familiar" / "briefings" / "2026-07-08.md").read_text()
    assert on_disk.startswith("---\ntype: familiar-briefing")


def test_upsert_replaces_existing(client, tmp_vault):
    p = tmp_vault / "Familiar"
    p.mkdir()
    (p / "memory.md").write_text("old\n")
    r = client.put("/v1/notes", json={"path": "Familiar/memory.md", "content": "new body\n"})
    assert r.status_code == 200
    assert r.json()["created"] is False
    assert (p / "memory.md").read_text() == "new body\n"


def test_upsert_rejects_traversal_and_non_md(client, tmp_vault):
    assert client.put("/v1/notes", json={"path": "../evil.md", "content": "x"}).status_code == 400
    assert client.put("/v1/notes", json={"path": "Familiar/run.sh", "content": "x"}).status_code == 400


def test_upsert_rejects_empty_content(client, tmp_vault):
    r = client.put("/v1/notes", json={"path": "Familiar/memory.md", "content": "  "})
    assert r.status_code == 422
```

(Check `conftest.py` for the actual `client` fixture name/signature and match it.)

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest ghostbrain/api/tests/test_routes_notes_upsert.py -v`
Expected: FAIL — 405 Method Not Allowed.

- [ ] **Step 3: Implement**

`repo/note.py`:

```python
def save_note_at_path(rel_path: str, content: str) -> dict:
    """Create or fully replace a vault note at ``rel_path`` (verbatim content).

    Unlike ``save_note_body`` this does not preserve frontmatter — the caller
    owns the whole file. Parent directories are created. Reuses the house
    ``_resolve_safe`` guard (vault-relative, no traversal, .md only).
    """
    target = _resolve_safe(rel_path)
    created = not target.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
    return {"path": rel_path, "created": created}
```

`models/note.py` (match the module's existing BaseModel style):

```python
class UpsertNoteRequest(BaseModel):
    path: str
    content: str
```

`routes/notes.py` (import `UpsertNoteRequest`, `save_note_at_path`; place the route next to `create_note`):

```python
@router.put("", status_code=status.HTTP_200_OK)
def upsert_note(req: UpsertNoteRequest) -> dict:
    """Create or replace a vault note at an explicit path (plugin write-back)."""
    if not req.content.strip():
        raise HTTPException(status_code=422, detail="content must not be empty")
    try:
        return save_note_at_path(req.path, req.content)
    except NoteInvalidPath as e:
        raise HTTPException(status_code=400, detail=str(e))
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest ghostbrain/api/tests/ -v -k "upsert or notes"`
Expected: new tests PASS, existing notes tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/repo/note.py ghostbrain/api/models/note.py ghostbrain/api/routes/notes.py ghostbrain/api/tests/test_routes_notes_upsert.py
git commit -m "feat(api): PUT /v1/notes path-addressed upsert"
```

---

### Task 5: `POST /v1/llm/run` — raw prompt runner

**Files:**
- Create: `ghostbrain/api/models/llm.py`
- Create: `ghostbrain/api/routes/llm.py`
- Modify: `ghostbrain/api/main.py` (import + `include_router`)
- Test: `ghostbrain/api/tests/test_routes_llm_run.py`

**Interfaces:**
- Consumes: `ghostbrain.llm.client.run(prompt, *, model, json_schema, system_prompt, budget_usd, timeout_s) -> LLMResult` (`LLMResult.text`, `.structured`, `.cost_usd`, `.duration_ms`); raises `LLMError`.
- Produces: `POST /v1/llm/run` body `{"prompt": str, "system": str|null, "model": str = "sonnet", "jsonSchema": dict|null, "timeoutSeconds": int = 600, "budgetUsd": float|null}` → `{"text": str, "structured": Any|null, "error": str|null, "costUsd": float|null, "durationMs": int|null}`. Never a 500: failures return `error`.

- [ ] **Step 1: Write failing tests**

```python
# ghostbrain/api/tests/test_routes_llm_run.py
"""POST /v1/llm/run — raw prompt runner for plugins."""
from ghostbrain.llm.client import LLMError, LLMResult


def _result(text="hi", structured=None):
    return LLMResult(text=text, structured=structured, model="sonnet",
                     cost_usd=0.01, duration_ms=1200, session_id="s", raw={})


def test_llm_run_success(client, monkeypatch):
    seen = {}

    def fake_run(prompt, **kw):
        seen["prompt"], seen["kw"] = prompt, kw
        return _result(text="pong")

    monkeypatch.setattr("ghostbrain.api.routes.llm.llm_run", fake_run)
    r = client.post("/v1/llm/run", json={"prompt": "ping", "system": "be brief", "model": "opus"})
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "pong" and body["error"] is None
    assert body["costUsd"] == 0.01 and body["durationMs"] == 1200
    assert seen["prompt"] == "ping"
    assert seen["kw"]["system_prompt"] == "be brief"
    assert seen["kw"]["model"] == "opus"
    assert seen["kw"]["timeout_s"] == 600


def test_llm_run_json_schema_passthrough(client, monkeypatch):
    schema = {"type": "object", "properties": {"x": {"type": "number"}}}

    def fake_run(prompt, **kw):
        assert kw["json_schema"] == schema
        return _result(text='{"x": 1}', structured={"x": 1})

    monkeypatch.setattr("ghostbrain.api.routes.llm.llm_run", fake_run)
    r = client.post("/v1/llm/run", json={"prompt": "p", "jsonSchema": schema})
    assert r.json()["structured"] == {"x": 1}


def test_llm_run_error_is_structured(client, monkeypatch):
    def fake_run(prompt, **kw):
        raise LLMError("claude binary not found")

    monkeypatch.setattr("ghostbrain.api.routes.llm.llm_run", fake_run)
    r = client.post("/v1/llm/run", json={"prompt": "p"})
    assert r.status_code == 200
    assert r.json()["error"] == "LLMError: claude binary not found"
    assert r.json()["text"] == ""


def test_llm_run_empty_prompt_422(client):
    assert client.post("/v1/llm/run", json={"prompt": "  "}).status_code == 422
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest ghostbrain/api/tests/test_routes_llm_run.py -v`
Expected: FAIL — 404 (no route).

- [ ] **Step 3: Implement**

```python
# ghostbrain/api/models/llm.py
"""Models for POST /v1/llm/run."""
from typing import Any

from pydantic import BaseModel


class LlmRunRequest(BaseModel):
    prompt: str
    system: str | None = None
    model: str = "sonnet"
    jsonSchema: dict | None = None
    timeoutSeconds: int = 600
    budgetUsd: float | None = None


class LlmRunResponse(BaseModel):
    text: str
    structured: Any | None = None
    error: str | None = None
    costUsd: float | None = None
    durationMs: int | None = None
```

```python
# ghostbrain/api/routes/llm.py
"""POST /v1/llm/run — raw prompt runner (plugins assemble their own context)."""
import logging

from fastapi import APIRouter, HTTPException

from ghostbrain.api.models.llm import LlmRunRequest, LlmRunResponse
from ghostbrain.llm.client import run as llm_run

log = logging.getLogger("ghostbrain.api.llm")

router = APIRouter(prefix="/v1/llm", tags=["llm"])


@router.post("/run", response_model=LlmRunResponse)
def llm_run_endpoint(payload: LlmRunRequest) -> dict:
    if not payload.prompt.strip():
        raise HTTPException(status_code=422, detail="prompt must not be empty")
    try:
        result = llm_run(
            payload.prompt,
            model=payload.model,
            json_schema=payload.jsonSchema,
            system_prompt=payload.system,
            budget_usd=payload.budgetUsd,
            timeout_s=payload.timeoutSeconds,
        )
        return {
            "text": result.text,
            "structured": result.structured,
            "error": None,
            "costUsd": result.cost_usd,
            "durationMs": result.duration_ms,
        }
    except Exception as e:  # noqa: BLE001 — same contract as answer.py
        log.exception("llm run failed")
        return {"text": "", "structured": None, "error": f"{type(e).__name__}: {e}",
                "costUsd": None, "durationMs": None}
```

`main.py`: add `from ghostbrain.api.routes import llm as llm_routes` to the imports and `app.include_router(llm_routes.router)` after the chat router.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest ghostbrain/api/tests/test_routes_llm_run.py ghostbrain/api/tests/test_main.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ghostbrain/api/models/llm.py ghostbrain/api/routes/llm.py ghostbrain/api/main.py ghostbrain/api/tests/test_routes_llm_run.py
git commit -m "feat(api): POST /v1/llm/run raw prompt runner"
```

---

### Task 6: Plugin scaffold (`plugins/familiar/`)

**Files:**
- Create: `plugins/familiar/manifest.json`, `plugins/familiar/package.json`, `plugins/familiar/build.mjs`, `plugins/familiar/src/main.js`, `plugins/familiar/src/renderer.js`, `plugins/familiar/.gitignore` (ignore `node_modules`, NOT `dist`)
- Create (built): `plugins/familiar/dist/main.cjs`, `plugins/familiar/dist/renderer.mjs`

**Interfaces:**
- Consumes: plugin package contract from the plugin-system spec (`activate(ctx)` / `deactivate()`; `mount(el, api)` returning unmount).
- Produces: an installable plugin skeleton every later task fills in. Build command: `npm run build` inside `plugins/familiar/`. Test command: `npm test` (vitest).

- [ ] **Step 1: Scaffold files**

```json
// plugins/familiar/manifest.json
{
  "id": "familiar",
  "name": "Familiar",
  "version": "0.1.0",
  "description": "Chief-of-staff briefings: themes, open loops, decisions, blind spots",
  "apiVersion": 1,
  "icon": "ghost",
  "entry": { "main": "dist/main.cjs", "renderer": "dist/renderer.mjs" }
}
```

```json
// plugins/familiar/package.json
{
  "name": "poltergeist-plugin-familiar",
  "private": true,
  "type": "module",
  "scripts": {
    "build": "node build.mjs",
    "test": "vitest run"
  },
  "devDependencies": {
    "esbuild": "^0.21.0",
    "vitest": "^1.6.0"
  },
  "dependencies": {
    "marked": "^12.0.0"
  }
}
```

```js
// plugins/familiar/build.mjs
import { build } from 'esbuild';

await build({
  entryPoints: ['src/main.js'],
  outfile: 'dist/main.cjs',
  bundle: true,
  platform: 'node',
  format: 'cjs',
  external: ['electron'],
});

await build({
  entryPoints: ['src/renderer.js'],
  outfile: 'dist/renderer.mjs',
  bundle: true,
  platform: 'browser',
  format: 'esm',
});
console.log('built dist/main.cjs + dist/renderer.mjs');
```

```js
// plugins/familiar/src/main.js — placeholder wiring, replaced in Task 11
let context = null;

export function activate(ctx) {
  context = ctx;
  ctx.log('familiar activated');
  ctx.ipc.handle('status', () => ({ running: false, note: 'scaffold' }));
}

export function deactivate() {
  context = null;
}
```

```js
// plugins/familiar/src/renderer.js — placeholder, replaced in Task 12
export function mount(el, api) {
  el.textContent = `Familiar scaffold (plugin ${api.pluginId})`;
  return () => {};
}
```

- [ ] **Step 2: Build and eyeball dist**

Run: `cd plugins/familiar && npm install && npm run build && head -5 dist/main.cjs dist/renderer.mjs`
Expected: both files exist; `main.cjs` is CJS (`module.exports`/`__toCommonJS`), `renderer.mjs` has `export {`.

- [ ] **Step 3: Manual smoke (optional but cheap)**

Launch the desktop app (dev), Plugins screen → Install from folder → pick `plugins/familiar/`. Expect "Familiar" in the sidebar rendering the scaffold text. Uninstall is not needed — later tasks reinstall over it via Reload.

- [ ] **Step 4: Commit**

```bash
git add plugins/familiar
git commit -m "feat(familiar): plugin scaffold with esbuild + committed dist"
```

---

### Task 7: `lib/schedule.js` — due-run math

**Files:**
- Create: `plugins/familiar/src/lib/schedule.js`
- Test: `plugins/familiar/src/lib/__tests__/schedule.test.js`

**Interfaces:**
- Produces:
  - `lastScheduledSlot(config, now: Date): Date` — most recent `{day, hour}` occurrence ≤ now (local time).
  - `isRunDue(config, state, now: Date): boolean` — true when `state.lastSuccessfulRunAt` (ISO string or undefined) predates the last slot; undefined ⇒ true (first run fires immediately).
  - `nextRunAt(config, now: Date): Date`.
  - `config` shape: `{cadence: 'weekly', day: 'monday'…'sunday', hour: 0–23}`.

- [ ] **Step 1: Write failing tests**

```js
// plugins/familiar/src/lib/__tests__/schedule.test.js
import { describe, expect, it } from 'vitest';
import { isRunDue, lastScheduledSlot, nextRunAt } from '../schedule.js';

const CFG = { cadence: 'weekly', day: 'monday', hour: 7 };
// 2026-07-08 is a Wednesday; 2026-07-06 the preceding Monday.
const WED = new Date(2026, 6, 8, 12, 0, 0);

describe('lastScheduledSlot', () => {
  it('finds the preceding Monday 07:00', () => {
    expect(lastScheduledSlot(CFG, WED)).toEqual(new Date(2026, 6, 6, 7, 0, 0));
  });
  it('same-day before the hour rolls back a week', () => {
    const monEarly = new Date(2026, 6, 6, 6, 0, 0);
    expect(lastScheduledSlot(CFG, monEarly)).toEqual(new Date(2026, 5, 29, 7, 0, 0));
  });
  it('same-day at the hour counts', () => {
    const monSeven = new Date(2026, 6, 6, 7, 0, 0);
    expect(lastScheduledSlot(CFG, monSeven)).toEqual(new Date(2026, 6, 6, 7, 0, 0));
  });
});

describe('isRunDue', () => {
  it('first run: due immediately', () => {
    expect(isRunDue(CFG, {}, WED)).toBe(true);
  });
  it('ran after the slot: not due', () => {
    expect(isRunDue(CFG, { lastSuccessfulRunAt: new Date(2026, 6, 6, 8, 0).toISOString() }, WED)).toBe(false);
  });
  it('missed slot (app closed Monday): due on Wednesday', () => {
    expect(isRunDue(CFG, { lastSuccessfulRunAt: new Date(2026, 6, 3, 9, 0).toISOString() }, WED)).toBe(true);
  });
});

describe('nextRunAt', () => {
  it('is one week after the last slot', () => {
    expect(nextRunAt(CFG, WED)).toEqual(new Date(2026, 6, 13, 7, 0, 0));
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd plugins/familiar && npx vitest run src/lib/__tests__/schedule.test.js`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```js
// plugins/familiar/src/lib/schedule.js
const DAYS = ['sunday', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday'];

export function lastScheduledSlot(config, now) {
  const target = DAYS.indexOf(config.day);
  const d = new Date(now);
  d.setHours(config.hour, 0, 0, 0);
  d.setDate(d.getDate() - ((d.getDay() - target + 7) % 7));
  if (d > now) d.setDate(d.getDate() - 7);
  return d;
}

export function isRunDue(config, state, now = new Date()) {
  if (!state.lastSuccessfulRunAt) return true;
  return new Date(state.lastSuccessfulRunAt) < lastScheduledSlot(config, now);
}

export function nextRunAt(config, now = new Date()) {
  const next = new Date(lastScheduledSlot(config, now));
  next.setDate(next.getDate() + 7);
  return next;
}
```

- [ ] **Step 4: Run tests**

Run: `cd plugins/familiar && npx vitest run src/lib/__tests__/schedule.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/familiar/src/lib/schedule.js plugins/familiar/src/lib/__tests__/schedule.test.js
git commit -m "feat(familiar): weekly schedule due-run math"
```

---

### Task 8: `lib/delta.js` + `lib/budget.js` — delta window and token budget

**Files:**
- Create: `plugins/familiar/src/lib/delta.js`, `plugins/familiar/src/lib/budget.js`
- Test: `plugins/familiar/src/lib/__tests__/delta.test.js`, `plugins/familiar/src/lib/__tests__/budget.test.js`

**Interfaces:**
- Produces:
  - `listDays(sinceIso: string, nowIso: string): string[]` — local `YYYY-MM-DD` for every day touching the window, inclusive both ends.
  - `extractPaths(rows: {path?: string|null}[]): string[]` — unique, non-null, excluding `Familiar/` prefix.
  - `trimToBudget(notes: {path, modified, text}[], maxChars: number): {kept: Note[], dropped: string[]}` — drops whole notes oldest-`modified`-first until under budget; always keeps ≥ 1; `kept` stays oldest→newest.
  - `renderNoteBlocks(notes): string` — `<note path="…" modified="…">\n…\n</note>` blocks.

- [ ] **Step 1: Write failing tests**

```js
// plugins/familiar/src/lib/__tests__/delta.test.js
import { describe, expect, it } from 'vitest';
import { extractPaths, listDays } from '../delta.js';

describe('listDays', () => {
  it('spans the window inclusively in local time', () => {
    const days = listDays(new Date(2026, 6, 6, 15, 0).toISOString(), new Date(2026, 6, 8, 9, 0).toISOString());
    expect(days).toEqual(['2026-07-06', '2026-07-07', '2026-07-08']);
  });
  it('same-day window yields one day', () => {
    const d = new Date(2026, 6, 8, 1, 0).toISOString();
    expect(listDays(d, d)).toEqual(['2026-07-08']);
  });
});

describe('extractPaths', () => {
  it('dedupes, drops nulls, excludes Familiar/', () => {
    const rows = [
      { path: '10-daily/2026-07-07.md' },
      { path: '10-daily/2026-07-07.md' },
      { path: null },
      {},
      { path: 'Familiar/briefings/2026-07-01.md' },
      { path: '20-contexts/codeship/x.md' },
    ];
    expect(extractPaths(rows)).toEqual(['10-daily/2026-07-07.md', '20-contexts/codeship/x.md']);
  });
});
```

```js
// plugins/familiar/src/lib/__tests__/budget.test.js
import { describe, expect, it } from 'vitest';
import { renderNoteBlocks, trimToBudget } from '../budget.js';

const note = (path, modified, len) => ({ path, modified, text: 'x'.repeat(len) });

describe('trimToBudget', () => {
  it('keeps everything under budget', () => {
    const { kept, dropped } = trimToBudget([note('a.md', '2026-07-01', 10), note('b.md', '2026-07-02', 10)], 100);
    expect(kept.map((n) => n.path)).toEqual(['a.md', 'b.md']);
    expect(dropped).toEqual([]);
  });
  it('drops oldest whole notes first', () => {
    const { kept, dropped } = trimToBudget(
      [note('new.md', '2026-07-07', 60), note('old.md', '2026-07-01', 60), note('mid.md', '2026-07-04', 60)],
      130,
    );
    expect(dropped).toEqual(['old.md']);
    expect(kept.map((n) => n.path)).toEqual(['mid.md', 'new.md']);
  });
  it('always keeps at least one note', () => {
    const { kept } = trimToBudget([note('huge.md', '2026-07-01', 500)], 10);
    expect(kept.length).toBe(1);
  });
});

describe('renderNoteBlocks', () => {
  it('wraps notes in path-tagged blocks', () => {
    const out = renderNoteBlocks([{ path: 'a.md', modified: '2026-07-01', text: 'hello' }]);
    expect(out).toBe('<note path="a.md" modified="2026-07-01">\nhello\n</note>');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd plugins/familiar && npx vitest run src/lib/__tests__/delta.test.js src/lib/__tests__/budget.test.js`
Expected: FAIL — modules not found.

- [ ] **Step 3: Implement**

```js
// plugins/familiar/src/lib/delta.js
function localYmd(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export function listDays(sinceIso, nowIso) {
  const d = new Date(sinceIso);
  d.setHours(0, 0, 0, 0);
  const end = new Date(nowIso);
  end.setHours(0, 0, 0, 0);
  const out = [];
  while (d <= end) {
    out.push(localYmd(d));
    d.setDate(d.getDate() + 1);
  }
  return out;
}

export function extractPaths(rows) {
  const seen = new Set();
  for (const row of rows) {
    const p = row?.path;
    if (typeof p === 'string' && p && !p.startsWith('Familiar/')) seen.add(p);
  }
  return [...seen];
}
```

```js
// plugins/familiar/src/lib/budget.js
export function trimToBudget(notes, maxChars) {
  const kept = [...notes].sort((a, b) => String(a.modified).localeCompare(String(b.modified)));
  const dropped = [];
  const total = () => kept.reduce((n, x) => n + x.text.length, 0);
  while (kept.length > 1 && total() > maxChars) dropped.push(kept.shift().path);
  return { kept, dropped };
}

export function renderNoteBlocks(notes) {
  return notes
    .map((n) => `<note path="${n.path}" modified="${n.modified ?? ''}">\n${n.text}\n</note>`)
    .join('\n\n');
}
```

- [ ] **Step 4: Run tests**

Run: `cd plugins/familiar && npx vitest run`
Expected: PASS (all lib tests so far).

- [ ] **Step 5: Commit**

```bash
git add plugins/familiar/src/lib/delta.js plugins/familiar/src/lib/budget.js plugins/familiar/src/lib/__tests__/
git commit -m "feat(familiar): delta window and char-budget trimming"
```

---

### Task 9: `lib/trackers.js` — open-loops/decisions parse, render, merge

**Files:**
- Create: `plugins/familiar/src/lib/trackers.js`
- Test: `plugins/familiar/src/lib/__tests__/trackers.test.js`

**Interfaces:**
- Produces:
  - Loop object: `{id, text, owedTo: string|null, sourcePath, firstSeen, status: 'open'|'done'|'stale'|'dismissed'}`.
  - `parseOpenLoops(md: string): {loops: Loop[], unparsed: string[]}` — a `- ` line that fails the format goes to `unparsed`, never lost.
  - `renderOpenLoops(loops: Loop[], unparsed: string[]): string` — full file body incl. `# Open loops` header; unparsed lines under `## Unparsed`.
  - `mergeLoops(current: Loop[], fromModel: Loop[]): Loop[]` — by id; user `done`/`dismissed` wins; model can flip `open→done|stale`; model never sets `dismissed` (coerced to `open` for new, ignored for existing); loops missing from model output are kept.
  - `parseDecisions(md): {date, text, sourcePath}[]`, `renderDecisions(list): string`, `mergeDecisions(current, fromModel)` — append-only, dedup key `date + text`.
- Line format (writer always emits every field; `owedTo` omitted when null):
  `- [ ] <!--id:loop-send-doc--> Send the doc — owed to Pieter (from [source](20-contexts/x.md), first seen 2026-07-01) {stale}`
  Checkbox `[x]` ⇔ `done`; `{stale}`/`{dismissed}` trailing tag; no tag + `[ ]` ⇔ `open`.
  Decisions: `- 2026-07-01 — Decided X (from [source](path.md))`.

- [ ] **Step 1: Write failing tests**

```js
// plugins/familiar/src/lib/__tests__/trackers.test.js
import { describe, expect, it } from 'vitest';
import {
  mergeDecisions, mergeLoops, parseDecisions, parseOpenLoops,
  renderDecisions, renderOpenLoops,
} from '../trackers.js';

const LOOP = {
  id: 'loop-send-doc', text: 'Send the doc', owedTo: 'Pieter',
  sourcePath: '20-contexts/x.md', firstSeen: '2026-07-01', status: 'open',
};

describe('open loops round-trip', () => {
  it('render → parse is identity', () => {
    const loops = [
      LOOP,
      { ...LOOP, id: 'loop-b', status: 'done' },
      { ...LOOP, id: 'loop-c', status: 'stale', owedTo: null },
      { ...LOOP, id: 'loop-d', status: 'dismissed' },
    ];
    const md = renderOpenLoops(loops, []);
    expect(parseOpenLoops(md)).toEqual({ loops, unparsed: [] });
  });
  it('malformed list lines survive as unparsed', () => {
    const md = '# Open loops\n\n- hand-written todo without id\n';
    const { loops, unparsed } = parseOpenLoops(md);
    expect(loops).toEqual([]);
    expect(unparsed).toEqual(['- hand-written todo without id']);
    expect(renderOpenLoops(loops, unparsed)).toContain('## Unparsed');
  });
});

describe('mergeLoops', () => {
  it('model flips open→done', () => {
    const merged = mergeLoops([LOOP], [{ ...LOOP, status: 'done' }]);
    expect(merged[0].status).toBe('done');
  });
  it('user done/dismissed wins over model', () => {
    const current = [{ ...LOOP, status: 'dismissed' }, { ...LOOP, id: 'loop-b', status: 'done' }];
    const fromModel = [{ ...LOOP, status: 'open' }, { ...LOOP, id: 'loop-b', status: 'open' }];
    const merged = mergeLoops(current, fromModel);
    expect(merged.map((l) => l.status)).toEqual(['dismissed', 'done']);
  });
  it('model cannot dismiss', () => {
    const merged = mergeLoops([LOOP], [{ ...LOOP, status: 'dismissed' }]);
    expect(merged[0].status).toBe('open');
    const fresh = mergeLoops([], [{ ...LOOP, id: 'loop-new', status: 'dismissed' }]);
    expect(fresh[0].status).toBe('open');
  });
  it('loops omitted by the model are kept', () => {
    const merged = mergeLoops([LOOP], []);
    expect(merged).toEqual([LOOP]);
  });
  it('new model loops are appended', () => {
    const merged = mergeLoops([LOOP], [{ ...LOOP, id: 'loop-new' }]);
    expect(merged.map((l) => l.id)).toEqual(['loop-send-doc', 'loop-new']);
  });
});

describe('decisions', () => {
  const DEC = { date: '2026-07-01', text: 'Use plugin architecture', sourcePath: 'a.md' };
  it('round-trips', () => {
    expect(parseDecisions(renderDecisions([DEC]))).toEqual([DEC]);
  });
  it('merge appends new, dedups by date+text', () => {
    const merged = mergeDecisions([DEC], [DEC, { ...DEC, text: 'Another' }]);
    expect(merged.length).toBe(2);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd plugins/familiar && npx vitest run src/lib/__tests__/trackers.test.js`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```js
// plugins/familiar/src/lib/trackers.js
// Tracker notes are plain markdown, one machine-parseable line per item.
// The vault is the database: humans may edit these files; any list line that
// doesn't parse is preserved under "## Unparsed" rather than dropped.

const LOOP_RE = new RegExp(
  '^- \\[( |x)\\] <!--id:([a-z0-9-]+)--> (.+?)' +
  '(?: — owed to (.+?))?' +
  ' \\(from \\[source\\]\\((.+?)\\), first seen (\\d{4}-\\d{2}-\\d{2})\\)' +
  '(?: \\{(stale|dismissed)\\})?$',
);

export function parseOpenLoops(md) {
  const loops = [];
  const unparsed = [];
  for (const line of md.split('\n')) {
    if (!line.startsWith('- ')) continue;
    const m = LOOP_RE.exec(line);
    if (!m) {
      unparsed.push(line);
      continue;
    }
    const [, box, id, text, owedTo, sourcePath, firstSeen, tag] = m;
    loops.push({
      id, text, owedTo: owedTo ?? null, sourcePath, firstSeen,
      status: box === 'x' ? 'done' : (tag ?? 'open'),
    });
  }
  return { loops, unparsed };
}

function renderLoop(l) {
  const box = l.status === 'done' ? 'x' : ' ';
  const owed = l.owedTo ? ` — owed to ${l.owedTo}` : '';
  const tag = l.status === 'stale' || l.status === 'dismissed' ? ` {${l.status}}` : '';
  return `- [${box}] <!--id:${l.id}--> ${l.text}${owed} (from [source](${l.sourcePath}), first seen ${l.firstSeen})${tag}`;
}

export function renderOpenLoops(loops, unparsed) {
  const lines = ['# Open loops', '', ...loops.map(renderLoop)];
  if (unparsed.length) lines.push('', '## Unparsed', '', ...unparsed);
  return lines.join('\n') + '\n';
}

export function mergeLoops(current, fromModel) {
  const byId = new Map(current.map((l) => [l.id, l]));
  const seen = new Set();
  const out = [];
  for (const cur of current) {
    seen.add(cur.id);
    const m = fromModel.find((x) => x.id === cur.id);
    if (!m || cur.status === 'done' || cur.status === 'dismissed') {
      out.push(cur); // user state wins; model omission never loses a loop
      continue;
    }
    const status = m.status === 'dismissed' ? cur.status : m.status;
    out.push({ ...cur, status });
  }
  for (const m of fromModel) {
    if (byId.has(m.id)) continue;
    out.push({ ...m, owedTo: m.owedTo ?? null, status: m.status === 'dismissed' ? 'open' : m.status });
  }
  return out;
}

const DECISION_RE = /^- (\d{4}-\d{2}-\d{2}) — (.+?) \(from \[source\]\((.+?)\)\)$/;

export function parseDecisions(md) {
  const out = [];
  for (const line of md.split('\n')) {
    const m = DECISION_RE.exec(line);
    if (m) out.push({ date: m[1], text: m[2], sourcePath: m[3] });
  }
  return out;
}

export function renderDecisions(list) {
  return ['# Decisions', '', ...list.map((d) => `- ${d.date} — ${d.text} (from [source](${d.sourcePath}))`)].join('\n') + '\n';
}

export function mergeDecisions(current, fromModel) {
  const key = (d) => `${d.date} ${d.text}`;
  const seen = new Set(current.map(key));
  const out = [...current];
  for (const d of fromModel) {
    if (!seen.has(key(d))) {
      seen.add(key(d));
      out.push(d);
    }
  }
  return out;
}
```

- [ ] **Step 4: Run tests**

Run: `cd plugins/familiar && npx vitest run src/lib/__tests__/trackers.test.js`
Expected: PASS. If the round-trip test fails on the regex, fix the regex — not the test.

- [ ] **Step 5: Commit**

```bash
git add plugins/familiar/src/lib/trackers.js plugins/familiar/src/lib/__tests__/trackers.test.js
git commit -m "feat(familiar): tracker notes parse/render/merge with user-edits-win semantics"
```

---

### Task 10: `lib/prompt.js` + `lib/output.js` — sweep prompt and output contract

**Files:**
- Create: `plugins/familiar/src/lib/prompt.js`, `plugins/familiar/src/lib/output.js`
- Test: `plugins/familiar/src/lib/__tests__/output.test.js`

**Interfaces:**
- Produces:
  - `SYSTEM_PROMPT: string`, `SWEEP_JSON_SCHEMA: object` (exported consts).
  - `buildUserPrompt({memoryMd, openLoopsMd, decisionsMd, noteBlocks, droppedPaths, windowStart, windowEnd}): string`.
  - `parseSweepOutput(res: {text, structured}): SweepOutput` — throws `Error` with a descriptive message on any contract violation (caller retries once with the message).
  - `SweepOutput = {briefingMarkdown, memoryMarkdown, openLoops: Loop[], decisions: Decision[]}` (loop/decision shapes from Task 9).

- [ ] **Step 1: Write failing tests**

```js
// plugins/familiar/src/lib/__tests__/output.test.js
import { describe, expect, it } from 'vitest';
import { parseSweepOutput } from '../output.js';

const GOOD = {
  briefingMarkdown: '# Briefing',
  memoryMarkdown: '# Memory',
  openLoops: [{ id: 'loop-a', text: 't', owedTo: null, sourcePath: 'a.md', firstSeen: '2026-07-01', status: 'open' }],
  decisions: [{ date: '2026-07-01', text: 'd', sourcePath: 'a.md' }],
};

describe('parseSweepOutput', () => {
  it('prefers structured output', () => {
    expect(parseSweepOutput({ text: 'garbage', structured: GOOD })).toEqual(GOOD);
  });
  it('falls back to fenced JSON in text', () => {
    const text = 'Here you go:\n```json\n' + JSON.stringify(GOOD) + '\n```\n';
    expect(parseSweepOutput({ text, structured: null })).toEqual(GOOD);
  });
  it('throws with the missing key named', () => {
    const bad = { ...GOOD };
    delete bad.openLoops;
    expect(() => parseSweepOutput({ text: '', structured: bad })).toThrow(/openLoops/);
  });
  it('throws on a loop with a bad id', () => {
    const bad = { ...GOOD, openLoops: [{ ...GOOD.openLoops[0], id: 'Bad Id!' }] };
    expect(() => parseSweepOutput({ text: '', structured: bad })).toThrow(/id/);
  });
  it('throws on invalid status', () => {
    const bad = { ...GOOD, openLoops: [{ ...GOOD.openLoops[0], status: 'wontfix' }] };
    expect(() => parseSweepOutput({ text: '', structured: bad })).toThrow(/status/);
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd plugins/familiar && npx vitest run src/lib/__tests__/output.test.js`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```js
// plugins/familiar/src/lib/output.js
export const SWEEP_JSON_SCHEMA = {
  type: 'object',
  required: ['briefingMarkdown', 'memoryMarkdown', 'openLoops', 'decisions'],
  properties: {
    briefingMarkdown: { type: 'string' },
    memoryMarkdown: { type: 'string' },
    openLoops: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'text', 'sourcePath', 'firstSeen', 'status'],
        properties: {
          id: { type: 'string', pattern: '^loop-[a-z0-9-]+$' },
          text: { type: 'string' },
          owedTo: { type: ['string', 'null'] },
          sourcePath: { type: 'string' },
          firstSeen: { type: 'string', pattern: '^\\d{4}-\\d{2}-\\d{2}$' },
          status: { type: 'string', enum: ['open', 'done', 'stale'] },
        },
      },
    },
    decisions: {
      type: 'array',
      items: {
        type: 'object',
        required: ['date', 'text', 'sourcePath'],
        properties: {
          date: { type: 'string', pattern: '^\\d{4}-\\d{2}-\\d{2}$' },
          text: { type: 'string' },
          sourcePath: { type: 'string' },
        },
      },
    },
  },
};

const LOOP_ID_RE = /^loop-[a-z0-9-]+$/;
const STATUSES = new Set(['open', 'done', 'stale']);

function extractJson(text) {
  const fenced = /```(?:json)?\s*\n([\s\S]*?)\n```/.exec(text);
  const raw = fenced ? fenced[1] : text;
  try {
    return JSON.parse(raw);
  } catch (e) {
    throw new Error(`output is not valid JSON: ${e.message}`);
  }
}

export function parseSweepOutput(res) {
  const data = res.structured ?? extractJson(res.text ?? '');
  for (const k of ['briefingMarkdown', 'memoryMarkdown', 'openLoops', 'decisions']) {
    if (!(k in (data ?? {}))) throw new Error(`output missing key: ${k}`);
  }
  if (typeof data.briefingMarkdown !== 'string' || typeof data.memoryMarkdown !== 'string') {
    throw new Error('briefingMarkdown/memoryMarkdown must be strings');
  }
  for (const l of data.openLoops) {
    if (!LOOP_ID_RE.test(l.id ?? '')) throw new Error(`bad loop id: ${JSON.stringify(l.id)}`);
    if (!STATUSES.has(l.status)) throw new Error(`bad loop status: ${JSON.stringify(l.status)}`);
    if (typeof l.text !== 'string' || typeof l.sourcePath !== 'string') {
      throw new Error(`loop ${l.id}: text/sourcePath must be strings`);
    }
    l.owedTo ??= null;
  }
  for (const d of data.decisions) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(d.date ?? '')) throw new Error(`bad decision date: ${JSON.stringify(d.date)}`);
  }
  return data;
}
```

```js
// plugins/familiar/src/lib/prompt.js
export const SYSTEM_PROMPT = [
  'You are Familiar, a personal chief of staff reviewing your principal\'s',
  'second-brain vault. You are skeptical and concrete. You never invent',
  'commitments, decisions, or facts: every open loop and decision must be',
  'traceable to a source note, cited by its vault-relative path. You care',
  'about: commitments made and not yet delivered (open loops), decisions',
  'taken, recurring themes, contradictions between stated intent and',
  'observed activity, and blind spots (questions the principal should be',
  'asking). Prose is tight; bullets over paragraphs.',
].join(' ');

export function buildUserPrompt(p) {
  return [
    `# Review window: ${p.windowStart} → ${p.windowEnd}`,
    '',
    '## Your rolling memory (from last run; rewrite it in your output)',
    p.memoryMd || '(first run — no memory yet)',
    '',
    '## Current open-loops tracker',
    p.openLoopsMd || '(empty)',
    '',
    'Dismissed loops are read-only context: never modify, resurrect, or',
    'return them. Return the COMPLETE updated list of every non-dismissed',
    'loop: pass through loops still open, flip status to "done" when the',
    'new notes show completion, "stale" after ~3 weeks without movement,',
    'and append new loops with new ids (slug format: loop-<kebab-case>).',
    '',
    '## Current decisions tracker',
    p.decisionsMd || '(empty)',
    '',
    '## New and changed notes this window',
    p.noteBlocks || '(no changes this window)',
    '',
    ...(p.droppedPaths.length
      ? [
          '## Notes omitted for length (coverage is PARTIAL; say so in the briefing)',
          ...p.droppedPaths.map((x) => `- ${x}`),
          '',
        ]
      : []),
    '## Output',
    'Return ONLY a JSON object matching the provided schema:',
    '{briefingMarkdown, memoryMarkdown, openLoops, decisions}.',
    'briefingMarkdown: the weekly briefing — sections: Themes, Open loops',
    '(summary of notable ones), Decisions, Contradictions, Blind spots.',
    'memoryMarkdown: your rewritten rolling memory — active themes,',
    'watch-list, condensed history. decisions: ONLY decisions newly seen',
    'this window.',
  ].join('\n');
}
```

- [ ] **Step 4: Run tests**

Run: `cd plugins/familiar && npx vitest run`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/familiar/src/lib/prompt.js plugins/familiar/src/lib/output.js plugins/familiar/src/lib/__tests__/output.test.js
git commit -m "feat(familiar): sweep prompt builder and output contract validation"
```

---

### Task 11: `lib/sweep.js` + real `main.js` — orchestration

**Files:**
- Create: `plugins/familiar/src/lib/sweep.js`
- Rewrite: `plugins/familiar/src/main.js`
- Test: `plugins/familiar/src/lib/__tests__/sweep.test.js`

**Interfaces:**
- Consumes: everything from Tasks 7–10; `ctx.api.fetch` (Task 2); sidecar endpoints `GET /v1/activity?date=&windowMinutes=1440`, `GET /v1/notes?path=` (→ `{path, title, body, frontmatter}`), `PUT /v1/notes` (Task 4), `POST /v1/llm/run` (Task 5).
- Produces:
  - `runSweep(deps): Promise<RunReport>` where `deps = {api: {fetch}, settings: {model, budgetChars}, state: {lastSuccessfulRunAt?}, now: Date, log}`.
  - `RunReport = {ok: boolean, error?: string, briefingPath?: string, windowStart, windowEnd, noteCount, droppedCount, costUsd?: number|null}`.
  - Vault paths (exported consts): `MEMORY_PATH = 'Familiar/memory.md'`, `LOOPS_PATH = 'Familiar/open-loops.md'`, `DECISIONS_PATH = 'Familiar/decisions.md'`, `briefingPath(ymd) = 'Familiar/briefings/<ymd>.md'`.
  - Plugin IPC channels (main.js): `status` → `{running, nextRunAt, config, lastRuns}`; `run` → `{started: true} | {started: false, reason}`; `config:set(config)`; event `run:finished(RunReport)`.

- [ ] **Step 1: Write failing tests**

Build a fake `api.fetch` backed by an in-memory route table + note store; assert the full pipeline:

```js
// plugins/familiar/src/lib/__tests__/sweep.test.js
import { beforeEach, describe, expect, it } from 'vitest';
import { runSweep, MEMORY_PATH, LOOPS_PATH, DECISIONS_PATH } from '../sweep.js';
import { parseOpenLoops, renderOpenLoops } from '../trackers.js';

const GOOD_OUTPUT = {
  briefingMarkdown: '# Briefing\nAll clear.',
  memoryMarkdown: '# Memory\nTheme: plugins.',
  openLoops: [{ id: 'loop-ship-familiar', text: 'Ship Familiar', owedTo: null, sourcePath: '10-daily/2026-07-07.md', firstSeen: '2026-07-07', status: 'open' }],
  decisions: [{ date: '2026-07-07', text: 'Familiar is a plugin', sourcePath: '10-daily/2026-07-07.md' }],
};

function makeFakeApi({ llmResponses }) {
  const notes = new Map();       // path -> body
  const puts = [];               // recorded PUT payloads
  const llmCalls = [];
  const api = {
    fetch: async (method, path, body) => {
      if (method === 'GET' && path.startsWith('/v1/activity')) {
        return { ok: true, data: [{ path: '10-daily/2026-07-07.md' }, { path: 'Familiar/memory.md' }] };
      }
      if (method === 'GET' && path.startsWith('/v1/notes?path=')) {
        const p = decodeURIComponent(path.slice('/v1/notes?path='.length));
        if (!notes.has(p)) return { ok: false, error: 'Note not found', status: 404 };
        return { ok: true, data: { path: p, title: p, body: notes.get(p), frontmatter: {} } };
      }
      if (method === 'PUT' && path === '/v1/notes') {
        puts.push(body);
        notes.set(body.path, body.content);
        return { ok: true, data: { path: body.path, created: true } };
      }
      if (method === 'POST' && path === '/v1/llm/run') {
        llmCalls.push(body);
        return { ok: true, data: llmResponses[Math.min(llmCalls.length - 1, llmResponses.length - 1)] };
      }
      throw new Error(`unexpected call: ${method} ${path}`);
    },
  };
  return { api, notes, puts, llmCalls };
}

const DEPS = (api) => ({
  api,
  settings: { model: 'sonnet', budgetChars: 150000 },
  state: { lastSuccessfulRunAt: new Date(2026, 6, 6, 7, 0).toISOString() },
  now: new Date(2026, 6, 8, 7, 0),
  log: () => {},
});

describe('runSweep', () => {
  let fake;
  beforeEach(() => {
    fake = makeFakeApi({ llmResponses: [{ text: '', structured: GOOD_OUTPUT, error: null, costUsd: 0.4, durationMs: 5 }] });
    fake.notes.set('10-daily/2026-07-07.md', 'daily note body');
  });

  it('happy path writes briefing, memory, and both trackers', async () => {
    const report = await runSweep(DEPS(fake.api));
    expect(report.ok).toBe(true);
    expect(report.briefingPath).toBe('Familiar/briefings/2026-07-08.md');
    const paths = fake.puts.map((p) => p.path);
    expect(paths).toEqual(expect.arrayContaining([
      'Familiar/briefings/2026-07-08.md', MEMORY_PATH, LOOPS_PATH, DECISIONS_PATH,
    ]));
    expect(fake.notes.get(LOOPS_PATH)).toContain('loop-ship-familiar');
    expect(fake.notes.get('Familiar/briefings/2026-07-08.md')).toContain('type: familiar-briefing');
  });

  it('excludes Familiar/ notes from the delta it sends the model', async () => {
    fake.notes.set(MEMORY_PATH, '# Memory');
    await runSweep(DEPS(fake.api));
    const prompt = fake.llmCalls[0].prompt;
    expect(prompt).not.toContain('<note path="Familiar/');
  });

  it('retries once on parse failure, then succeeds', async () => {
    fake = makeFakeApi({
      llmResponses: [
        { text: 'not json at all', structured: null, error: null },
        { text: '', structured: GOOD_OUTPUT, error: null },
      ],
    });
    fake.notes.set('10-daily/2026-07-07.md', 'x');
    const report = await runSweep(DEPS(fake.api));
    expect(report.ok).toBe(true);
    expect(fake.llmCalls.length).toBe(2);
    expect(fake.llmCalls[1].prompt).toContain('not valid JSON');
  });

  it('fails after second parse failure without touching trackers, exposing raw output', async () => {
    fake = makeFakeApi({ llmResponses: [{ text: 'bad', structured: null, error: null }] });
    fake.notes.set('10-daily/2026-07-07.md', 'x');
    const report = await runSweep(DEPS(fake.api));
    expect(report.ok).toBe(false);
    expect(report.rawOutput).toBe('bad');
    expect(fake.puts).toEqual([]);
  });

  it('user dismissal mid-run survives write-back', async () => {
    // tracker on disk already has the loop dismissed; model returns it open
    fake.notes.set(LOOPS_PATH, renderOpenLoops(
      [{ ...GOOD_OUTPUT.openLoops[0], status: 'dismissed' }], [],
    ));
    fake.notes.set('10-daily/2026-07-07.md', 'x');
    await runSweep(DEPS(fake.api));
    const { loops } = parseOpenLoops(fake.notes.get(LOOPS_PATH));
    expect(loops[0].status).toBe('dismissed');
  });

  it('propagates llm endpoint error', async () => {
    fake = makeFakeApi({ llmResponses: [{ text: '', structured: null, error: 'LLMError: boom' }] });
    fake.notes.set('10-daily/2026-07-07.md', 'x');
    const report = await runSweep(DEPS(fake.api));
    expect(report.ok).toBe(false);
    expect(report.error).toContain('boom');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd plugins/familiar && npx vitest run src/lib/__tests__/sweep.test.js`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `lib/sweep.js`**

```js
// plugins/familiar/src/lib/sweep.js
import { extractPaths, listDays } from './delta.js';
import { renderNoteBlocks, trimToBudget } from './budget.js';
import { buildUserPrompt, SYSTEM_PROMPT } from './prompt.js';
import { parseSweepOutput, SWEEP_JSON_SCHEMA } from './output.js';
import {
  mergeDecisions, mergeLoops, parseDecisions, parseOpenLoops,
  renderDecisions, renderOpenLoops,
} from './trackers.js';

export const MEMORY_PATH = 'Familiar/memory.md';
export const LOOPS_PATH = 'Familiar/open-loops.md';
export const DECISIONS_PATH = 'Familiar/decisions.md';
export const briefingPath = (ymd) => `Familiar/briefings/${ymd}.md`;

function localYmd(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

async function getJson(api, path) {
  const r = await api.fetch('GET', path);
  if (!r.ok) throw new Error(`GET ${path}: ${r.error}`);
  return r.data;
}

/** Read a note body; missing note (404) → null, other failures throw. */
async function readNote(api, notePath) {
  const r = await api.fetch('GET', `/v1/notes?path=${encodeURIComponent(notePath)}`);
  if (r.ok) return r.data.body;
  if (r.status === 404) return null;
  throw new Error(`read ${notePath}: ${r.error}`);
}

async function writeNote(api, notePath, content) {
  const r = await api.fetch('PUT', '/v1/notes', { path: notePath, content });
  if (!r.ok) throw new Error(`write ${notePath}: ${r.error}`);
}

export async function runSweep(deps) {
  const { api, settings, state, now, log } = deps;
  const windowStart = state.lastSuccessfulRunAt
    ?? new Date(now.getTime() - 7 * 24 * 3600 * 1000).toISOString();
  const windowEnd = now.toISOString();
  const report = {
    ok: false, windowStart, windowEnd, noteCount: 0, droppedCount: 0, costUsd: null,
  };

  try {
    // 1. delta paths from the activity feed, one call per day in the window
    const pathSet = [];
    for (const day of listDays(windowStart, windowEnd)) {
      const rows = await getJson(api, `/v1/activity?date=${day}&windowMinutes=1440`);
      pathSet.push(...rows);
    }
    const paths = extractPaths(pathSet);

    // 2. full text of every delta note (dropped from the feed if unreadable)
    const notes = [];
    for (const p of paths) {
      const body = await readNote(api, p);
      if (body !== null) notes.push({ path: p, modified: '', text: body });
    }
    const { kept, dropped } = trimToBudget(notes, settings.budgetChars);
    report.noteCount = kept.length;
    report.droppedCount = dropped.length;

    // 3. current memory + trackers
    const memoryMd = (await readNote(api, MEMORY_PATH)) ?? '';
    const loopsMd = (await readNote(api, LOOPS_PATH)) ?? '';
    const decisionsMd = (await readNote(api, DECISIONS_PATH)) ?? '';

    // 4. LLM call, one retry on contract violation
    const userPrompt = buildUserPrompt({
      memoryMd, openLoopsMd: loopsMd, decisionsMd,
      noteBlocks: renderNoteBlocks(kept), droppedPaths: dropped,
      windowStart, windowEnd,
    });
    let output = null;
    let lastErr = null;
    let lastRawText = '';
    for (let attempt = 0; attempt < 2 && !output; attempt++) {
      const prompt = lastErr
        ? `${userPrompt}\n\nYour previous output was rejected: ${lastErr}. Return ONLY the JSON object.`
        : userPrompt;
      const r = await api.fetch('POST', '/v1/llm/run', {
        prompt, system: SYSTEM_PROMPT, model: settings.model,
        jsonSchema: SWEEP_JSON_SCHEMA, timeoutSeconds: 840,
      });
      if (!r.ok) throw new Error(`llm/run transport: ${r.error}`);
      if (r.data.error) throw new Error(`llm/run: ${r.data.error}`);
      report.costUsd = (report.costUsd ?? 0) + (r.data.costUsd ?? 0);
      lastRawText = r.data.text ?? '';
      try {
        output = parseSweepOutput(r.data);
      } catch (e) {
        lastErr = e.message;
        log(`sweep output rejected (attempt ${attempt + 1}): ${e.message}`);
      }
    }
    if (!output) {
      report.rawOutput = lastRawText; // main.js persists this to dataDir for debugging
      throw new Error(`output contract violated twice: ${lastErr}`);
    }

    // 5. merge trackers against a FRESH read (user may have edited mid-run)
    const freshLoops = parseOpenLoops((await readNote(api, LOOPS_PATH)) ?? '');
    const mergedLoops = mergeLoops(freshLoops.loops, output.openLoops);
    const freshDecisions = parseDecisions((await readNote(api, DECISIONS_PATH)) ?? '');
    const mergedDecisions = mergeDecisions(freshDecisions, output.decisions);

    // 6. write-back — briefing first (worst crash outcome: briefing without
    //    tracker update, repaired by the next run)
    const ymd = localYmd(now);
    const briefing = [
      '---',
      'type: familiar-briefing',
      `window: ${windowStart}..${windowEnd}`,
      `notes: ${kept.length}`,
      `dropped: ${dropped.length}`,
      `created: ${windowEnd}`,
      '---',
      '',
      output.briefingMarkdown,
    ].join('\n');
    await writeNote(api, briefingPath(ymd), briefing);
    await writeNote(api, MEMORY_PATH, output.memoryMarkdown);
    await writeNote(api, LOOPS_PATH, renderOpenLoops(mergedLoops, freshLoops.unparsed));
    await writeNote(api, DECISIONS_PATH, renderDecisions(mergedDecisions));

    report.ok = true;
    report.briefingPath = briefingPath(ymd);
    return report;
  } catch (e) {
    report.error = e instanceof Error ? e.message : String(e);
    return report;
  }
}
```

- [ ] **Step 4: Run sweep tests**

Run: `cd plugins/familiar && npx vitest run`
Expected: PASS.

- [ ] **Step 5: Rewrite `src/main.js`**

```js
// plugins/familiar/src/main.js
import { readFileSync, writeFileSync, appendFileSync, mkdirSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { isRunDue, nextRunAt } from './lib/schedule.js';
import { runSweep } from './lib/sweep.js';

const TICK_MS = 15 * 60 * 1000;
const FIRST_TICK_MS = 30 * 1000;
const STALE_RUN_MS = 30 * 60 * 1000;
const DEFAULT_CONFIG = { cadence: 'weekly', day: 'monday', hour: 7, model: 'sonnet', budgetChars: 150000 };

let ctx = null;
let timer = null;
let firstTimer = null;
let running = false;

const statePath = () => join(ctx.dataDir, 'state.json');
const runsPath = () => join(ctx.dataDir, 'runs.jsonl');

function loadState() {
  try {
    return JSON.parse(readFileSync(statePath(), 'utf-8'));
  } catch {
    return {};
  }
}

function saveState(state) {
  mkdirSync(ctx.dataDir, { recursive: true });
  writeFileSync(statePath(), JSON.stringify(state, null, 2));
}

function config() {
  return { ...DEFAULT_CONFIG, ...(ctx.settings.get('config') ?? {}) };
}

function lastRuns(n = 10) {
  try {
    return readFileSync(runsPath(), 'utf-8').trim().split('\n').slice(-n).map((l) => JSON.parse(l));
  } catch {
    return [];
  }
}

async function sweep(trigger) {
  const state = loadState();
  if (running) return { started: false, reason: 'already running' };
  if (state.runningSince && Date.now() - new Date(state.runningSince).getTime() < STALE_RUN_MS) {
    return { started: false, reason: 'run in progress' };
  }
  running = true;
  saveState({ ...state, runningSince: new Date().toISOString(), lastAttemptAt: new Date().toISOString() });
  const cfg = config();
  const startedAt = new Date().toISOString();
  let report;
  try {
    report = await runSweep({
      api: ctx.api,
      settings: { model: cfg.model, budgetChars: cfg.budgetChars },
      state,
      now: new Date(),
      log: ctx.log,
    });
  } catch (e) {
    report = { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
  running = false;
  const next = loadState();
  delete next.runningSince;
  if (report.ok) next.lastSuccessfulRunAt = report.windowEnd;
  saveState(next);
  mkdirSync(ctx.dataDir, { recursive: true });
  if (report.rawOutput) {
    // rejected LLM output, kept for debugging (spec §2.1); too big for runs.jsonl
    writeFileSync(join(ctx.dataDir, `failed-${Date.now()}.txt`), report.rawOutput);
    delete report.rawOutput;
  }
  appendFileSync(runsPath(), JSON.stringify({ startedAt, finishedAt: new Date().toISOString(), trigger, ...report }) + '\n');
  ctx.ipc.send('run:finished', report);
  ctx.log(`sweep ${report.ok ? 'ok' : `FAILED: ${report.error}`}`);
  return { started: true };
}

function tick() {
  if (isRunDue(config(), loadState(), new Date())) void sweep('schedule');
}

export function activate(context) {
  ctx = context;
  ctx.ipc.handle('status', () => ({
    running,
    nextRunAt: nextRunAt(config(), new Date()).toISOString(),
    lastSuccessfulRunAt: loadState().lastSuccessfulRunAt ?? null,
    config: config(),
    lastRuns: lastRuns(),
  }));
  ctx.ipc.handle('run', () => sweep('manual'));
  ctx.ipc.handle('config:set', (partial) => {
    if (typeof partial !== 'object' || partial === null) throw new Error('config must be an object');
    ctx.settings.set('config', { ...config(), ...partial });
    return config();
  });
  timer = setInterval(tick, TICK_MS);
  firstTimer = setTimeout(tick, FIRST_TICK_MS); // catch-up shortly after launch
}

export function deactivate() {
  if (timer) clearInterval(timer);
  if (firstTimer) clearTimeout(firstTimer);
  timer = firstTimer = null;
  ctx = null;
}
```

- [ ] **Step 6: Build + full plugin test run**

Run: `cd plugins/familiar && npm run build && npx vitest run`
Expected: build succeeds, all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add plugins/familiar/src plugins/familiar/dist
git commit -m "feat(familiar): sweep orchestration, scheduling tick, run audit trail"
```

---

### Task 12: `renderer.js` — the Familiar screen

**Files:**
- Rewrite: `plugins/familiar/src/renderer.js`
- Create: `plugins/familiar/src/lib/ui.js` (pure render helpers)
- Test: `plugins/familiar/src/lib/__tests__/ui.test.js`

**Interfaces:**
- Consumes: `PluginApi` (`api.fetch`, `ipc.invoke/on`, `theme`); IPC channels from Task 11; tracker lib from Task 9; `marked` for markdown.
- Produces: `mount(el, api): () => void` rendering the full screen.

- [ ] **Step 1: Write failing tests for the pure helpers**

Keep DOM assembly untested (manual); test the two decision-carrying helpers:

```js
// plugins/familiar/src/lib/__tests__/ui.test.js
import { describe, expect, it } from 'vitest';
import { statusLine, toggleLoop } from '../ui.js';

const LOOP = { id: 'loop-a', text: 't', owedTo: null, sourcePath: 'a.md', firstSeen: '2026-07-01', status: 'open' };

describe('toggleLoop', () => {
  it('open → done and back', () => {
    expect(toggleLoop(LOOP).status).toBe('done');
    expect(toggleLoop({ ...LOOP, status: 'done' }).status).toBe('open');
  });
  it('stale toggles to done', () => {
    expect(toggleLoop({ ...LOOP, status: 'stale' }).status).toBe('done');
  });
});

describe('statusLine', () => {
  it('describes a healthy idle state', () => {
    const s = statusLine({ running: false, lastRuns: [{ ok: true, finishedAt: '2026-07-06T07:05:00Z' }], nextRunAt: '2026-07-13T07:00:00.000Z' });
    expect(s).toContain('Next run');
    expect(s).not.toContain('failed');
  });
  it('surfaces a failed last run', () => {
    const s = statusLine({ running: false, lastRuns: [{ ok: false, error: 'boom' }], nextRunAt: '2026-07-13T07:00:00.000Z' });
    expect(s).toContain('failed');
    expect(s).toContain('boom');
  });
  it('shows running state', () => {
    expect(statusLine({ running: true, lastRuns: [], nextRunAt: null })).toContain('Running');
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd plugins/familiar && npx vitest run src/lib/__tests__/ui.test.js`
Expected: FAIL.

- [ ] **Step 3: Implement `lib/ui.js`**

```js
// plugins/familiar/src/lib/ui.js
export function toggleLoop(loop) {
  return { ...loop, status: loop.status === 'done' ? 'open' : 'done' };
}

export function statusLine(status) {
  if (status.running) return 'Running sweep…';
  const last = status.lastRuns[status.lastRuns.length - 1];
  const parts = [];
  if (last && !last.ok) parts.push(`Last run failed: ${last.error}`);
  else if (last) parts.push(`Last run ${new Date(last.finishedAt).toLocaleString()}`);
  if (status.nextRunAt) parts.push(`Next run ${new Date(status.nextRunAt).toLocaleString()}`);
  return parts.join(' · ') || 'No runs yet';
}
```

- [ ] **Step 4: Implement `renderer.js`**

Structure (full file; adapt visual polish freely but keep the behavior):

```js
// plugins/familiar/src/renderer.js
import { marked } from 'marked';
import { parseOpenLoops, renderOpenLoops, parseDecisions } from './lib/trackers.js';
import { statusLine, toggleLoop } from './lib/ui.js';

const LOOPS_PATH = 'Familiar/open-loops.md';

async function readNote(api, path) {
  const r = await api.api.fetch('GET', `/v1/notes?path=${encodeURIComponent(path)}`);
  return r.ok ? r.data.body : null;
}

export function mount(el, api) {
  el.innerHTML = '';
  const root = document.createElement('div');
  root.style.cssText = `padding:24px;max-width:860px;margin:0 auto;color:${api.theme['--ink-0'] || 'inherit'};font-size:14px;`;
  el.appendChild(root);

  const header = document.createElement('div');
  header.style.cssText = 'display:flex;align-items:center;gap:12px;margin-bottom:16px;';
  const title = document.createElement('h1');
  title.textContent = 'Familiar';
  title.style.cssText = 'font-size:20px;margin:0;flex:1;';
  const status = document.createElement('span');
  status.style.cssText = `color:${api.theme['--ink-2'] || '#888'};font-size:12px;`;
  const runBtn = document.createElement('button');
  runBtn.textContent = 'Run now';
  header.append(title, status, runBtn);
  root.appendChild(header);

  const sections = {
    briefing: document.createElement('section'),
    loops: document.createElement('section'),
    decisions: document.createElement('section'),
    history: document.createElement('section'),
    settings: document.createElement('section'),
  };
  for (const s of Object.values(sections)) root.appendChild(s);

  async function refreshStatus() {
    const st = await api.ipc.invoke('status');
    status.textContent = statusLine(st);
    runBtn.disabled = st.running;
    return st;
  }

  async function renderBriefing(st) {
    const runs = (st.lastRuns ?? []).filter((r) => r.ok && r.briefingPath);
    const latest = runs[runs.length - 1];
    sections.briefing.innerHTML = '<h2>Latest briefing</h2>';
    if (!latest) {
      sections.briefing.insertAdjacentHTML('beforeend', '<p>No briefing yet — hit “Run now”.</p>');
      return;
    }
    const body = await readNote(api, latest.briefingPath);
    sections.briefing.insertAdjacentHTML('beforeend', body ? marked.parse(body) : '<p>(briefing note missing)</p>');
    sections.history.innerHTML = '<h2>History</h2>' + runs
      .slice(0, -1)
      .reverse()
      .map((r) => `<div>${r.briefingPath}</div>`)
      .join('');
  }

  async function renderLoops() {
    const body = (await readNote(api, LOOPS_PATH)) ?? '';
    const { loops, unparsed } = parseOpenLoops(body);
    sections.loops.innerHTML = '<h2>Open loops</h2>';
    for (const loop of loops.filter((l) => l.status !== 'dismissed')) {
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;gap:8px;align-items:baseline;padding:4px 0;';
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.checked = loop.status === 'done';
      const label = document.createElement('span');
      label.textContent = `${loop.text}${loop.owedTo ? ` — owed to ${loop.owedTo}` : ''}${loop.status === 'stale' ? ' (stale)' : ''}`;
      if (loop.status === 'done') label.style.textDecoration = 'line-through';
      const dismiss = document.createElement('button');
      dismiss.textContent = 'dismiss';
      dismiss.style.cssText = 'margin-left:auto;font-size:11px;';
      const save = async (updated) => {
        const fresh = parseOpenLoops((await readNote(api, LOOPS_PATH)) ?? '');
        const next = fresh.loops.map((l) => (l.id === updated.id ? updated : l));
        await api.api.fetch('PUT', '/v1/notes', { path: LOOPS_PATH, content: renderOpenLoops(next, fresh.unparsed) });
        await renderLoops();
      };
      box.onchange = () => void save(toggleLoop(loop));
      dismiss.onclick = () => void save({ ...loop, status: 'dismissed' });
      row.append(box, label, dismiss);
      sections.loops.appendChild(row);
    }
    if (unparsed.length) {
      sections.loops.insertAdjacentHTML('beforeend', `<p style="opacity:.6">${unparsed.length} hand-edited line(s) preserved in the note.</p>`);
    }
  }

  async function renderDecisionLog() {
    const body = (await readNote(api, 'Familiar/decisions.md')) ?? '';
    const list = parseDecisions(body);
    sections.decisions.innerHTML = '<h2>Decisions</h2>' + list
      .slice()
      .reverse()
      .map((d) => `<div>${d.date} — ${d.text}</div>`)
      .join('');
  }

  function renderSettings(st) {
    const cfg = st.config;
    sections.settings.innerHTML = '<h2>Settings</h2>';
    const form = document.createElement('div');
    form.style.cssText = 'display:flex;gap:8px;align-items:center;flex-wrap:wrap;';
    const day = document.createElement('select');
    for (const d of ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']) {
      const o = document.createElement('option');
      o.value = d;
      o.textContent = d;
      o.selected = d === cfg.day;
      day.appendChild(o);
    }
    const hour = document.createElement('input');
    hour.type = 'number';
    hour.min = '0';
    hour.max = '23';
    hour.value = String(cfg.hour);
    hour.style.width = '56px';
    const model = document.createElement('select');
    for (const m of ['haiku', 'sonnet', 'opus']) {
      const o = document.createElement('option');
      o.value = m;
      o.textContent = m;
      o.selected = m === cfg.model;
      model.appendChild(o);
    }
    const budget = document.createElement('input');
    budget.type = 'number';
    budget.step = '10000';
    budget.value = String(cfg.budgetChars);
    budget.style.width = '96px';
    const save = document.createElement('button');
    save.textContent = 'Save';
    save.onclick = async () => {
      await api.ipc.invoke('config:set', {
        day: day.value,
        hour: Number(hour.value),
        model: model.value,
        budgetChars: Number(budget.value),
      });
      await refreshStatus();
    };
    form.append('Weekly on', day, 'at', hour, ':00 · model', model, '· budget (chars)', budget, save);
    sections.settings.appendChild(form);
  }

  async function refreshAll() {
    const st = await refreshStatus();
    renderSettings(st);
    await Promise.all([renderBriefing(st), renderLoops(), renderDecisionLog()]);
  }

  runBtn.onclick = async () => {
    const r = await api.ipc.invoke('run');
    if (r?.started === false) status.textContent = r.reason;
    await refreshStatus();
  };
  const off = api.ipc.on('run:finished', () => void refreshAll());
  void refreshAll();

  return () => off();
}
```

- [ ] **Step 5: Build, test, typecheck nothing (plain JS) — run vitest**

Run: `cd plugins/familiar && npm run build && npx vitest run`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add plugins/familiar/src plugins/familiar/dist
git commit -m "feat(familiar): briefing screen with open-loop check-off and run-now"
```

---

### Task 13: End-to-end verification and spec corrections

**Files:**
- Possibly modify: spec doc (corrections), any file where E2E shakes out a bug.

- [ ] **Step 1: Full test suites**

Run all three:
```bash
.venv/bin/pytest ghostbrain/api/tests/ -q
cd desktop && npx vitest run && npx tsc --noEmit && cd ..
cd plugins/familiar && npx vitest run && cd ../..
```
Expected: all PASS.

- [ ] **Step 2: Manual E2E (use the superpowers:verification-before-completion skill)**

1. `cd plugins/familiar && npm run build`.
2. Launch the desktop app (dev). Plugins screen → Install from folder (or Reload if already installed) → Familiar appears in the sidebar.
3. Open Familiar → "No briefing yet" → **Run now**.
4. Watch the main log for `[plugin:familiar]`; the sweep should finish (minutes — real `claude -p` call).
5. Verify in the vault: `Familiar/briefings/<today>.md`, `Familiar/memory.md`, `Familiar/open-loops.md`, `Familiar/decisions.md` exist with sane content; briefing renders in the plugin screen.
6. Check off one open loop → the checkbox persists after app restart; the note on disk shows `[x]`.
7. Dismiss one loop → gone from the UI, `{dismissed}` in the note.
8. Run now a second time → dismissed loop is NOT resurrected; second briefing appears in History.
9. Search the vault (app search) for a phrase from the briefing → it's indexed.

- [ ] **Step 3: Spec corrections**

If implementation diverged from the spec (it will somewhere), update the spec doc and commit as `docs: spec corrections from implementation (familiar)` — same pattern as commit `7688def`.

- [ ] **Step 4: Final commit / branch state**

```bash
git status   # everything committed
git log --oneline -15
```

Hand back to the user for the finishing-a-development-branch flow (this work sits on `feat/plugin-system` alongside the plugin-system commits).
