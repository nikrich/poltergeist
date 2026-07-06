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

export function installPluginsIpc(opts: { loader: PluginLoader; pluginsRoot: string }): void {
  const { loader, pluginsRoot } = opts;

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
