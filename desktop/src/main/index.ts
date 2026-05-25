import { app, BrowserWindow, ipcMain, shell } from 'electron';
import { join } from 'node:path';
import * as settings from './settings';
import { pickVaultFolder } from './dialogs';
import { settingsSchema } from '../shared/settings-schema';
import type { Settings } from '../shared/types';
import { loadInitialState, attachStatePersistence } from './window-state';
import { buildAppMenu } from './menu';
import { Sidecar } from './sidecar';
import { forward } from './api-forwarder';
import { installTray, type TrayController } from './tray';
import {
  installMeetingNotifier,
  type MeetingNotifierController,
} from './meeting-notifier';

// Repo root: in dev, that's one level up from the desktop/ project dir
// (app.getAppPath() resolves to the desktop/ folder). In prod (Phase 2 bundles
// the sidecar as a binary), this changes.
function repoRoot(): string {
  return join(app.getAppPath(), '..');
}

const sidecar = new Sidecar(repoRoot(), {
  schedulerEnabled: settings.getAll().schedulerEnabled,
});

let trayController: TrayController | null = null;
let meetingNotifier: MeetingNotifierController | null = null;

function showWindow(): void {
  let win = BrowserWindow.getAllWindows()[0];
  if (!win) {
    createWindow();
    win = BrowserWindow.getAllWindows()[0];
  }
  if (!win) return;
  if (win.isMinimized()) win.restore();
  win.show();
  win.focus();
}

async function quitApp(): Promise<void> {
  // Mark quit-in-progress so before-quit unwinds cleanly.
  isQuitting = true;
  app.quit();
}

let isQuitting = false;

function createWindow() {
  const isMac = process.platform === 'darwin';
  const initial = loadInitialState();
  const win = new BrowserWindow({
    x: initial.x,
    y: initial.y,
    width: initial.width,
    height: initial.height,
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
  if (initial.maximized) win.maximize();
  attachStatePersistence(win);
  win.on('ready-to-show', () => win.show());
  // On macOS, hide the window on close instead of destroying it. The tray
  // keeps the app reachable; explicit Quit comes from Cmd+Q / tray menu /
  // dock menu. On other platforms keep default close behavior — quit triggers
  // via window-all-closed below.
  if (isMac) {
    win.on('close', (event) => {
      if (!isQuitting) {
        event.preventDefault();
        win.hide();
      }
    });
  }
  if (process.env.ELECTRON_RENDERER_URL) {
    win.loadURL(process.env.ELECTRON_RENDERER_URL);
  } else {
    win.loadFile(join(__dirname, '../renderer/index.html'));
  }
}

ipcMain.handle('gb:settings:getAll', () => settings.getAll());

ipcMain.handle('gb:settings:set', async (_e, key: unknown, value: unknown) => {
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
  if (key === 'schedulerEnabled') {
    // Sidecar reads this from its launch env, so flipping it requires a restart.
    sidecar.setSchedulerEnabled(parsed.data as boolean);
    try {
      await sidecar.stop();
      await sidecar.start();
    } catch (err) {
      return {
        ok: false,
        error: `Sidecar restart failed: ${err instanceof Error ? err.message : String(err)}`,
      };
    }
  }
  return { ok: true };
});

ipcMain.handle('gb:dialogs:pickVaultFolder', () => pickVaultFolder());

ipcMain.handle('gb:shell:openPath', async (_e, p: unknown) => {
  if (typeof p !== 'string' || p === '') {
    return { ok: false, error: 'openPath: path must be a non-empty string' };
  }
  const vaultPath = settings.getAll().vaultPath;
  if (!vaultPath) {
    return { ok: false, error: 'openPath: vault path is not configured' };
  }
  // Allow opening the configured vault path itself or any path under it.
  // Reject anything else to prevent the renderer from opening arbitrary paths.
  const normalized = p.replace(/\\/g, '/');
  const allowed = vaultPath.replace(/\\/g, '/');
  if (normalized !== allowed && !normalized.startsWith(allowed + '/')) {
    return { ok: false, error: 'openPath: only the vault path is allowed' };
  }
  // shell.openPath resolves with "" on success or an error message on failure.
  const err = await shell.openPath(p);
  if (err) {
    console.error('[shell.openPath] failed:', err, 'path=', p);
    return { ok: false, error: err };
  }
  return { ok: true };
});

ipcMain.handle('gb:shell:openExternal', async (_e, url: unknown) => {
  if (typeof url !== 'string' || url === '') {
    return { ok: false, error: 'openExternal: url must be a non-empty string' };
  }
  // Allow only well-known external protocols so a stray markdown link can't
  // trigger `file://` or `vscode://` style handoffs.
  if (!/^(https?|mailto):/i.test(url)) {
    return { ok: false, error: `openExternal: protocol not allowed: ${url.slice(0, 32)}` };
  }
  try {
    await shell.openExternal(url);
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
});

app.whenReady().then(async () => {
  buildAppMenu();
  createWindow();
  trayController = installTray({
    onShow: showWindow,
    onSyncNow: async () => {
      // Best-effort fire-and-forget: surfacing errors here would interrupt the
      // tray flow. Failures show up via the connector status polling instead.
      try {
        await forward(sidecar, 'POST', '/v1/connectors/sync-all', undefined);
      } catch {
        // swallowed — see comment above
      }
    },
    onQuit: () => void quitApp(),
  });
  meetingNotifier = installMeetingNotifier({ sidecar });
  console.log('[sidecar] starting; repoRoot =', repoRoot());
  try {
    const info = await sidecar.start();
    console.log('[sidecar] READY port=', info.port);
    BrowserWindow.getAllWindows()[0]?.webContents.send('gb:sidecar:ready');
  } catch (err) {
    console.error('[sidecar] FAILED:', err instanceof Error ? err.message : String(err));
    BrowserWindow.getAllWindows()[0]?.webContents.send('gb:sidecar:failed', {
      reason: err instanceof Error ? err.message : String(err),
    });
  }
});

sidecar.on('ready', () => {
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send('gb:sidecar:ready');
  }
});

sidecar.on('failed', (info: { reason: string }) => {
  for (const win of BrowserWindow.getAllWindows()) {
    win.webContents.send('gb:sidecar:failed', info);
  }
});

let sidecarStopped = false;
app.on('before-quit', (event) => {
  meetingNotifier?.destroy();
  if (!sidecarStopped) {
    event.preventDefault();
    sidecarStopped = true;
    sidecar.stop().finally(() => app.quit());
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') app.quit();
});
app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

ipcMain.handle(
  'gb:api:request',
  async (_e, method: unknown, path: unknown, body: unknown) => {
    if (typeof method !== 'string' || typeof path !== 'string') {
      return { ok: false, error: 'Invalid request shape' };
    }
    const m = method.toUpperCase();
    if (m !== 'GET' && m !== 'POST') {
      return { ok: false, error: 'Method not allowed' };
    }
    if (!path.startsWith('/v1/')) {
      return { ok: false, error: 'Path not allowed (must start with /v1/)' };
    }
    return forward(sidecar, m, path, body);
  },
);

ipcMain.handle('gb:tray:setFailing', (_e, names: unknown) => {
  if (!Array.isArray(names)) {
    return { ok: false, error: 'expected string[]' };
  }
  const sanitized = names.filter((n): n is string => typeof n === 'string');
  trayController?.setFailing(sanitized);
  return { ok: true };
});

ipcMain.handle('gb:sidecar:retry', async () => {
  try {
    await sidecar.start();
    return { ok: true };
  } catch (err) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
});
