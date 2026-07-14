import { BrowserWindow, app, ipcMain } from 'electron';
import { autoUpdater } from 'electron-updater';

const CHECK_INTERVAL_MS = 4 * 60 * 60 * 1000;

interface UpdateAvailablePayload {
  version: string;
  canSelfUpdate: boolean;
}

interface UpdateProgressPayload {
  percent: number;
}

interface UpdateDownloadedPayload {
  version: string;
}

// electron-updater can self-update macOS (zip), Windows (NSIS), and Linux
// AppImage, but not a .deb install — the renderer falls back to opening the
// releases page when this is false.
function canSelfUpdate(): boolean {
  return process.platform !== 'linux' || Boolean(process.env.APPIMAGE);
}

// Mirrors the `BrowserWindow.getAllWindows()[0]` convention already used for
// main-window-only pushes elsewhere (see gb:sidecar:ready in index.ts) — the
// main window is always created before the lazily-opened jot overlay.
function sendToMainWindow(channel: string, payload: unknown): void {
  BrowserWindow.getAllWindows()[0]?.webContents.send(channel, payload);
}

function checkForUpdates(): void {
  autoUpdater.checkForUpdates().catch((err: unknown) => {
    console.error('[updater] checkForUpdates failed:', err);
  });
}

export function installUpdater(): void {
  if (!app.isPackaged) return;

  autoUpdater.autoDownload = false;

  autoUpdater.on('update-available', (info) => {
    sendToMainWindow('gb:updates:available', {
      version: info.version,
      canSelfUpdate: canSelfUpdate(),
    } satisfies UpdateAvailablePayload);
  });

  autoUpdater.on('download-progress', (info) => {
    sendToMainWindow('gb:updates:progress', {
      percent: info.percent,
    } satisfies UpdateProgressPayload);
  });

  autoUpdater.on('update-downloaded', (info) => {
    sendToMainWindow('gb:updates:downloaded', {
      version: info.version,
    } satisfies UpdateDownloadedPayload);
  });

  autoUpdater.on('error', (err) => {
    console.error('[updater] error event:', err);
  });

  ipcMain.handle('gb:updates:download', async () => {
    try {
      await autoUpdater.downloadUpdate();
      return { ok: true };
    } catch (err) {
      return { ok: false, error: err instanceof Error ? err.message : String(err) };
    }
  });

  ipcMain.handle('gb:updates:install', () => {
    autoUpdater.quitAndInstall();
  });

  checkForUpdates();
  setInterval(checkForUpdates, CHECK_INTERVAL_MS);
}
