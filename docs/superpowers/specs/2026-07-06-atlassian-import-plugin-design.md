# Atlassian Import → Installable Plugin — Design

**Date:** 2026-07-06
**Status:** Approved design
**Repos:** host changes in `ghost-brain` (branch off `main`); new plugin repo `nikrich/poltergeist-atlassian-import`.

## Goal

Make Jira/Confluence import **opt-in**. Today the import tab ships in Poltergeist core; not everyone uses Atlassian. Extract the import **UI** into an installable, renderer-only plugin. The Python `/v1/import` backend and the connectors config stay in core (a plugin can't carry Python), but core no longer shows the tab — you install the plugin only if you use Atlassian.

## What moves and what stays

- **Moves** (out of core, into the plugin): the import screen (`desktop/src/renderer/screens/import.tsx`), its React-Query hooks (`hooks.ts`), the import-only types in `shared/api-types.ts`, the `import` Sidebar nav item, the `App.tsx` route, and `'import'` in the `ScreenId` union.
- **Stays** in core: the Python sidecar routes/models/repo under `ghostbrain/api/**/import_atlassian.py` (now consumed only by the plugin), and the connectors screen + connector auth (Atlassian credentials are configured there — the import feature reuses that auth via routing.yaml).

## Part 1 — Sidecar bridge (plugin-host capability, ghost-brain)

The only change to the plugin *system*. Plugin UIs currently get plugin-scoped IPC, plugin settings, `openExternal`, and `theme` — but no way to reach the sidecar. Add a guarded, general bridge to the renderer `PluginApi`:

```ts
// added to PluginApi (src/renderer/components/PluginHost.tsx) and the preload bridge
api.sidecar.request(method: HttpMethod, path: string, body?: unknown):
  Promise<{ ok: true; data: T } | { ok: false; error: string; status?: number }>
```

Wiring:
- New host IPC handler `gb:plugins:sidecar` in `src/main/plugins/ipc.ts`, calling the existing `forward(sidecar, method, path, body)`.
- **Guards mirror the app's own `gb:api:request` exactly** (`src/main/index.ts`): method must pass `isAllowedMethod`; path must start with `/v1/`. Reject otherwise with `{ ok:false, error }`. In DEMO mode, route to `handleDemoApi` like the app does.
- Preload (`src/preload/index.ts`): extend the per-plugin bridge (`window.gb.plugin(id)`) with `sidecar.request` mapping to `ipcRenderer.invoke('gb:plugins:sidecar', method, path, body)`. `PluginHost` passes it into the `api` object handed to `mount`.
- Reusable by any plugin; not import-specific.

## Part 2 — The plugin (`nikrich/poltergeist-atlassian-import`)

**Renderer-only** — exercises the loader's main-optional path. No `main.cjs`; all work is HTTP to the sidecar via the bridge.

```
manifest.json          # id: atlassian-import, name: "Atlassian Import", apiVersion: 1,
                       # icon: "download", entry: { renderer: "dist/renderer.mjs" }
package.json           # esbuild + react/react-dom devDeps (as in the Séance plugin)
build.mjs              # esbuild renderer.jsx → dist/renderer.mjs (minified, prod define)
src/renderer.jsx       # export function mount(el, api) — own React root
src/ui/*.jsx           # ImportScreen, tab strip, browse lists, selection, import progress
dist/                  # committed (pre-built rule)
```

Behavior (ports `import.tsx` faithfully, framework-free, inline styles from `api.theme`):
- Two tabs, Confluence and Jira. Confluence: space picker → paginated page tree + search; Jira: JQL/quick search list. Multi-select with a selection key `${kind}:${site}:${id|key}`.
- Import runs one POST per item to `/v1/import` (each a valid 1-item batch, matching the current hook), driving a "3/7 — importing …" progress line; per-item success/error surfaced.
- Data calls go through `api.sidecar.request('GET', '/v1/import/confluence/spaces')`, `.../pages?…`, `.../confluence/search?q=…`, `.../jira/issues?q=…`, and `POST /v1/import`.
- **Not-configured state:** a 409 from any browse call renders a "Configure the Atlassian connector in Settings → Connectors first" panel instead of an error.
- Theme-blended, dark-fallback inline styles; no core component imports (bundles its own).

## Part 3 — Core removal (ghost-brain, same PR as Part 1)

Delete: `screens/import.tsx`; the Atlassian import block in `lib/api/hooks.ts` (`useImportSpaces/useConfluencePages/useConfluenceSearch/useJiraIssues/useImportItems` + `ImportRunVars`); the import-only types in `shared/api-types.ts` (`ImportItem/ImportItemResult/ImportJiraIssue/ImportPage/ImportSpace/ImportResponse/ConfluencePagesResponse` — verify none are referenced by connectors/scheduled-sync before deleting; keep any that are shared); the `import` entry in `Sidebar.tsx` `NAV_ITEMS`; the `App.tsx` import + route; `'import'` from `ScreenId`. Remove now-unused imports. Keep the Python backend and connectors untouched.

## Sequencing

1. **ghost-brain PR**: sidecar bridge (Part 1) + core removal (Part 3) together. Verify `npm run typecheck` + full vitest + a dev-app smoke (import tab gone, other screens fine, `window.gb.plugin('x').sidecar` exists). Merge → cut **v0.6.0** (feat: sidecar bridge; the removal is a `feat`/`refactor` — import is now a plugin).
2. **plugin repo**: build against v0.6.0’s bridge. Live e2e — install from the new repo’s git URL, browse + import against the real Atlassian connector, confirm a note lands in the vault; confirm the 409 not-configured state.

## Testing

- **Unit (ghost-brain):** `gb:plugins:sidecar` guards — non-`/v1/` path rejected, disallowed method rejected, `/v1/import/...` GET forwarded (mock `forward`). Add to `src/main/plugins/__tests__/`.
- **Existing suite:** update `renderer/test/setup.ts` stub `plugin()` to include `sidecar.request`; remove/adjust any import-screen tests.
- **Plugin:** `node build.mjs` produces `dist/renderer.mjs` exporting `mount`; live install + browse + import + not-configured.

## Error handling

- Bridge: reject bad method/path with a clear `{ok:false,error}`; never throw to the renderer.
- Plugin: 409 → not-configured panel; other errors → inline error with the message; import continues past a failed item and reports which failed.

## Out of scope (v1)

- Moving the Python backend into a plugin (JS-only plugin system; backend stays).
- Auto-detecting a configured Atlassian connector to suggest the plugin (clean removal + release note instead).
- Any change to connectors, scheduled sync, or note formatting.
