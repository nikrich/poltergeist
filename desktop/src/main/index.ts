import { app, BrowserWindow, ipcMain, shell } from 'electron';
import { join } from 'node:path';
import * as settings from './settings';
import { pickVaultFolder } from './dialogs';
import { settingsSchema } from '../shared/settings-schema';
import type { Settings } from '../shared/types';

function createWindow() {
  const isMac = process.platform === 'darwin';
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 1024,
    minHeight: 720,
    show: false,
    backgroundColor: '#0E0F12',
    titleBarStyle: isMac ? 'hiddenInset' : 'default',
    trafficLightPosition: isMac ? { x: 14, y: 14 } : undefined,
    icon: join(app.getAppPath(), 'build/icon.png'),
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      sandbox: true,
    },
  });
  win.on('ready-to-show', () => win.show());
  if (process.env.ELECTRON_RENDERER_URL) {
    win.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    win.loadFile(join(__dirname, '../renderer/index.html'));
  }
}

ipcMain.handle('gb:settings:getAll', () => settings.getAll());

ipcMain.handle('gb:settings:set', (_e, key: unknown, value: unknown) => {
  if (typeof key !== 'string' || !(key in settingsSchema.shape)) {
    return { ok: false, error: `Unknown setting: ${String(key)}` };
  }
  const fieldSchema = settingsSchema.shape[key as keyof typeof settingsSchema.shape];
  const parsed = fieldSchema.safeParse(value);
  if (!parsed.success) {
    const issue = parsed.error.issues[0]?.message ?? 'validation failed';
    return { ok: false, error: `Invalid value for ${key}: ${issue}` };
  }
  settings.setKey(key as keyof Settings, parsed.data as Settings[keyof Settings]);
  return { ok: true };
});

ipcMain.handle('gb:dialogs:pickVaultFolder', () => pickVaultFolder());

ipcMain.handle('gb:shell:openPath', async (_e, p: unknown) => {
  if (typeof p !== 'string') {
    return { ok: false, error: 'openPath: path must be a string' };
  }
  const vaultPath = settings.getAll().vaultPath;
  // Allow opening the configured vault path itself or any path under it.
  // Reject anything else to prevent the renderer from opening arbitrary paths.
  const normalized = p.replace(/\\/g, '/');
  const allowed = vaultPath.replace(/\\/g, '/');
  if (normalized !== allowed && !normalized.startsWith(allowed + '/')) {
    return { ok: false, error: 'openPath: only the vault path is allowed' };
  }
  await shell.openPath(p);
  return { ok: true };
});

app.whenReady().then(createWindow);
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
