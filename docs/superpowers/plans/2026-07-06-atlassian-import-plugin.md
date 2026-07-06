# Atlassian Import Plugin Extraction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> **Pre-designated for INLINE execution (user constraint: no subagents).**

**Goal:** Make Jira/Confluence import opt-in — add a reusable sidecar bridge to the plugin host, remove the import tab from core, and rebuild it as a renderer-only plugin in `nikrich/poltergeist-atlassian-import`. Per `docs/superpowers/specs/2026-07-06-atlassian-import-plugin-design.md`.

**Architecture:** Plugin host gains `api.sidecar.request(method, '/v1/...', body)` (guarded like the app's own `gb:api:request`). Core deletes the import screen/hooks/types/nav. A new renderer-only plugin (no `main.cjs`) ports the import UI framework-free, calling the sidecar bridge. Python `/v1/import` backend and connectors stay untouched.

**Tech Stack:** Electron/electron-vite, React 19 + zustand, vitest (jsdom), esbuild (plugin), the Séance plugin as the pattern reference.

## Global Constraints

- ghost-brain work happens in the worktree `/tmp/gb-import` on branch `feat/atlassian-import-plugin` (clean base off `origin/main` @ v0.5.0). Never touch the user's other checkout.
- Conventional commits, `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Sidecar bridge guards MUST mirror `gb:api:request` in `src/main/index.ts`: `isAllowedMethod(method)` and `path.startsWith('/v1/')`; DEMO mode routes to `handleDemoApi`.
- Plugin is **renderer-only**: `manifest.entry = { renderer: 'dist/renderer.mjs' }`, no main.cjs. id `atlassian-import`, icon `download`.
- Plugin renderer is framework-free (bundles own React, inline styles from `api.theme`), no core-component imports — same contract as the Séance plugin (`~/development/nikrich/seance/poltergeist-plugin`).
- Plugin ships pre-built `dist/` (committed). Install never builds.
- Backend endpoints the plugin calls (unchanged): `GET /v1/import/confluence/spaces`, `GET /v1/import/confluence/pages?site&space&parent&limit&cursor`, `GET /v1/import/confluence/search?q`, `GET /v1/import/jira/issues?q`, `POST /v1/import` (body `{items:[item]}`, one item per call).

## File Structure

```
ghost-brain (worktree /tmp/gb-import, branch feat/atlassian-import-plugin):
  desktop/src/shared/types.ts                 # + sidecar to per-plugin GbBridge.plugin(id)
  desktop/src/preload/index.ts                # + sidecar.request in plugin(id) bridge
  desktop/src/main/plugins/ipc.ts             # + gb:plugins:sidecar handler (guarded forward)
  desktop/src/main/plugins/__tests__/ipc-sidecar.test.ts   # guard unit tests
  desktop/src/renderer/components/PluginHost.tsx  # + sidecar on PluginApi + api object
  desktop/src/renderer/test/setup.ts          # stub plugin().sidecar
  # removals:
  desktop/src/renderer/screens/import.tsx     # DELETE
  desktop/src/renderer/lib/api/hooks.ts       # remove Atlassian-import block (548–~640)
  desktop/src/shared/api-types.ts             # remove import types (345–404)
  desktop/src/renderer/components/Sidebar.tsx # remove 'import' NAV_ITEMS entry
  desktop/src/renderer/App.tsx                # remove ImportScreen import + route
  desktop/src/renderer/stores/navigation.ts   # remove 'import' from ScreenId

nikrich/poltergeist-atlassian-import (new repo, ~/development/nikrich/poltergeist-atlassian-import):
  manifest.json  package.json  build.mjs  .gitignore  README.md
  src/renderer.jsx        # mount(el, api) + ImportApp
  src/ui/*.jsx            # Tabs, ConfluenceBrowse, JiraBrowse, SelectionBar
  dist/                   # committed
```

---

### Task 1: Sidecar bridge on the plugin host

**Files:** Modify `desktop/src/shared/types.ts`, `desktop/src/preload/index.ts`, `desktop/src/main/plugins/ipc.ts`, `desktop/src/renderer/components/PluginHost.tsx`, `desktop/src/renderer/test/setup.ts`; Create `desktop/src/main/plugins/__tests__/ipc-sidecar.test.ts`

**Interfaces — Produces:**
- IPC channel `gb:plugins:sidecar` (args: `method: string, path: string, body?: unknown`) → `{ ok:true, data } | { ok:false, error, status? }`.
- `window.gb.plugin(id).sidecar.request(method, path, body?)` (preload).
- `api.sidecar.request(method, path, body?)` on the renderer `PluginApi`.

- [ ] **Step 1: Write the guard unit test** `desktop/src/main/plugins/__tests__/ipc-sidecar.test.ts`:

```ts
import { describe, it, expect, vi } from 'vitest';

// The handler factory is pure over its deps; we test it directly.
import { makeSidecarHandler } from '../ipc';

describe('gb:plugins:sidecar guards', () => {
  const forward = vi.fn(async () => ({ ok: true, data: { hi: 1 } }));
  const handler = makeSidecarHandler({
    forward: forward as never,
    isAllowedMethod: (m: string) => ['GET', 'POST', 'PATCH', 'DELETE'].includes(m),
    demo: false,
    handleDemoApi: vi.fn(),
  });

  it('rejects non-/v1 paths', async () => {
    expect(await handler('GET', '/etc/passwd')).toEqual({ ok: false, error: expect.stringContaining('/v1/') });
    expect(forward).not.toHaveBeenCalled();
  });
  it('rejects disallowed methods', async () => {
    expect(await handler('OPTIONS', '/v1/import/jira/issues')).toEqual({ ok: false, error: expect.stringContaining('Method') });
  });
  it('forwards a valid /v1 GET', async () => {
    const r = await handler('get', '/v1/import/confluence/spaces');
    expect(forward).toHaveBeenCalledWith('GET', '/v1/import/confluence/spaces', undefined);
    expect(r).toEqual({ ok: true, data: { hi: 1 } });
  });
  it('uses demo handler in demo mode', async () => {
    const demoFn = vi.fn(async () => ({ ok: true, data: 'demo' }));
    const h = makeSidecarHandler({ forward: forward as never, isAllowedMethod: () => true, demo: true, handleDemoApi: demoFn as never });
    expect(await h('GET', '/v1/x')).toEqual({ ok: true, data: 'demo' });
  });
});
```

- [ ] **Step 2:** `cd /tmp/gb-import/desktop && npx vitest run src/main/plugins/__tests__/ipc-sidecar.test.ts` → FAIL (no `makeSidecarHandler`).

- [ ] **Step 3: Add `makeSidecarHandler` + registration to `ipc.ts`.** At the top add imports and a factory; register inside `installPluginsIpc`. The factory (put above `installPluginsIpc`):

```ts
import type { Sidecar } from '../sidecar';

type ApiResult = { ok: true; data: unknown } | { ok: false; error: string; status?: number };

export function makeSidecarHandler(deps: {
  forward: (m: string, p: string, b?: unknown) => Promise<ApiResult>;
  isAllowedMethod: (m: string) => boolean;
  demo: boolean;
  handleDemoApi: (m: string, p: string, b?: unknown) => Promise<ApiResult> | ApiResult;
}) {
  return async (method: unknown, path: unknown, body?: unknown): Promise<ApiResult> => {
    if (typeof method !== 'string' || typeof path !== 'string') {
      return { ok: false, error: 'Invalid request shape' };
    }
    const m = method.toUpperCase();
    if (!deps.isAllowedMethod(m)) return { ok: false, error: 'Method not allowed' };
    if (!path.startsWith('/v1/')) return { ok: false, error: 'Path not allowed (must start with /v1/)' };
    if (deps.demo) return deps.handleDemoApi(m, path, body);
    return deps.forward(m, path, body);
  };
}
```

Extend `installPluginsIpc`'s options to accept `{ loader, pluginsRoot, sidecarBridge }` where `sidecarBridge` is the ready-made handler, and register it:

```ts
ipcMain.handle('gb:plugins:sidecar', (_e, method, path, body) => opts.sidecarBridge(method, path, body));
```

- [ ] **Step 4: Wire real deps in `src/main/index.ts`.** In `installPlugins()`, build the handler from the module-level `sidecar`, `isAllowedMethod`, `DEMO`, `handleDemoApi`, and the existing `forward`, and pass it to `installPluginsIpc`:

```ts
import { makeSidecarHandler } from './plugins/ipc';
// ...inside installPlugins(), after loader is created:
const sidecarBridge = makeSidecarHandler({
  forward: (m, p, b) => forward(sidecar, m as never, p, b),
  isAllowedMethod,
  demo: DEMO,
  handleDemoApi: (m, p, b) => handleDemoApi(m as never, p, b),
});
installPluginsIpc({ loader, pluginsRoot, sidecarBridge });
```

- [ ] **Step 5: Preload** — add to the `plugin(id)` object in `src/preload/index.ts`:

```ts
    sidecar: {
      request: (method: string, path: string, body?: unknown) =>
        ipcRenderer.invoke('gb:plugins:sidecar', method, path, body),
    },
```

- [ ] **Step 6: Types** — in `src/shared/types.ts`, add to the `plugin(id: string)` return type:

```ts
    sidecar: {
      request(
        method: string,
        path: string,
        body?: unknown,
      ): Promise<{ ok: true; data: unknown } | { ok: false; error: string; status?: number }>;
    };
```

- [ ] **Step 7: PluginApi** — in `PluginHost.tsx`, add to the `PluginApi` interface and the `api` object:

```ts
// interface PluginApi { ... add:
  sidecar: { request(method: string, path: string, body?: unknown): Promise<{ ok: true; data: unknown } | { ok: false; error: string; status?: number }> };
// api object { ... add:
      sidecar: bridge.sidecar,
```

- [ ] **Step 8: Test stub** — in `src/renderer/test/setup.ts`, add `sidecar: { request: async () => ({ ok: true, data: null }) }` to the `plugin()` stub return.

- [ ] **Step 9:** `npx vitest run src/main/plugins/__tests__/ipc-sidecar.test.ts` → PASS; `npm run typecheck` clean.

- [ ] **Step 10: Commit**

```bash
git add desktop/src/shared/types.ts desktop/src/preload/index.ts desktop/src/main/plugins/ipc.ts desktop/src/main/index.ts desktop/src/renderer/components/PluginHost.tsx desktop/src/renderer/test/setup.ts desktop/src/main/plugins/__tests__/ipc-sidecar.test.ts
git commit -m "feat(plugins): sidecar bridge — plugins can call /v1/* through the host"
```

### Task 2: Remove the import tab from core

**Files:** Delete `desktop/src/renderer/screens/import.tsx`; Modify `desktop/src/renderer/lib/api/hooks.ts`, `desktop/src/shared/api-types.ts`, `desktop/src/renderer/components/Sidebar.tsx`, `desktop/src/renderer/App.tsx`, `desktop/src/renderer/stores/navigation.ts`

**Interfaces:** Consumes nothing new. Produces a core with no import screen; `/v1/import` backend + connectors untouched.

- [ ] **Step 1:** Delete the screen: `git rm desktop/src/renderer/screens/import.tsx`.
- [ ] **Step 2:** In `hooks.ts`, delete the Atlassian-import section — from the `// ── Atlassian import ──` banner (line ~548) through the end of `useImportItems` (the block containing `useImportSpaces`, `useConfluencePages`, `useConfluenceSearch`, `useJiraIssues`, `ImportRunVars`, `useImportItems`). Remove now-unused type imports at the top (`ConfluencePagesResponse, ImportItem, ImportItemResult, ImportJiraIssue, ImportPage, ImportResponse, ImportSpace`) — keep any still used elsewhere in the file (check with a grep after).
- [ ] **Step 3:** In `api-types.ts`, delete lines from `// ── Atlassian import (mirrors …) ──` (line 345) through the blank line before `// ── Projects ──` (i.e. the seven interfaces + `ImportItemKind`). Leave `ConfluenceExportRequest/Response` (unrelated, kept).
- [ ] **Step 4:** In `Sidebar.tsx`, delete the `{ id: 'import', icon: 'download', label: 'import' },` line from `NAV_ITEMS`.
- [ ] **Step 5:** In `App.tsx`, delete `import { ImportScreen } from './screens/import';` and the `{active === 'import' && <ImportScreen />}` line.
- [ ] **Step 6:** In `stores/navigation.ts`, remove `| 'import'` from the `ScreenId` union.
- [ ] **Step 7:** `npm run typecheck` → clean (fix any dangling references it flags). `npx vitest run` → all pass (remove any import-screen test file if one exists: `ls desktop/src/renderer/screens/__tests__/import*` and `git rm` if present).
- [ ] **Step 8: Dev-app smoke** — `npm run build` then launch the built app (or `npm run dev`), open the sidebar: no `import` item; `window.gb.plugin('x').sidecar` is a function; other screens render.
- [ ] **Step 9: Commit**

```bash
git add -A
git commit -m "feat(import): extract Atlassian import into an installable plugin — remove core tab

Import UI is now the poltergeist-atlassian-import plugin; the /v1/import backend
and connectors config stay in core."
```

- [ ] **Step 10: Push branch + open PR**

```bash
git push -u origin feat/atlassian-import-plugin
gh pr create --base main --title "feat: sidecar bridge + extract Atlassian import to a plugin" --body "<summary + link to spec>"
```

### Task 3: Scaffold the plugin repo

**Files (new repo `~/development/nikrich/poltergeist-atlassian-import`):** `manifest.json`, `package.json`, `build.mjs`, `.gitignore`, `README.md`

**Interfaces — Produces:** the plugin package skeleton; `mount` implemented in Task 4/5.

- [ ] **Step 1:** `mkdir -p ~/development/nikrich/poltergeist-atlassian-import/src/ui && cd` there, `git init -b main`.
- [ ] **Step 2:** `manifest.json`:

```json
{
  "id": "atlassian-import",
  "name": "Atlassian Import",
  "version": "0.1.0",
  "description": "Browse and import Jira issues and Confluence pages into your vault",
  "apiVersion": 1,
  "icon": "download",
  "entry": { "renderer": "dist/renderer.mjs" }
}
```

- [ ] **Step 3:** `package.json` (mirror the Séance plugin): scripts `build: node build.mjs`; devDeps `esbuild ^0.25.0`, `react ^19.0.0`, `react-dom ^19.0.0`. `.gitignore` = `node_modules/`.
- [ ] **Step 4:** `build.mjs` — esbuild renderer only:

```js
import { build } from 'esbuild';
await build({
  entryPoints: ['src/renderer.jsx'],
  outfile: 'dist/renderer.mjs',
  bundle: true, platform: 'browser', format: 'esm', jsx: 'automatic',
  minify: true, define: { 'process.env.NODE_ENV': '"production"' }, logLevel: 'info',
});
```

- [ ] **Step 5:** `npm install`. Commit `chore: scaffold atlassian-import plugin`.

### Task 4: Plugin UI — browse + not-configured state

**Files:** Create `src/renderer.jsx`, `src/ui/theme.js`, `src/ui/ConfluenceBrowse.jsx`, `src/ui/JiraBrowse.jsx`

**Interfaces — Consumes:** `api.sidecar.request`, `api.theme`. **Produces:** `mount(el, api)` rendering the two-tab browser; selection state lifted to the App.

- [ ] **Step 1:** `src/ui/theme.js` — export `readTheme(api)` returning `{paper, vellum, fog, hairline, ink0, ink1, ink2, neon, moss, oxblood}` with dark fallbacks (copy the pattern from the Séance plugin's `useTheme`).
- [ ] **Step 2:** `src/renderer.jsx` — `mount(el, api)` creates a React root, renders `<ImportApp api={api}/>`, returns `() => root.unmount()`. `ImportApp`: state `tab` (`confluence|jira`), `selection` (Map keyed by `selectionKey(item)` where `selectionKey = ({kind, site, id, key}) => \`${kind}:${site}:${id ?? key ?? ''}\``), `notConfigured`. On mount, a helper `call(method, path, body)` wraps `api.sidecar.request` → returns `data` or throws; a 409 sets `notConfigured=true`. Render: header with two tab buttons + import bar; if `notConfigured`, a panel "Configure the Atlassian connector in Settings → Connectors, then reopen this tab."
- [ ] **Step 3:** `ConfluenceBrowse.jsx` — space `<select>` from `GET /v1/import/confluence/spaces` (`ImportSpace[]`: `{site, siteSlug, key, name, context}`), then a page list from `GET /v1/import/confluence/pages?site=&space=&parent=&limit=25&cursor=` (`{items: ImportPage[], nextCursor}`); `ImportPage` = `{site,id,title,type:'page'|'folder',parentId,hasChildren,updatedAt,version,space}`. Folders are navigable (click to drill via `parent=id`), pages are selectable (checkbox toggles selection with `{kind:'confluence_page', site, id}`). A search box calls `GET /v1/import/confluence/search?q=` (`ImportPage[]`). "load more" uses `nextCursor`.
- [ ] **Step 4:** `JiraBrowse.jsx` — a search box → `GET /v1/import/jira/issues?q=` (`ImportJiraIssue[]` = `{site,key,summary,status,project,updatedAt}`); each row selectable with `{kind:'jira_issue', site, key}`.
- [ ] **Step 5:** `node build.mjs`; `node -e "import('./dist/renderer.mjs').then(m=>console.log(typeof m.mount))"` → `function`. Commit `feat: browse Confluence spaces/pages and Jira issues`.

### Task 5: Plugin UI — import with progress

**Files:** Create `src/ui/SelectionBar.jsx`; Modify `src/renderer.jsx`

**Interfaces — Consumes:** selection Map, `call`. **Produces:** import action.

- [ ] **Step 1:** `SelectionBar.jsx` — shows selected count + an "import N" button; disabled when empty or importing. Clicking runs `runImport(items)`:

```js
async function runImport(items, call, onProgress) {
  const results = [];
  for (let i = 0; i < items.length; i++) {
    onProgress(i, items.length, items[i]);
    try {
      const data = await call('POST', '/v1/import', { items: [items[i]] }); // ImportResponse {results:[ImportItemResult]}
      results.push(data.results?.[0] ?? { ok: false, error: 'no result' });
    } catch (e) {
      results.push({ ok: false, error: String(e?.message ?? e) });
    }
  }
  return results; // ImportItemResult[]
}
```

Progress renders "3/7 — importing <title/key>…"; on finish, a summary "imported X, failed Y" with failed keys listed. Clear selection on success.
- [ ] **Step 2:** Wire into `ImportApp`: pass `selection` values as the items array; show `SelectionBar` above the browse panes.
- [ ] **Step 3:** `node build.mjs`. Commit `feat: batch import selected items with progress`. Push repo to `nikrich/poltergeist-atlassian-import` (create public repo via `gh repo create`).

### Task 6: Live verification + ship

- [ ] **Step 1:** Run the ghost-brain **branch** build (the bridge lives on `feat/atlassian-import-plugin`, not yet released): `cd /tmp/gb-import/desktop && npm run build`, launch built app. (Alternatively wait for the v0.6.0 release, but the branch build is enough to verify the bridge.)
- [ ] **Step 2:** Plugins → install from git `https://github.com/nikrich/poltergeist-atlassian-import` (no subdir) → an "Atlassian Import" entry appears with the download icon.
- [ ] **Step 3:** Open it. If your Atlassian connector is configured: browse a Confluence space, select a page, import it, confirm the note appears in the vault (check `~/ghostbrain/vault/20-contexts/*/confluence/`). Jira: search, select an issue, import, confirm. If NOT configured: confirm the not-configured panel shows (no crash).
- [ ] **Step 4:** Merge the ghost-brain PR; cut **v0.6.0** via the release worktree flow (bump `desktop/package.json` + `.release-please-manifest.json` to `0.6.0`, prepend `desktop/CHANGELOG.md`, `chore: release 0.6.0`, tag, push — the release.yml fallback builds+publishes). Release note: "Atlassian import is now an installable plugin: Plugins → install from git `https://github.com/nikrich/poltergeist-atlassian-import`."
- [ ] **Step 5:** Add the plugin's git URL to the plugin `README.md` install section; final commit + push.

## Self-review notes

- Spec coverage: Part 1 bridge (T1), Part 3 removal (T2), plugin scaffold/UI/import (T3–T5), sequencing+live+release (T6). Connectors + Python backend explicitly untouched.
- Type consistency: `selectionKey` shape, `ImportSpace/ImportPage/ImportJiraIssue/ImportItem/ImportResponse/ImportItemResult` field names copied verbatim from `api-types.ts` (T4/T5) so the plugin's inlined shapes match the backend contract; `makeSidecarHandler` signature identical in T1 test, impl, and index.ts wiring.
- The bridge is testable without electron by factoring `makeSidecarHandler` as a pure function over injected deps (no ipcMain in the unit test).
- Renderer-only plugin (no main.cjs) exercises the loader's main-optional path already built and tested for the loader.
