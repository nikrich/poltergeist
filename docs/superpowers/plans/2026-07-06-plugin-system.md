# Poltergeist Plugin System v1 + Séance Plugin — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Pre-designated for INLINE execution (user constraint: no subagents).**

**Goal:** Runtime-installable plugins for Poltergeist (folder/git install, crash-isolated loader, `plugin://` renderer host) proven end-to-end by the Séance plugin.

**Architecture:** Trusted-code plugins: `manifest.json` (zod-validated) + pre-built `dist/main.cjs` (`activate(ctx)/deactivate()`, loaded via `createRequire`) + `dist/renderer.mjs` (`mount(el, api)`, dynamic-imported over a path-safe `plugin://` protocol). Namespaced IPC `gb:plugin:<id>:<channel>`. Plugin enabled-state + per-plugin settings in `<userData>/plugins.json` (own store; the app settings store validates against a fixed zod shape, so dynamic plugin data does NOT go there — spec amended).

**Tech Stack:** Electron 37/electron-vite, React 19 + zustand, zod, vitest (jsdom, `src/main/**/*.test.ts` included), esbuild (plugin builds in the seance repo).

## Global Constraints

- Repos: loader/host in `ghost-brain` on branch `feat/plugin-system` (repo has unrelated dirty files — commit ONLY files this plan touches, always by explicit path). Plugin in `seance` on `main`.
- Install NEVER runs npm/build/postinstall. Plugins commit `dist/`.
- manifest `id` regex `^[a-z][a-z0-9-]{1,31}$`; `apiVersion` must equal `1`; IPC channel regex `^[a-z0-9:_-]+$`.
- Every plugin call wrapped in try/catch → state `errored`, app never crashes.
- Plugin dirs: `<userData>/plugins/<id>/`; data: `<userData>/plugin-data/<id>/`; state file `<userData>/plugins.json`.
- All new IPC channels start `gb:plugins:` (host) or `gb:plugin:<id>:` (per-plugin).
- Séance plugin writes ONLY to workspace `inbox/` (+ its own dataDir); everything else read-only.
- Commit style: conventional commits, `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## File Structure

```
ghost-brain/desktop/
  src/shared/plugin-types.ts                     # manifest zod schema, PluginRecord/PluginRuntimeState, api types
  src/main/plugins/store.ts                      # plugins.json (enabled map + per-plugin data), atomic write
  src/main/plugins/loader.ts                     # scan, validate, activate/deactivate/reload, PluginContext
  src/main/plugins/installer.ts                  # installFromFolder / installFromGit / uninstall
  src/main/plugins/protocol.ts                   # plugin:// scheme (privileged registration + handler)
  src/main/plugins/ipc.ts                        # gb:plugins:* host handlers + renderer push
  src/main/plugins/__tests__/{store,loader,installer,protocol}.test.ts
  src/main/plugins/__tests__/fixtures/hello/     # fixture plugin (manifest + main.cjs + renderer.mjs)
  src/main/plugins/__tests__/fixtures/broken/    # manifest ok, activate throws
  src/preload/index.ts                           # + plugins host api, + plugin(id) scoped bridge
  src/shared/types.ts                            # + GbBridge additions
  src/renderer/stores/navigation.ts              # ScreenId += `plugin:${string}`
  src/renderer/components/Sidebar.tsx            # + dynamic plugin nav items
  src/renderer/components/PluginHost.tsx         # dynamic import + mount/unmount + error panel
  src/renderer/screens/plugins.tsx               # manage/install UI
  src/renderer/App.tsx                           # + plugins screen + PluginHost route
seance/poltergeist-plugin/
  manifest.json
  package.json / build.mjs                       # esbuild: src/main.cts→dist/main.cjs, src/renderer.tsx→dist/renderer.mjs
  src/main.cts                                   # workspaces/status/summon/steer/heartbeat/watch
  src/lib/state-files.cts                        # frontmatter + workspace parsing (pure, node-testable)
  src/renderer.tsx (+ src/ui/*.tsx)              # React screen, bundled
  dist/ (committed)
```

---

### Task 1: Shared plugin types + plugins.json store

**Files:** Create `src/shared/plugin-types.ts`, `src/main/plugins/store.ts`, `src/main/plugins/__tests__/store.test.ts`

**Produces (used by all later tasks):**

```ts
// src/shared/plugin-types.ts
import { z } from 'zod';
export const manifestSchema = z.object({
  id: z.string().regex(/^[a-z][a-z0-9-]{1,31}$/),
  name: z.string().min(1).max(64),
  version: z.string().min(1),
  description: z.string().max(500).optional(),
  apiVersion: z.literal(1),
  icon: z.string().regex(/^[a-z0-9-]+$/).optional(),   // lucide name; host falls back to 'puzzle'
  entry: z.object({
    main: z.string().regex(/^[\w./-]+\.cjs$/).optional(),
    renderer: z.string().regex(/^[\w./-]+\.mjs$/).optional(),
  }).refine((e) => e.main || e.renderer, { message: 'entry needs main and/or renderer' }),
});
export type PluginManifest = z.infer<typeof manifestSchema>;
export type PluginRuntimeState = 'enabled' | 'disabled' | 'errored' | 'invalid';
export interface PluginRecord {
  id: string;               // for invalid manifests: the directory name
  dir: string;
  manifest: PluginManifest | null;   // null when invalid
  state: PluginRuntimeState;
  error?: string;
}
export interface ActivePluginInfo { id: string; name: string; icon: string; hasRenderer: boolean }
```

```ts
// src/main/plugins/store.ts — same atomic-write pattern as src/main/settings.ts
export function isEnabled(id: string): boolean               // default false (install leaves disabled until user enables? NO — see below: install enables by default)
export function setEnabled(id: string, on: boolean): void
export function getData(id: string, key: string): unknown
export function setData(id: string, key: string, value: unknown): void
export function forget(id: string): void                     // uninstall: drop enabled flag, KEEP data
```

On-disk shape `{ version: 1, enabled: Record<string, boolean>, data: Record<string, Record<string, unknown>> }` at `join(app.getPath('userData'), 'plugins.json')`. **Install default: enabled = true** (first prototype ergonomics). Store module keeps a cache like settings.ts; export `_resetForTest()` clearing cache and allow overriding the file path via exported `_setPathForTest(p)` (tests run without electron `app` — `vi.mock('electron', ...)` with `getPath: () => tmpdir`).

- [ ] Step 1: Write `store.test.ts` — enabled defaults false for unknown id; setEnabled persists across `_resetForTest()`+reread; setData/getData roundtrip; forget removes enabled but keeps data; corrupted JSON file → defaults (no throw). Mock electron: `vi.mock('electron', () => ({ app: { getPath: () => TESTDIR } }))`.
- [ ] Step 2: Run `npx vitest run src/main/plugins/__tests__/store.test.ts` → FAIL (module missing).
- [ ] Step 3: Implement `plugin-types.ts` + `store.ts`.
- [ ] Step 4: Test passes; `npm run typecheck` clean.
- [ ] Step 5: Commit (paths only): `feat(plugins): manifest schema + plugin state store`

### Task 2: Loader with crash isolation

**Files:** Create `src/main/plugins/loader.ts`, fixtures `hello/` + `broken/`, `__tests__/loader.test.ts`

**Produces:**

```ts
export interface PluginContext {  // per spec
  pluginId: string; pluginDir: string; dataDir: string;
  settings: { get<T>(key: string): T | undefined; set(key: string, v: unknown): void };
  ipc: { handle(channel: string, fn: (...args: unknown[]) => unknown): void;
         send(channel: string, payload: unknown): void };
  log: (...args: unknown[]) => void;
}
export interface LoaderDeps {     // injected so tests need no electron ipcMain/BrowserWindow
  pluginsRoot: string; dataRoot: string;
  registerHandler(channel: string, fn: (...args: unknown[]) => unknown): void;
  unregisterHandler(channel: string): void;
  broadcast(channel: string, payload: unknown): void;
}
export function createLoader(deps: LoaderDeps): {
  scan(): PluginRecord[];                       // read dirs, validate manifests (no activation)
  activateEnabled(): Promise<void>;             // activate every scanned+enabled plugin with a main entry
  setEnabled(id: string, on: boolean): Promise<void>;
  reloadAll(): Promise<void>;                   // deactivate all → clear require cache under each dir → scan → activateEnabled
  deactivateAll(): Promise<void>;               // best-effort, per-plugin try/catch, 2s timeout each
  records(): PluginRecord[];                    // current records incl. runtime state
  active(): ActivePluginInfo[];                 // enabled && !errored
}
```

Rules from spec: `createRequire(__filename)` to load `main.cjs`; channel names validated `^[a-z0-9:_-]+$` and single registration; a throw in activate/handler → record `errored` + all its handlers unregistered + excluded from `active()`; `records()`/`active()` changes are the caller's cue to broadcast (ipc.ts does that). Renderer-only plugins (no main entry) activate trivially.

Fixture `hello`: manifest (id `hello`, icon `ghost`, both entries), `main.cjs` = `module.exports={activate(ctx){ctx.ipc.handle('ping',()=> 'pong-'+ctx.pluginId)},deactivate(){}}`, `renderer.mjs` = `export function mount(el){el.textContent='hello'; return ()=>{}}`. Fixture `broken`: activate throws `new Error('boom')`.

- [ ] Step 1: Write `loader.test.ts` (copy fixtures to a tmp pluginsRoot per test): scan finds both, invalid-manifest dir → `invalid` record; activateEnabled with hello enabled → registerHandler called with `gb:plugin:hello:ping` and invoking it returns `pong-hello`; broken enabled → its record `errored: 'boom'`, hello still activates; bad channel name from a fixture variant → handler rejected with error; setEnabled(false) → unregisterHandler called; reloadAll picks up an edited main.cjs (write new file content, reload, handler returns new value — proves require-cache clearing).
- [ ] Step 2: Run → FAIL. Step 3: Implement. Step 4: PASS + typecheck.
- [ ] Step 5: Commit: `feat(plugins): crash-isolated plugin loader`

### Task 3: Installer (folder / git / uninstall)

**Files:** Create `src/main/plugins/installer.ts`, `__tests__/installer.test.ts`

**Produces:**

```ts
export async function installFromFolder(src: string, pluginsRoot: string): Promise<PluginRecord>  // validate manifest at src, refuse id collision (error 'already installed'), cp -R
export async function installFromGit(url: string, subdir: string | undefined, pluginsRoot: string): Promise<PluginRecord>
export async function uninstall(id: string, pluginsRoot: string): Promise<void>                    // rm -rf plugin dir; store.forget(id)
```

Git: `execFile('git', ['clone','--depth','1','--single-branch', url, tmp], {timeout: 120_000})` into `mkdtemp`; source = subdir ? join(tmp, subdir) : tmp; validate; copy with `cp(src, dest, {recursive: true})` **excluding `.git`**; always rm tmp in `finally`. URL allowlist: `^(https:\/\/|git@)`.

- [ ] Step 1: Tests: folder install copies + returns record; id collision rejects; invalid manifest rejects and leaves pluginsRoot untouched; git install from a LOCAL fixture repo (create a bare-ish git repo in tmp via `git init`+commit with plugin at subdir `pkg/`, install with `url=file://<tmp>` — allow `file://` ONLY under `NODE_ENV=test` guard? No: relax allowlist to `^(https:\/\/|git@|file:\/\/)` and note file:// is fine — it's a local app, not a server) → plugin lands, `.git` not copied; uninstall removes dir and store.forget called (spy).
- [ ] Step 2: FAIL → Step 3: Implement → Step 4: PASS + typecheck.
- [ ] Step 5: Commit: `feat(plugins): folder and git installers`

### Task 4: plugin:// protocol

**Files:** Create `src/main/plugins/protocol.ts`, `__tests__/protocol.test.ts`

**Produces:**

```ts
export function registerPluginScheme(): void       // BEFORE app ready: registerSchemesAsPrivileged([{scheme:'plugin', privileges:{standard:true, secure:true, supportFetchAPI:true, corsEnabled:true}}])
export function installPluginProtocol(resolveDir: (id: string) => string | null): void  // AFTER ready: protocol.handle('plugin', ...)
export function resolvePluginPath(rootForId: string, urlPath: string): string | null    // PURE: null on traversal/escape — unit-tested
```

Handler: URL `plugin://<id>/<path>`; hostname = id → `resolveDir(id)` (loader record dir, only for active plugins); `resolvePluginPath` joins + `path.resolve` and verifies `startsWith(dir + sep)`; 404 Response on any failure; MIME map: `.mjs/.js→text/javascript`, `.css→text/css`, `.json→application/json`, `.svg→image/svg+xml`, `.png→image/png`, default `application/octet-stream`.

- [ ] Step 1: Tests for `resolvePluginPath` only (pure): normal file ok; `..` escape → null; absolute path → null; URL-encoded `%2e%2e` (pass decoded) → null; nested ok.
- [ ] Step 2–4: FAIL → implement → PASS + typecheck.
- [ ] Step 5: Commit: `feat(plugins): plugin:// protocol with path containment`

### Task 5: Wire main process + preload + host IPC

**Files:** Create `src/main/plugins/ipc.ts`; Modify `src/main/index.ts`, `src/preload/index.ts`, `src/shared/types.ts`

`ipc.ts` — `installPluginsIpc({loader, pluginsRoot})` registers:
`gb:plugins:list` → `loader.records()` (+ `active()` merged shape for the screen); `gb:plugins:active` → `loader.active()`; `gb:plugins:setEnabled(id,on)`; `gb:plugins:reload`; `gb:plugins:installFromFolder` (uses `dialog.showOpenDialog({properties:['openDirectory']})`); `gb:plugins:installFromGit(url,subdir)`; `gb:plugins:uninstall(id)`; `gb:plugins:data:get/set(id,key,value?)` (renderer-side plugin settings). All return `{ok:true,...}|{ok:false,error}` like existing handlers. After any mutation: broadcast `gb:plugins:changed` with `loader.active()` to all windows.

`index.ts` wiring: `registerPluginScheme()` at module top (before ready); in `whenReady` (before `createWindow()` so the first paint can already know plugins — actually AFTER createWindow is fine since renderer invokes `gb:plugins:active` on mount): create loader with real deps (`ipcMain.handle`/`removeHandler`, broadcast over all windows), `loader.scan(); await loader.activateEnabled(); installPluginProtocol(...); installPluginsIpc(...)`. In `before-quit`: `void loader.deactivateAll()`.

`preload/index.ts` + `shared/types.ts` — add to GbBridge:

```ts
plugins: {
  list(): Promise<PluginRecord[]>; active(): Promise<ActivePluginInfo[]>;
  setEnabled(id: string, on: boolean): Promise<Result>; reload(): Promise<Result>;
  installFromFolder(): Promise<Result>; installFromGit(url: string, subdir?: string): Promise<Result>;
  uninstall(id: string): Promise<Result>;
  onChanged(cb: (active: ActivePluginInfo[]) => void): () => void;
};
plugin(id: string): {
  invoke(channel: string, ...args: unknown[]): Promise<unknown>;
  on(channel: string, cb: (payload: unknown) => void): () => void;
  settings: { get(key: string): Promise<unknown>; set(key: string, v: unknown): Promise<void> };
};
```

- [ ] Step 1: Implement all four files (no new unit tests — logic lives in tested modules; this is wiring).
- [ ] Step 2: `npm run typecheck && npx vitest run` → all green (renderer tests unaffected).
- [ ] Step 3: `npm run dev` smoke: app boots, devtools console `await window.gb.plugins.list()` → `[]`.
- [ ] Step 4: Commit: `feat(plugins): wire loader, protocol, host IPC and preload bridge`

### Task 6: Renderer — sidebar, PluginHost, Plugins screen

**Files:** Modify `src/renderer/stores/navigation.ts` (`export type ScreenId = <existing union> | \`plugin:${string}\``), `src/renderer/components/Sidebar.tsx`, `src/renderer/App.tsx`; Create `src/renderer/components/PluginHost.tsx`, `src/renderer/screens/plugins.tsx`, `src/renderer/screens/__tests__/plugins.test.tsx`

- Sidebar: `usePlugins()` local hook (module in plugins.tsx exports it): state from `window.gb.plugins.active()` + `onChanged`; render nav items `{id: 'plugin:'+p.id, icon: p.icon || 'puzzle', label: p.name.toLowerCase()}` in a `plugins` Eyebrow section (below core nav), only when non-empty. Add a `plugins` core nav item (icon `blocks`, label `plugins`) above `settings`.
- App.tsx: `{active === 'plugins' && <PluginsScreen/>}` and `{active.startsWith('plugin:') && <PluginHost key={active} id={active.slice(7)} />}`.
- PluginHost: on mount `import(/* @vite-ignore */ \`plugin://${id}/${entryRenderer}\`)` — get entry path from `active()` info (extend ActivePluginInfo with `rendererEntry: string | null`; adjust Task 2 type + loader accordingly NOW, not later); call `mod.mount(el, api)` with api built from `window.gb.plugin(id)` + `openExternal` + `theme` (read `getComputedStyle(document.documentElement)` custom props). Keep unmount fn; call on cleanup. Errors → `PanelError` + retry button.
- plugins.tsx: Panel listing `list()` records (name, id, version, state pill, error text), Toggle per plugin (`setEnabled`), uninstall Btn with `confirm()`, "install from folder" Btn, git URL + subdir inputs + install Btn, Reload plugins Btn; trust-warning copy on the install section: *"Plugins run with full access to your machine. Install only code you trust."* All mutations then refetch list. Follow `connectors.tsx` visual conventions (Panel, Eyebrow, Btn, Pill, Toggle).
- [ ] Step 1: Write `plugins.test.tsx` (mock `window.gb`): renders records; toggle calls setEnabled with (id, false); install-from-git button calls installFromGit with typed url/subdir; error state shows error message.
- [ ] Step 2: FAIL → Step 3: implement all renderer changes → Step 4: `npx vitest run` PASS + typecheck.
- [ ] Step 5: `npm run dev` smoke: Plugins screen renders empty state; sidebar unchanged (no plugins yet).
- [ ] Step 6: Commit: `feat(plugins): plugins screen, sidebar entries, PluginHost`

### Task 7: Séance plugin — main process side

**Files (seance repo):** Create `poltergeist-plugin/{manifest.json,package.json,build.mjs,src/main.cts,src/lib/state-files.cts,test/state-files.test.mjs}`

manifest: `{"id":"seance","name":"Séance","version":"0.1.0","description":"Summon autonomous coding sessions and watch them live","apiVersion":1,"icon":"sparkles","entry":{"main":"dist/main.cjs","renderer":"dist/renderer.mjs"}}`

`state-files.cts` (pure, tested with `node --test`): `parseFrontmatter(md) → {attrs: Record<string,unknown>, body}` (yaml-lite: scalars, arrays `[a, b]`, quoted strings — enough for séance files); `readWorkspaceStatus(wsPath) → Snapshot`:

```ts
interface Snapshot {
  requirements: Array<{id:string; title:string; status:string; priority:string}>;
  stories: Array<{id:string; requirement:string; repo:string; status:string; attempts:number; title:string}>; // title = first non-empty line under '## Task'
  agents: Array<{id:string; role:string; pid:number; story:string|null; startedAt:string; alive:boolean}>;
  attention: Array<{name:string; body:string}>;
  lastTickTs: string | null;         // newest ts in journal/ticks.ndjson (read tail)
  backlogCounts: Record<string, number>; // stories per status
}
```

`main.cts` — `activate(ctx)` registers (all channels validated by host): `workspaces:list` (scan `~/seance/*/config.yaml` — homedir from `os`), `status(wsPath)` (guard: wsPath must be a string under `~/seance/`), `summon(wsPath,{id,title,priority,body})` (id `^[A-Z][A-Z0-9-]{1,31}$`, refuse if `inbox/<id>.md` or `state/requirements/<id>.md` exists, write frontmatter+body), `steer(wsPath,text)`, `heartbeat:start(wsPath)` (script path = plugin setting `seanceRepoPath` ?? `~/development/nikrich/seance`, spawn `bash heartbeat.sh <ws>` detached, `unref()`, pid → `dataDir/heartbeats.json`), `heartbeat:stop(wsPath)` (`process.kill(-pid)` then fallback `kill(pid)`; clear pidfile entry), `heartbeat:status(wsPath)` (`{running, pid, lastTickTs}` — also detect an externally-started heartbeat via `ps -eo pid,command | grep heartbeat.sh <ws>`? NO — YAGNI: pidfile + liveness only), `watch:start(wsPath)`/`watch:stop` (fs.watch recursive on `state`,`attention`,`journal`, 500ms debounce → `ctx.ipc.send('changed',{wsPath})`). `deactivate()`: close watchers (leave heartbeats running — they're the point).

`build.mjs`: esbuild — main: `{entryPoints:['src/main.cts'], outfile:'dist/main.cjs', bundle:true, platform:'node', format:'cjs', external:['electron']}`; renderer added in Task 8.

- [ ] Step 1: `node --test test/state-files.test.mjs` against fixtures copied from a real sandbox story/requirement/agent file (frontmatter arrays, status extraction, `## Task` title, ndjson tail) → written first, FAIL.
- [ ] Step 2: Implement lib + main.cts + build; tests PASS.
- [ ] Step 3: Integration smoke without Poltergeist: `node -e "const p=require('./dist/main.cjs'); p.activate(fakeCtx)"` with a fakeCtx capturing handlers; call `workspaces:list` (expect sandbox), `status` (expect ≥3 merged stories from the earlier soak), `summon` to a scratch inbox then delete it.
- [ ] Step 4: Commit (seance repo): `feat: poltergeist plugin — main process (status, summon, heartbeat, watch)`

### Task 8: Séance plugin — renderer + committed dist

**Files (seance repo):** Create `poltergeist-plugin/src/renderer.tsx` (+ `src/ui/Board.tsx`, `src/ui/Summon.tsx`), extend `build.mjs` (renderer: `{bundle:true, format:'esm', outfile:'dist/renderer.mjs', jsx:'automatic'}`, react+react-dom bundled), commit `dist/`.

`renderer.tsx`: `export function mount(el, api)` → creates React root, renders `<App api={api}/>`, returns `()=>root.unmount()`. App: header (workspace `<select>` from `workspaces:list`, heartbeat toggle button + health dot from `heartbeat:status` polled 10s, last-tick relative time), attention strip (amber cards), summon form (id/title/priority/body → `summon`, then clear + toast-ish inline confirmation), steering one-liner input, board = five columns (Backlog=pending, Building, Verifying, Shipped=merged+pr_open, Blocked) of story cards (id, repo, attempts pill). Subscribe `api.ipc.on('changed')` → refetch status; `watch:start` on workspace select, `watch:stop` on switch/unmount. Styling: inline styles reading `api.theme` vars with dark fallbacks — no Tailwind dependence.

- [ ] Step 1: Implement + `node build.mjs` → dist/main.cjs + dist/renderer.mjs exist, `node -e "import('./dist/renderer.mjs').then(m=>console.log(typeof m.mount))"` → `function`.
- [ ] Step 2: Commit including dist: `feat: poltergeist plugin — renderer screen (board, summon, heartbeat)` and push seance.

### Task 9: End-to-end + docs

- [ ] Step 1: `npm run dev` in ghost-brain/desktop → Plugins screen → **install from folder** pointing at `~/development/nikrich/seance/poltergeist-plugin` → Séance appears in sidebar with sparkles icon.
- [ ] Step 2: Open Séance screen: sandbox workspace listed; soak stories visible in Shipped; summon `REQ-3 "Add a subtract function"` → file appears in `~/seance/sandbox/inbox/`; start heartbeat from UI → board moves (planner → builder → merged) live via watch events. Stop heartbeat.
- [ ] Step 3: Uninstall, then **install from git**: URL `https://github.com/nikrich/seance`, subdir `poltergeist-plugin` → loads identically.
- [ ] Step 4: Seed a fake `attention/manual.md` → strip renders; remove it.
- [ ] Step 5: Update seance README (Integrations section: "install via Poltergeist → Plugins → git URL + subdir") and ghost-brain spec if reality diverged. Commit both repos: `docs: plugin install instructions`.

## Self-review notes

- Spec deviation (recorded in header): plugin enabled/data state in `plugins.json`, not the app settings store — the settings IPC validates against a closed zod shape.
- ActivePluginInfo carries `rendererEntry` (needed by PluginHost) — defined that way from Task 2 onward.
- file:// allowed in git installer URL allowlist (local desktop app; enables tests and local installs).
- Renderer-only plugins covered by loader (trivial activate) and PluginHost (entry from manifest); main-only plugins simply add no sidebar item (`hasRenderer=false` filters them from nav but they still show in the Plugins screen).
