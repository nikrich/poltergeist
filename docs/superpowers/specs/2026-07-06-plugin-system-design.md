# Poltergeist Plugin System v1 — Design

**Date:** 2026-07-06
**Status:** Approved design
**Repos:** loader/host in `ghost-brain` (this repo, branch `feat/plugin-system`); first plugin in `nikrich/seance` under `poltergeist-plugin/`

## Goal

Let Poltergeist install and run third-party plugins at runtime, prototyped end-to-end with the **Séance** code plugin: kick off autonomous coding sessions (write a requirement into a Séance workspace inbox, start/stop the heartbeat) and watch their status live — without leaving the app.

## Trust model (explicit)

v1 plugins are **trusted code**. `main.cjs` runs unsandboxed in the Electron main process with full Node access; `renderer.mjs` runs in the app's renderer. Install only plugins you trust — the Plugins screen says this at install time. Sandboxing is a non-goal for v1.

## Plugin package format

A plugin is a directory, installed to `<userData>/plugins/<id>/`:

```
manifest.json
dist/main.cjs        # pre-built CommonJS; module.exports = { activate(ctx), deactivate() }
dist/renderer.mjs    # pre-built ESM;      export function mount(el, api): () => void
```

`manifest.json` (validated with zod; reject = plugin shows as invalid, never loaded):

```json
{
  "id": "seance",                  // ^[a-z][a-z0-9-]{1,31}$ — unique, doubles as dir name
  "name": "Séance",
  "version": "0.1.0",
  "description": "Summon autonomous coding sessions",
  "apiVersion": 1,                 // loader refuses any value other than 1
  "icon": "sparkles",              // lucide icon name for the sidebar
  "entry": { "main": "dist/main.cjs", "renderer": "dist/renderer.mjs" }
}
```

**Pre-built is a hard rule:** install never runs `npm install`, build scripts, or postinstall hooks. Plugins commit their `dist/`.

Both entry files are optional individually (a plugin may be main-only or renderer-only), but at least one must be present. Séance has both.

## Install & manage (Plugins screen)

New `plugins.tsx` screen following the `connectors.tsx` pattern, plus a sidebar entry. Shows every plugin in the plugins dir with state: `enabled | disabled | errored (message) | invalid (zod error)`. Actions:

- **Install from folder** — native directory picker → validate manifest → copy to `<userData>/plugins/<id>/`. Refuse if id already installed (offer replace).
- **Install from git** — dialog: URL + optional subdirectory. `git clone --depth 1` to a temp dir, take the subdir (or root), validate, copy in, delete temp. Uses the system `git`; a clear error if missing. (Séance: URL `https://github.com/nikrich/seance`, subdir `poltergeist-plugin`.)
- **Enable/disable toggle** — persisted in `<userData>/plugins.json` (own atomic store, NOT the app settings store: `gb:settings:set` validates against a closed zod shape, plugin data is dynamic). Disable calls `deactivate()`, unloads renderer entry, removes sidebar item.
- **Uninstall** — confirm dialog → `deactivate()` → delete `<userData>/plugins/<id>/`. Plugin data dir (`<userData>/plugin-data/<id>/`) survives; noted in the confirm text.
- **Reload plugins** — full deactivate/rescan/reactivate cycle (dev loop; also the recovery path after updating a plugin).

Update story for v1 = uninstall + reinstall (or reinstall-from-git over it). No auto-update.

## Main-process loader (`src/main/plugins/`)

Files: `loader.ts` (scan/validate/activate lifecycle), `installer.ts` (folder/git install, uninstall), `ipc.ts` (namespacing + host IPC for the Plugins screen), `types.ts` (PluginContext, records).

On `app.whenReady`: scan `<userData>/plugins/*/manifest.json` → validate → for each enabled plugin with a `main` entry, `require(<dir>/<entry.main>)` and call `activate(ctx)`:

```ts
interface PluginContext {
  pluginId: string;
  pluginDir: string;                       // read-only home of the plugin
  dataDir: string;                         // <userData>/plugin-data/<id>/ — created on demand
  settings: { get<T>(key: string): T | undefined; set(key: string, v: unknown): void };
                                           // namespaced: plugins.data.<id>.<key> in settings store
  ipc: {
    handle(channel: string, fn: (...args: unknown[]) => unknown): void;   // gb:plugin:<id>:<channel>
    send(channel: string, payload: unknown): void;                        // to all app windows
  };
  log: (...args: unknown[]) => void;       // prefixed [plugin:<id>] to main log
}
```

Rules:

- Activate/load failures are try/caught: a throw → plugin state `errored` with the message, its IPC handlers removed, sidebar entry dropped. A throwing IPC *handler* rejects only that call (the renderer surfaces the error) — a validation error must not kill the plugin. The app never crashes because of a plugin.
- The renderer CSP allows the `plugin:` scheme for script/img/connect (`script-src 'self' plugin:` etc.) — without this the dynamic import is blocked.
- `ipc.handle` rejects channels not matching `^[a-z0-9:_-]+$` and registers at most once per channel.
- `deactivate()` is called on disable, uninstall, reload, and app quit (best-effort, 2s timeout).
- Reload uses `delete require.cache[...]` for the plugin's module tree under its dir.

## Renderer host

- Main pushes the active-plugin list `{id, name, icon}[]` to the renderer (`gb:plugins:changed` event + `gb:plugins:list` invoke).
- `Sidebar` appends one nav item per active plugin (lucide icon by name, fallback `puzzle`) below core screens. `App.tsx`: `active === 'plugin:<id>'` renders `<PluginHost id={id}/>`.
- `PluginHost` dynamic-imports `plugin://<id>/renderer.mjs` and calls `mount(el, api)`, keeping the returned unmount fn; unmounts on navigate away/disable. Import or mount failure → `PanelError` inside the host with a retry button.
- `plugin://` is a custom protocol registered in main (`protocol.handle`), serving files **only** from installed plugin dirs, path-traversal-safe (resolved path must stay under the plugin dir), correct MIME for `.mjs`/`.js`/`.css`/images.
- The `api` handed to `mount`:

```ts
interface PluginApi {
  pluginId: string;
  ipc: {
    invoke(channel: string, ...args: unknown[]): Promise<unknown>;        // gb:plugin:<id>:<channel>
    on(channel: string, cb: (payload: unknown) => void): () => void;
  };
  settings: { get(key: string): Promise<unknown>; set(key: string, v: unknown): Promise<void> };
  openExternal(url: string): void;
  theme: Record<string, string>;           // the app's CSS custom properties, for visual blending
}
```

- Preload: one addition to `GbBridge` — `plugin(id).invoke/on/settings`, mapped to the namespaced channels. Plugins never get raw `ipcRenderer`.
- The renderer contract is framework-free: the plugin owns the DOM under `el` and bundles any framework internally. The host styles `el` as a full-height scroll container.

## The Séance plugin (`seance/poltergeist-plugin/`)

Consumes only the file contract in Séance's README (writes ONLY to `inbox/`).

**main.cjs** (`activate` registers, `deactivate` cleans up watchers/intervals):

- `workspaces:list` → scan `~/seance/*/config.yaml` → `{name, path}[]`.
- `status` `(wsPath)` → one JSON snapshot: requirements, stories (id, status, repo, attempts, title from `## Task` first line), agents (+pid liveness via `kill -0`), attention items (name + body), last tick ts + last 24h tick counts, heartbeat state.
- `summon` `(wsPath, {id, title, priority, body})` → validate id `^[A-Z0-9-]+$`, write `inbox/<id>.md` in the requirement format. The only state write.
- `steer` `(wsPath, text)` → write `inbox/steer-<ts>.md` (no `id:` frontmatter).
- `heartbeat:start` `(wsPath)` → resolve `heartbeat.sh` from plugin settings key `seanceRepoPath` (default `~/development/nikrich/seance`), spawn detached with stdout→`logs/launchd.log`-style file, record pid in `dataDir/heartbeats.json`; `heartbeat:stop` kills the process group; `heartbeat:status` = pidfile + liveness + newest tick ts.
- `watch:start/stop` `(wsPath)` → `fs.watch` (recursive) on `state/`, `attention/`, `journal/`, debounced 500ms → `ipc.send('changed', {wsPath})`.

**renderer.mjs** — one screen, own React bundled via esbuild (`dist/` committed):

- Header: workspace picker + heartbeat toggle + health dot (green: tick < 15 min or idle-consistent; amber: no recent tick while work pending; grey: stopped).
- Attention strip (topmost, only when non-empty): each `attention/*.md` as an alert card.
- Board: stories grouped by status (Backlog / Building / Verifying / Shipped / Blocked) with repo, attempts, requirement chips; requirements summary row above.
- Summon panel: id, title, priority, markdown body → `summon`; steering input → `steer`.
- Subscribes to `changed` events → refetch `status`.

## Testing

- **Vitest (ghost-brain):** manifest zod validation (good/bad fixtures); loader isolation (fixture plugin whose activate throws → state `errored`, app continues, others load); IPC namespacing (channel becomes `gb:plugin:<id>:<x>`, bad channel names rejected); installer subdir copy + id-collision refusal; `plugin://` path-traversal rejection (`..`, absolute, symlink escape).
- **Fixture plugin** in `src/main/plugins/__tests__/fixtures/hello/` (manifest + trivial main.cjs + renderer.mjs).
- **End-to-end (manual, gated on both repos):** install Séance via the git flow (URL + subdir) into the dev app → enable → sandbox workspace appears → summon a toy requirement → start heartbeat → watch stories move on the board → attention item renders when seeded.

## Out of scope (v1)

- Sandboxing/permissions, plugin auto-update, plugin marketplace/registry
- Additional extension points (tray, jot actions, chat tools, sidecar/Python hooks)
- Building plugins at install time; unsigned-code warnings beyond the install-time trust note
