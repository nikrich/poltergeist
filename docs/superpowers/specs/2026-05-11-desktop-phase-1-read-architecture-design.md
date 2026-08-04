# Ghostbrain Desktop — Phase 1: Read Architecture

**Date:** 2026-05-11
**Status:** drafted, pending approval
**Depends on:** Slice 1 (merged), Slice 1.5 Cleanup (merged), light-mode fix (merged)
**Author:** brainstormed with Jannik

## Context

The desktop app today renders six screens at design fidelity but every byte of data on them is mocked. The user wants real data wired through — Today's stats and agenda, the capture inbox, the connector states, meeting history — without waiting for a backend rewrite, and **without throwing this architecture away when writes / recording / OAuth / installer come next**.

Phase 1 = read-only end-to-end, using the architecture that survives into Phase 2/3:

```
Renderer  ──IPC──>  Electron main  ──HTTP(localhost+token)──>  Python sidecar  ──>  vault on disk
  React              spawn lifecycle           FastAPI                    existing ghostbrain.*
  React Query        token in main only        Pydantic schemas           (paths, connectors, recorder, etc.)
```

The Python side ships a new `ghostbrain.api` package — a FastAPI app that imports the existing `ghostbrain.paths`, reads `ghostbrain/connectors/*`, walks the vault, and exposes the data as a typed JSON API. **The existing `ghostbrain.*` modules (worker, recorder, connectors, scripts, console_scripts, tests, pyproject.toml entries) are not modified.** `ghostbrain.api` is purely additive.

Phase 2 adds endpoints (`POST /v1/connectors/{id}/sync`, `POST /v1/meetings/start`, OAuth flows, search), a WebSocket event channel, PyInstaller bundling of the sidecar, code signing, and the installer. None of that work invalidates the Phase 1 architecture — it adds endpoints to the same FastAPI app and wraps the binary differently.

## Goals

1. **All six screens read from the real vault** via the sidecar — no more `lib/mocks/`.
2. **Stable typed API contract** between renderer and sidecar — the same surface holds for Phase 2's additions.
3. **Honest empty / loading / error states** on every screen — current code assumes data exists.
4. **Sidecar lifecycle is robust enough for daily use** — auto-start on app launch, graceful shutdown on quit, one auto-restart on crash.
5. **Connector list reflects reality** — drop the mock set (gmail/slack/notion/linear/drive), surface what's actually in `ghostbrain/connectors/` + state dir.

## Non-goals

- **No write endpoints.** No "sync now", no "start recording", no "save to vault", no "ask the archive". Buttons that would write keep their `stub(N)` toasts.
- **No OAuth flows.** Connector OAuth is Phase 2.
- **No WebSocket events.** Phase 1 polls via React Query `refetchInterval`; live push channel is Phase 2.
- **No PyInstaller bundling.** Phase 1's sidecar runs via `python3` from PATH (developer machine). Bundling is Phase 2.
- **No code signing, no installer.** Phase 2.
- **No changes to existing `ghostbrain.*` modules.** New `ghostbrain.api` package only.
- **No changes to existing `ghostbrain-*` console scripts** (`-worker`, `-recorder`, etc.). They keep running unchanged.
- **No new connector implementations.** Phase 1 surfaces whatever connectors already exist; new ones land on the Python side independently.

## Architecture

### Process model

- **Sidecar:** `python3 -m ghostbrain.api`. FastAPI app via uvicorn, bound to `127.0.0.1:<random-port>`. Generates a 256-bit hex token at startup. Prints `READY port=<port> token=<token>` to stdout as the first non-log line, then takes over uvicorn's normal output.
- **Electron main:** On `whenReady`, spawns the sidecar as a child process. Captures stdout, parses the `READY` line, stores port+token. Forwards renderer IPC calls to `http://127.0.0.1:<port>` with `Authorization: Bearer <token>`. On `before-quit`, sends SIGTERM, waits up to 5s, SIGKILL if needed.
- **Renderer:** Never sees the token. Calls `window.gb.api.request(method, path, body)`; main does the HTTP round-trip.

### Auth and security

- Sidecar binds 127.0.0.1 only (not 0.0.0.0). Other machines can't reach it.
- Token required on every request. Sidecar middleware rejects missing/wrong token with `401`.
- Token is single-use per app launch — sidecar generates a fresh one each time.
- Renderer never holds the token; it lives in main and is injected by the IPC forwarder.

### Failure modes

| Failure | What happens |
|---|---|
| `python3` not on PATH | Sidecar fails to spawn. Main fires an IPC event `gb:sidecar:failed` with the reason. Renderer shows a "ghostbrain isn't set up" screen with diagnostic + retry. |
| Sidecar imports fail (e.g. missing `fastapi`) | Sidecar exits with stderr captured. Same error screen. |
| Sidecar never prints `READY` within 10s | Main times out, kills the process, shows error screen. |
| Vault path doesn't exist | Sidecar starts fine; endpoints return data based on empty vault. Renderer shows empty states. Setting → Vault → change is the recovery. |
| Sidecar crashes after startup | Main detects exit, attempts one auto-restart with 2s backoff. If restart fails, shows error toast and disables data fetches until "retry". |
| Endpoint returns `5xx` | React Query retries 2× with exponential backoff. Then surfaces error state in the affected panel. |
| Endpoint returns `401` | Token corruption; main re-fetches port/token by restarting sidecar, retries once. |

### Stack additions

Renderer:
- `@tanstack/react-query` v5 — fetch lifecycle, caching, retries, refetching

Sidecar:
- `fastapi` — web framework
- `uvicorn` — ASGI server
- `pydantic` — schemas (probably already installed via anthropic SDK transitively, verify)

These get added to `pyproject.toml` under a new optional dependency group `[project.optional-dependencies] api`:

```toml
[project.optional-dependencies]
api = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
]
```

Install via `pip install -e ".[api]"` during development. Phase 2's PyInstaller spec will bundle these.

## The sidecar

### Module layout

```
ghostbrain/api/
├── __init__.py          # exports `app: FastAPI`
├── __main__.py          # python -m ghostbrain.api entrypoint (uvicorn + READY banner)
├── main.py              # FastAPI app instantiation, middleware wiring, error handlers
├── auth.py              # Bearer token middleware
├── routes/
│   ├── __init__.py
│   ├── vault.py         # GET /v1/vault/stats
│   ├── connectors.py    # GET /v1/connectors, GET /v1/connectors/{id}
│   ├── captures.py      # GET /v1/captures, GET /v1/captures/{id}
│   ├── meetings.py      # GET /v1/meetings
│   ├── agenda.py        # GET /v1/agenda
│   ├── activity.py      # GET /v1/activity
│   └── suggestions.py   # GET /v1/suggestions
├── models/
│   ├── __init__.py
│   ├── vault.py         # VaultStats
│   ├── connector.py     # Connector, ConnectorState
│   ├── capture.py       # Capture, CaptureSummary
│   ├── meeting.py       # PastMeeting
│   ├── agenda.py        # AgendaItem
│   ├── activity.py      # ActivityRow
│   └── suggestion.py    # Suggestion
└── repo/
    ├── __init__.py
    ├── vault.py         # filesystem reads against vault_path()
    ├── connectors.py    # reads state_dir() and inspects ghostbrain/connectors/
    ├── captures.py      # reads queue_dir() + audit_dir()
    ├── meetings.py      # reads vault/20-contexts/.../meetings/
    └── agenda.py        # reads vault/20-contexts/.../calendar/
```

**Why separate `routes/` and `repo/`:** routes own HTTP concerns (request validation, status codes, OpenAPI metadata). `repo/` modules own the actual vault reading — they're plain functions, unit-testable without spinning up FastAPI.

### Startup sequence

`ghostbrain/api/__main__.py`:

```python
import secrets
import socket
import sys

import uvicorn

from ghostbrain.api.main import create_app


def main() -> None:
    token = secrets.token_hex(32)
    port = _pick_port()
    app = create_app(token=token)

    # Print the READY banner BEFORE uvicorn takes over stdout.
    print(f"READY port={port} token={token}", flush=True)

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info", access_log=False)


def _pick_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


if __name__ == "__main__":
    sys.exit(main() or 0)
```

### Auth middleware

`ghostbrain/api/auth.py`:

```python
from fastapi import HTTPException, Request, status


def make_auth_middleware(token: str):
    async def auth_middleware(request: Request, call_next):
        # /openapi.json is allowed unauthenticated for dev introspection.
        if request.url.path in ("/openapi.json", "/docs", "/redoc"):
            return await call_next(request)
        header = request.headers.get("authorization", "")
        if header != f"Bearer {token}":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        return await call_next(request)
    return auth_middleware
```

Wired in `main.py` via `app.middleware("http")(make_auth_middleware(token))`.

### Endpoints

All paths under `/v1/`. JSON in/out. Pagination via `?limit=&offset=`. Timestamps as RFC 3339 (`"2026-05-11T14:23:00Z"`).

#### `GET /v1/vault/stats`

Returns aggregate counts.

```json
{
  "totalNotes": 2489,
  "queuePending": 12,
  "vaultSizeBytes": 148928000,
  "lastSyncAt": "2026-05-11T13:45:12Z",
  "indexedCount": 27543
}
```

Source: `vault_path()` walk for `*.md` count + `du`-equivalent size; `queue_dir()/pending/` listing count; `state_dir()/*/state.json` for connector last-sync timestamps (take max) and indexed counts (sum).

#### `GET /v1/connectors`

Returns the list of connectors that exist in `ghostbrain/connectors/` + their state.

```json
[
  {
    "id": "github",
    "displayName": "github",
    "state": "on",
    "count": 824,
    "lastSyncAt": "2026-05-11T13:42:00Z",
    "account": "theo-haunts",
    "throughput": "~18 issues/day",
    "error": null
  },
  {
    "id": "slack",
    "displayName": "slack",
    "state": "on",
    "count": 9412,
    "lastSyncAt": "2026-05-11T13:44:00Z",
    "account": "ghostbrain-team",
    "throughput": "~1.2k msgs/day",
    "error": null
  },
  {
    "id": "claude_code",
    "displayName": "Claude Code",
    "state": "off",
    "count": 0,
    "lastSyncAt": null,
    "account": null,
    "throughput": null,
    "error": null
  }
]
```

`id`: directory name under `ghostbrain/connectors/`. `displayName`: looked up from a small static dict in `repo/connectors.py` (`{"claude_code": "Claude Code", "github": "github", ...}`). `state`: `'on'` if state dir exists and has a `last_run` within 24h; `'err'` if the state file has an `error` field; `'off'` otherwise. The other fields come from the connector's `state.json`.

#### `GET /v1/connectors/{id}`

Same shape as the list item plus `scopes`, `pulls` (what types of items it ingests, from a static lookup), `vaultDestination` (the path under the vault where it writes — also a static lookup keyed by connector id).

#### `GET /v1/captures?since=&limit=&source=`

```json
{
  "total": 142,
  "items": [
    {
      "id": "2026-05-11T08:14:23Z-gmail-abc123",
      "source": "gmail",
      "title": "re: design crit moved",
      "snippet": "works for me — moving the 11am to thursday next week...",
      "from": "theo · 8:14am",
      "tags": ["followup"],
      "unread": true,
      "capturedAt": "2026-05-11T08:14:23Z"
    }
  ]
}
```

Source: reads `audit_dir()/<recent>.jsonl` for processed items + `queue_dir()/pending/*.json` for pending. Sorted by `capturedAt` desc. `unread` = "not yet acknowledged in UI" — track via a `read_state.json` in `state_dir()` (renderer would write this, but Phase 1 has no writes — so `unread` defaults to true for items captured in the last 6h, false otherwise. Phase 2 wires actual read state.)

#### `GET /v1/captures/{id}`

Returns the full capture record including the body text and any extracted entities (action items, mentions, links).

#### `GET /v1/meetings?limit=`

```json
{
  "total": 47,
  "items": [
    {
      "id": "2026-05-08-design-crit",
      "title": "design crit · onboarding v3",
      "date": "2026-05-08",
      "dur": "28:14",
      "speakers": 4,
      "tags": ["design"]
    }
  ]
}
```

Source: list `vault_path()/20-contexts/*/meetings/*.md`, parse frontmatter for date/duration/speakers/tags. (Exact path depends on the recorder's output convention — `repo/meetings.py` reads `ghostbrain.recorder.paths` if it exposes one, otherwise hardcodes the convention.)

#### `GET /v1/agenda?date=YYYY-MM-DD`

Returns today's calendar agenda items.

```json
[
  {
    "id": "2026-05-11-11:00-design-crit",
    "time": "11:00",
    "duration": "30m",
    "title": "Design crit · onboarding v3",
    "with": ["mira", "jules", "sam"],
    "status": "upcoming"
  }
]
```

Source: walk `vault_path()/20-contexts/*/calendar/<date>*.md` files. Parse frontmatter for time/duration/attendees. `status`: `'recorded'` if a corresponding meeting file exists in `meetings/`, otherwise `'upcoming'`.

#### `GET /v1/activity?windowMinutes=240`

Returns recent processed-event log.

```json
[
  {
    "id": "2026-05-11T13:42:00Z-gmail-archive-12",
    "source": "gmail",
    "verb": "archived",
    "subject": "3 newsletters",
    "atRelative": "2m",
    "at": "2026-05-11T13:42:00Z"
  }
]
```

Source: `audit_dir()/<today>.jsonl` (and yesterday if `windowMinutes` spans). Map each row's record-type to a verb (archived/captured/linked/indexed/extracted), shorten the subject. Sorted desc by `at`.

#### `GET /v1/suggestions`

Phase 1: returns a small static list of always-on hints, OR derives 2-3 trivial ones (e.g. "Connect drive" if drive is mentioned anywhere in captures). Anything LLM-driven is Phase 2.

```json
[
  {
    "id": "connect-drive",
    "icon": "link",
    "title": "connect drive",
    "body": "3 mentions of shared docs in slack this week — none are indexed.",
    "accent": false
  }
]
```

## The bridge (Electron main)

### Files

- `desktop/src/main/sidecar.ts` — spawn lifecycle, READY parsing, restart logic, shutdown
- `desktop/src/main/api-forwarder.ts` — `forward(method, path, body)` that calls the sidecar with the captured token, returns `{ ok, data | error }`
- `desktop/src/main/index.ts` — wires the above; adds `ipcMain.handle('gb:api:request', ...)`
- `desktop/src/preload/index.ts` — adds `window.gb.api.request<T>(method, path, body?)`
- `desktop/src/shared/types.ts` — `GbApiBridge` interface

### Sidecar lifecycle (`sidecar.ts`)

```ts
import { spawn, type ChildProcess } from 'node:child_process';
import { join } from 'node:path';

interface SidecarInfo {
  port: number;
  token: string;
}

export class Sidecar {
  private process: ChildProcess | null = null;
  private info: SidecarInfo | null = null;
  private restartAttempts = 0;
  // ... event emitter for ready/failed/exited

  async start(repoRoot: string): Promise<SidecarInfo> {
    return new Promise((resolve, reject) => {
      const proc = spawn('python3', ['-m', 'ghostbrain.api'], {
        cwd: repoRoot,
        env: { ...process.env, PYTHONUNBUFFERED: '1' },
      });

      const timeout = setTimeout(() => {
        proc.kill();
        reject(new Error('Sidecar did not become ready within 10s'));
      }, 10_000);

      proc.stdout?.on('data', (chunk: Buffer) => {
        const text = chunk.toString();
        const match = text.match(/^READY port=(\d+) token=([0-9a-f]+)/m);
        if (match) {
          clearTimeout(timeout);
          this.info = { port: parseInt(match[1]!, 10), token: match[2]! };
          this.process = proc;
          resolve(this.info);
        }
      });

      proc.on('exit', (code) => {
        if (!this.info) {
          clearTimeout(timeout);
          reject(new Error(`Sidecar exited with code ${code} before ready`));
        } else {
          // Already running — try one restart with backoff
          this.handleUnexpectedExit(repoRoot, code);
        }
      });
    });
  }

  async stop(): Promise<void> {
    if (!this.process) return;
    this.process.kill('SIGTERM');
    await new Promise<void>((r) => setTimeout(r, 5_000));
    if (!this.process.killed) this.process.kill('SIGKILL');
    this.process = null;
    this.info = null;
  }

  getInfo(): SidecarInfo | null {
    return this.info;
  }

  // private restart logic, capped at 1 attempt with 2s backoff
}
```

The full implementation handles edge cases (process death races, double-start prevention, stderr capture for diagnostics). Plan task will spell it out.

### Forwarder (`api-forwarder.ts`)

```ts
import { Sidecar } from './sidecar';

export async function forward(
  sidecar: Sidecar,
  method: string,
  path: string,
  body?: unknown,
): Promise<{ ok: true; data: unknown } | { ok: false; error: string }> {
  const info = sidecar.getInfo();
  if (!info) return { ok: false, error: 'Sidecar not ready' };
  try {
    const res = await fetch(`http://127.0.0.1:${info.port}${path}`, {
      method,
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${info.token}`,
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!res.ok) {
      const text = await res.text();
      return { ok: false, error: `HTTP ${res.status}: ${text}` };
    }
    const data = await res.json();
    return { ok: true, data };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
}
```

### IPC handler + preload

In `main/index.ts`:

```ts
ipcMain.handle('gb:api:request', async (_e, method: unknown, path: unknown, body: unknown) => {
  if (typeof method !== 'string' || typeof path !== 'string') {
    return { ok: false, error: 'Invalid request shape' };
  }
  // Restrict to /v1/* paths and known methods to prevent the renderer from
  // poking at /openapi.json etc.
  if (!path.startsWith('/v1/') || !['GET', 'POST'].includes(method.toUpperCase())) {
    return { ok: false, error: 'Path not allowed' };
  }
  return forward(sidecar, method.toUpperCase(), path, body);
});
```

In `preload/index.ts`, extend the bridge:

```ts
api: {
  request: <T>(method: 'GET' | 'POST', path: string, body?: unknown) =>
    ipcRenderer.invoke('gb:api:request', method, path, body) as Promise<
      { ok: true; data: T } | { ok: false; error: string }
    >;
}
```

The bridge return type is the existing `{ ok: true } | { ok: false; error: string }` shape extended with `data: T`.

## The renderer

### Data layer

`desktop/src/renderer/lib/api/client.ts` — typed wrapper around `window.gb.api.request`:

```ts
async function get<T>(path: string): Promise<T> {
  const result = await window.gb.api.request<T>('GET', path);
  if (!result.ok) throw new Error(result.error);
  return result.data;
}
```

`desktop/src/renderer/lib/api/hooks.ts` — React Query hooks. One per resource:

```ts
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
  });
}

// ... etc for captures, meetings, agenda, activity, suggestions
```

`@tanstack/react-query` v5 is the modern fetch state library. Defaults: 2 retries with exponential backoff, refetch on window focus.

### Per-screen migration

Each screen replaces its `import { MOCK } from '../lib/mocks/...'` with the corresponding hook. Components add loading/empty/error UI.

Today screen example:

```tsx
const stats = useVaultStats();
const agenda = useAgenda();
const activity = useRecentActivity();
const connectors = useConnectors();
const captures = useCaptures({ limit: 3 });

return (
  <div>
    <Panel title="agenda" subtitle="2 events · today">
      {agenda.isLoading && <SkeletonRows count={3} />}
      {agenda.isError && <PanelError onRetry={agenda.refetch} />}
      {agenda.data && agenda.data.length === 0 && <PanelEmpty message="no events today" />}
      {agenda.data?.map((item) => <AgendaItem key={item.id} {...item} />)}
    </Panel>
    {/* ... */}
  </div>
);
```

New components for loading/empty/error states:

- `components/SkeletonRows.tsx` — N grey shimmer rows
- `components/PanelEmpty.tsx` — neutral empty state with optional CTA
- `components/PanelError.tsx` — error message + retry button

These are tiny (~20 lines each) and reused across screens.

### Mocks deletion

After every screen consumes real hooks, `desktop/src/renderer/lib/mocks/` is deleted. Type definitions that lived in those files move to `desktop/src/shared/api-types.ts` (mirroring the Pydantic schemas).

### First-run UI

If the bridge reports the sidecar isn't ready (via a small new state in `useSettings` or a dedicated `useSidecar()` hook), the renderer shows a setup screen:

- Title: "ghostbrain isn't running"
- Body: "the python backend failed to start. detail: {error}"
- Button: "retry" — calls `window.gb.sidecar.restart()`

The screen replaces the normal app render entirely while the sidecar is down.

## Connector list reconciliation

The mocks reference `gmail/slack/notion/linear/calendar/github/drive`. Real connectors per `ghostbrain/connectors/` directory listing (post-merge of recent work): `claude_code, github, jira, confluence, calendar, atlassian, slack, gmail` (the user has been actively adding to this).

Phase 1 changes:
- The sidecar's `repo/connectors.py` enumerates `ghostbrain/connectors/` directory entries and returns whatever's there.
- The static lookup dict in `repo/connectors.py` maps id → display metadata (name, color, vault destination). Adding a new connector requires adding to this dict — small dev tax, but explicit.
- Renderer code is unchanged structurally; it just renders whatever the endpoint returns.
- Missing logos for `claude_code, jira, confluence, atlassian` get added under `desktop/src/renderer/public/assets/connectors/` as part of this slice.
- `linear, notion, drive` logos stay in the repo (in case the user adds those connectors later) but the renderer only displays them if the sidecar reports those ids.

## Acceptance criteria

1. **Sidecar starts and serves:** `python3 -m ghostbrain.api` (with the API extras installed) starts a FastAPI server bound to 127.0.0.1 with token auth. `curl -H "Authorization: Bearer <token>" http://127.0.0.1:<port>/v1/vault/stats` returns valid JSON.
2. **All 9 endpoints implemented** (or 8 — `/v1/connectors/{id}` shares code with `/v1/connectors`) with Pydantic schemas, returning data sourced from the real vault.
3. **OpenAPI schema is available** at `/openapi.json` and reflects every endpoint with full request/response shapes.
4. **Electron main spawns the sidecar** on `whenReady`, captures port+token from stdout, terminates gracefully on `before-quit`, auto-restarts once on unexpected exit with 2s backoff.
5. **Token never reaches the renderer.** Confirmable: at runtime in DevTools, `window.gb` has no `token` property anywhere.
6. **`window.gb.api.request<T>(method, path, body?)`** works end-to-end.
7. **React Query v5 installed and wired** with sensible defaults.
8. **Hooks for every endpoint exist** in `lib/api/hooks.ts`: `useVaultStats`, `useConnectors`, `useConnector`, `useCaptures`, `useCapture`, `useMeetings`, `useAgenda`, `useRecentActivity`, `useSuggestions`.
9. **Every screen consumes real data.** Today, Connectors, Capture, Meetings (history portion), Vault, Settings — no more `lib/mocks/` imports.
10. **`lib/mocks/` directory is deleted.**
11. **Loading skeletons render** before data arrives; empty states render when the vault is empty; error states render with retry on `5xx`.
12. **Connector list reflects reality** — surfaces what's in `ghostbrain/connectors/` directory, with logos for the real set (`claude_code, github, jira, confluence, calendar, atlassian, slack, gmail`).
13. **First-run UX handles** missing Python, missing vault, empty vault — no white screens.
14. **`pyproject.toml`** has `[project.optional-dependencies] api = [...]` for FastAPI + uvicorn.
15. **Hard rule on Python side:** no existing `ghostbrain/*.py` file outside `ghostbrain/api/` is modified. Verifiable: `git diff main..HEAD -- ghostbrain/ ':!ghostbrain/api/'` returns nothing.
16. **`npm run typecheck && npm run lint && npm test`** all pass.
17. **`npm run dev`** boots, sidecar comes up, all six screens render real data.

## Risks & open questions

1. **Vault layout assumptions.** The endpoints assume `vault_path()/20-contexts/*/calendar/`, `.../meetings/`, etc. These conventions exist in `ghostbrain/spec/SPEC.md` and the worker — verify exact paths during implementation; the `repo/*.py` modules centralize this so changes are localized.

2. **Meeting file location.** `ghostbrain.recorder.paths` (if exposed) is the source of truth. Plan task should grep the recorder to find the exact path.

3. **Pydantic version.** anthropic SDK pulls Pydantic v2 transitively. FastAPI is Pydantic v2-native. No conflict expected.

4. **uvicorn logging vs READY banner.** uvicorn's default startup log writes to stderr; the READY banner goes to stdout. Main parses stdout only, so they don't interleave. Verify on the first dev launch.

5. **CSP and `connect-src` localhost.** The renderer's CSP (`connect-src 'self'`) doesn't allow `http://localhost:<port>` — but it doesn't need to, because all HTTP calls happen in main, not renderer. The renderer talks IPC only. No CSP change needed.

6. **`fetch` in Electron main.** Node 22+ has global `fetch`. Electron 32 uses Node 20.x — also has global `fetch`. No `node-fetch` dep needed.

7. **React Query devtools.** Useful in dev, adds bundle weight in prod. Plan task can decide whether to include — if so, conditionally mount in dev only.

8. **Polling vs WebSocket for live updates.** Phase 1 uses React Query `refetchInterval`. The "ghost activity" panel feels alive at 30s polling — verify visually; if not, lean to 15s or implement WebSocket events earlier.

9. **First-run "Python not on PATH" copy.** Need to write friendly instructions for the user. Probably: "Install Python 3.11+: brew install python@3.11 (macOS) / python.org (Windows). Then: pip install -e '.[api]' from this directory."

10. **Suggestions endpoint.** Phase 1 returns static or trivially-computed hints. The real LLM-driven suggestions need the `claude` CLI subprocess pattern that the rest of ghostbrain uses (per the LLM backend memory) — slot that into Phase 2.

11. **Performance.** Vault walks can be slow on a large vault. The vault stats endpoint should cache its result for ~30s (TTL cache in the repo layer). Bigger vaults (>10k notes) may need an index.

12. **Cross-platform paths.** `vault_path()` uses `Path.home() / "ghostbrain" / "vault"` — works on macOS and Windows. Verify that `python3` from PATH resolves correctly on Windows (it might be `python` instead of `python3` on some Win installs — plan task adds detection logic).

## Estimated effort

| Slice | Days |
|---|---|
| Sidecar bootstrap (FastAPI app, schemas, auth middleware, startup banner, README) | 3 |
| Read endpoints (9 of them, Pydantic models, real vault reads in `repo/`) | 2.5 |
| Electron main: sidecar lifecycle, IPC forwarder, error events | 1.5 |
| Renderer: React Query, hooks, loading/empty/error components, type contracts | 1.5 |
| Per-screen migration (Today, Connectors, Capture, Meetings, Vault) | 2.5 |
| Connector reconciliation + 4 missing logos | 0.5 |
| First-run UX (sidecar-down screen, vault-missing handling) | 1 |
| Hardening (restart-on-crash, graceful shutdown, edge cases) | 1 |
| **Total** | **~13.5 days (≈2.5–3 weeks)** |

## What Phase 2 adds (preview, for context only — not in this spec)

- `POST` endpoints: `/v1/connectors/{id}/sync`, `/v1/connectors/{id}/oauth/start`, `/v1/meetings/start`, `/v1/meetings/{id}/stop`, `/v1/captures/{id}/archive`, `/v1/search`
- `GET /v1/events` (WebSocket) — live transcript stream, activity push, sync progress
- PyInstaller spec; electron-builder `extraResources` to ship the binary
- Code signing (Mac notarization, Win Authenticode)
- Auto-updater wiring
- CI matrix for build/sign/release

Same architecture. Additive endpoints. Bundled binary replaces system `python3`.
