import { BrowserWindow, dialog, ipcMain } from 'electron';
import { installFromFolder, installFromGit, uninstall } from './installer';
import * as store from './store';
import type { PluginLoader } from './loader';

// Host-side IPC for the Plugins screen. Plugin-scoped channels
// (gb:plugin:<id>:*) are registered by the loader; these are the gb:plugins:*
// management channels.

type Result = { ok: true } | { ok: false; error: string };

function err(e: unknown): Result {
  return { ok: false, error: e instanceof Error ? e.message : String(e) };
}

type ApiResult = { ok: true; data: unknown } | { ok: false; error: string; status?: number };

/**
 * The plugin sidecar bridge, factored as a pure function over injected deps so
 * it is unit-testable without electron. Guards mirror the app's own
 * gb:api:request handler: method allowlist + path must start with /v1/.
 */
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

export function installPluginsIpc(opts: {
  loader: PluginLoader;
  pluginsRoot: string;
  sidecarBridge: (method: unknown, path: unknown, body?: unknown) => Promise<ApiResult>;
}): void {
  const { loader, pluginsRoot } = opts;

  ipcMain.handle('gb:plugins:sidecar', (_e, method, path, body) =>
    opts.sidecarBridge(method, path, body),
  );

  const broadcastChanged = (): void => {
    for (const win of BrowserWindow.getAllWindows()) {
      win.webContents.send('gb:plugins:changed', loader.active());
    }
  };

  ipcMain.handle('gb:plugins:list', () => loader.records());
  ipcMain.handle('gb:plugins:active', () => loader.active());

  ipcMain.handle('gb:plugins:setEnabled', async (_e, id: unknown, on: unknown) => {
    if (typeof id !== 'string' || typeof on !== 'boolean') {
      return { ok: false, error: 'invalid arguments' };
    }
    try {
      await loader.setEnabled(id, on);
      broadcastChanged();
      return { ok: true };
    } catch (e) {
      return err(e);
    }
  });

  ipcMain.handle('gb:plugins:reload', async () => {
    try {
      await loader.reloadAll();
      broadcastChanged();
      return { ok: true };
    } catch (e) {
      return err(e);
    }
  });

  ipcMain.handle('gb:plugins:installFromFolder', async () => {
    try {
      const picked = await dialog.showOpenDialog({ properties: ['openDirectory'] });
      const src = picked.filePaths[0];
      if (picked.canceled || !src) return { ok: false, error: 'cancelled' };
      await installFromFolder(src, pluginsRoot);
      await loader.reloadAll();
      broadcastChanged();
      return { ok: true };
    } catch (e) {
      return err(e);
    }
  });

  ipcMain.handle('gb:plugins:installFromGit', async (_e, url: unknown, subdir: unknown) => {
    if (typeof url !== 'string' || (subdir !== undefined && typeof subdir !== 'string')) {
      return { ok: false, error: 'invalid arguments' };
    }
    try {
      await installFromGit(url, subdir || undefined, pluginsRoot);
      await loader.reloadAll();
      broadcastChanged();
      return { ok: true };
    } catch (e) {
      return err(e);
    }
  });

  ipcMain.handle('gb:plugins:uninstall', async (_e, id: unknown) => {
    if (typeof id !== 'string') return { ok: false, error: 'invalid arguments' };
    try {
      await loader.setEnabled(id, false);
      await uninstall(id, pluginsRoot);
      await loader.reloadAll();
      broadcastChanged();
      return { ok: true };
    } catch (e) {
      return err(e);
    }
  });

  ipcMain.handle('gb:plugins:data:get', (_e, id: unknown, key: unknown) => {
    if (typeof id !== 'string' || typeof key !== 'string') return undefined;
    return store.getData(id, key);
  });

  ipcMain.handle('gb:plugins:data:set', (_e, id: unknown, key: unknown, value: unknown) => {
    if (typeof id !== 'string' || typeof key !== 'string') {
      return { ok: false, error: 'invalid arguments' };
    }
    store.setData(id, key, value);
    return { ok: true };
  });
}
