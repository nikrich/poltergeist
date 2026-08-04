import { BrowserWindow, globalShortcut, ipcMain, screen } from 'electron';
import { join } from 'node:path';
import { forward } from './api-forwarder';
import type { Sidecar } from './sidecar';

const OVERLAY_WIDTH = 480;
const OVERLAY_HEIGHT = 260;

// Module-level state — one overlay per app lifetime.
let overlay: BrowserWindow | null = null;
let installedOptions: JotOverlayOptions | null = null;

export interface JotOverlayOptions {
  accelerator: string;
  /** The Sidecar instance used to forward POST /v1/notes on save. */
  sidecar: Sidecar;
  /** Dev-mode renderer URL, e.g. "http://localhost:5173/overlay.html" */
  rendererUrl?: string;
  /** Prod-mode renderer file path, e.g. join(__dirname, '../renderer/overlay.html') */
  rendererFile?: string;
}

function buildOverlay(): BrowserWindow {
  const cursor = screen.getCursorScreenPoint();
  const display = screen.getDisplayNearestPoint(cursor);
  const x = display.bounds.x + Math.round((display.bounds.width - OVERLAY_WIDTH) / 2);
  const y = display.bounds.y + Math.round((display.bounds.height - OVERLAY_HEIGHT) / 3);

  const win = new BrowserWindow({
    width: OVERLAY_WIDTH,
    height: OVERLAY_HEIGHT,
    x,
    y,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    show: false,
    vibrancy: 'hud', // macOS-only; silently ignored on other platforms

    webPreferences: {
      // Use the same preload bundle as the main window.
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  const opts = installedOptions;
  if (opts?.rendererUrl) {
    win.loadURL(opts.rendererUrl);
  } else if (opts?.rendererFile) {
    win.loadFile(opts.rendererFile);
  }
  // Auto-hide when the overlay loses focus so it acts like a quick-capture popup.
  win.on('blur', () => win.hide());
  // If the window is ever destroyed (crash recovery etc.), drop the stale
  // reference so the next open builds a fresh one instead of throwing.
  win.on('closed', () => {
    overlay = null;
  });
  return win;
}

export function openJotOverlay(): void {
  if (!overlay) {
    overlay = buildOverlay();
  }
  overlay.show();
  overlay.focus();
  overlay.webContents.send('gb:jot:focus');
}

export function closeJotOverlay(): void {
  overlay?.hide();
}

export function installJotOverlay(opts: JotOverlayOptions): void {
  if (installedOptions) {
    // Re-install (e.g. future hotkey reconfiguration): drop the previous
    // accelerator and IPC handlers first — a second ipcMain.handle for the
    // same channel throws.
    globalShortcut.unregister(installedOptions.accelerator);
    ipcMain.removeHandler('gb:jot:save');
    ipcMain.removeHandler('gb:jot:cancel');
  }
  installedOptions = opts;

  const registered = globalShortcut.register(opts.accelerator, () => {
    openJotOverlay();
  });
  if (!registered) {
    console.error(
      `[jot-overlay] failed to register accelerator: ${opts.accelerator}`,
    );
  }

  // IPC: renderer fires save (fire-and-forget).
  // The overlay closes immediately; the POST runs in the background.
  // On failure every open window receives 'gb:jot:save-failed'.
  ipcMain.handle('gb:jot:save', async (_e, body: string) => {
    closeJotOverlay();
    forward(opts.sidecar, 'POST', '/v1/notes', { body })
      .then((res) => {
        if (!res.ok) {
          BrowserWindow.getAllWindows().forEach((w) =>
            w.webContents.send('gb:jot:save-failed', {
              body,
              error: (res as { ok: false; error: string }).error,
            }),
          );
        }
      })
      .catch((err: unknown) => {
        BrowserWindow.getAllWindows().forEach((w) =>
          w.webContents.send('gb:jot:save-failed', {
            body,
            error: err instanceof Error ? err.message : String(err),
          }),
        );
      });
    return { ok: true };
  });

  ipcMain.handle('gb:jot:cancel', () => {
    closeJotOverlay();
    return { ok: true };
  });
}
