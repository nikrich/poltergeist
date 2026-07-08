import { app, BrowserWindow, globalShortcut, ipcMain, session, shell } from 'electron';
import { join } from 'node:path';
import * as settings from './settings';
import { pickVaultFolder } from './dialogs';
import { settingsSchema } from '../shared/settings-schema';
import type { Settings } from '../shared/types';
import { loadInitialState, attachStatePersistence } from './window-state';
import { buildAppMenu } from './menu';
import { Sidecar } from './sidecar';
import { forward, isAllowedMethod } from './api-forwarder';
import { startChatStream, stopChatStream } from './chat-stream';
import type { ChatStreamEvent } from '../shared/api-types';
import { startDocsStream, stopDocsStream } from './docs-stream';
import { exportPdf, renderVaultHtmlToPdf } from './pdf-export';
import { installTray, type TrayController } from './tray';
import {
  installMeetingNotifier,
  type MeetingNotifierController,
} from './meeting-notifier';
import { installJotOverlay } from './jot-overlay';
import { installClipboardBridge } from './clipboard';
import {
  registerGbAssetScheme,
  registerAssetProtocol,
  installAssetBridge,
} from './assets';
import { handleDemoApi, DEMO_SETTINGS } from './demo/fixtures';
import { runDemoChatStream, stopDemoChat } from './demo/chat';
import { createLoader, type PluginLoader } from './plugins/loader';
import { installPluginsIpc, makeSidecarHandler } from './plugins/ipc';
import { registerPluginScheme, installPluginProtocol } from './plugins/protocol';

// Showcase recording mode: serve fully synthetic fixtures and never spawn the
// Python sidecar or touch the real vault. Enabled by the demo driver via env.
const DEMO = process.env.GHOSTBRAIN_DEMO === '1';

// Repo root: in dev, that's one level up from the desktop/ project dir
// (app.getAppPath() resolves to the desktop/ folder). In prod (Phase 2 bundles
// the sidecar as a binary), this changes.
function repoRoot(): string {
  return join(app.getAppPath(), '..');
}

function vaultRoot(): string {
  return settings.getAll().vaultPath ?? '';
}

const sidecar = new Sidecar(repoRoot(), {
  schedulerEnabled: settings.getAll().schedulerEnabled,
});

let trayController: TrayController | null = null;
let meetingNotifier: MeetingNotifierController | null = null;
let pluginLoader: PluginLoader | null = null;

// plugin:// must be registered as privileged before app ready.
registerPluginScheme();

function installPlugins(): void {
  const pluginsRoot = join(app.getPath('userData'), 'plugins');
  const dataRoot = join(app.getPath('userData'), 'plugin-data');
  const loader = createLoader({
    pluginsRoot,
    dataRoot,
    registerHandler: (channel, fn) => ipcMain.handle(channel, (_e, ...args) => fn(...args)),
    unregisterHandler: (channel) => ipcMain.removeHandler(channel),
    broadcast: (channel, payload) => {
      for (const win of BrowserWindow.getAllWindows()) {
        win.webContents.send(channel, payload);
      }
    },
    // 15-minute ceiling covers long LLM sweeps plugins may kick off.
    fetchApi: (method, path, body) => forward(sidecar, method, path, body, 900_000),
  });
  pluginLoader = loader;
  loader.scan();
  void loader.activateEnabled().then(() => {
    for (const win of BrowserWindow.getAllWindows()) {
      win.webContents.send('gb:plugins:changed', loader.active());
    }
  });
  installPluginProtocol((id) => loader.dirFor(id));
  const sidecarBridge = makeSidecarHandler({
    forward: (m, p, b) => forward(sidecar, m as never, p, b),
    isAllowedMethod,
    demo: DEMO,
    handleDemoApi: (m, p, b) => handleDemoApi(m as never, p, b),
  });
  installPluginsIpc({ loader, pluginsRoot, sidecarBridge });
}

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
  // In demo mode let the window close normally so the recorder's app.close()
  // terminates the process; otherwise keep the tray-resident hide-on-close.
  if (isMac && !DEMO) {
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

ipcMain.handle('gb:settings:getAll', () =>
  DEMO ? DEMO_SETTINGS : settings.getAll(),
);

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

installClipboardBridge();

// Privileged scheme must be registered before the app is ready.
registerGbAssetScheme();

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
  registerAssetProtocol(vaultRoot);
  installAssetBridge(vaultRoot);
  buildAppMenu();
  installPlugins();
  createWindow();
  // First-party renderer (loaded from our own bundle / dev server). Grant
  // camera/mic for webcam capture; deny everything else.
  session.defaultSession.setPermissionRequestHandler((_wc, permission, callback) => {
    callback(permission === 'media');
  });
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
  if (!DEMO) {
    meetingNotifier = installMeetingNotifier({ sidecar });
  }

  const hotkey = settings.getAll().hotkeys?.jotOverlay ?? 'Alt+J';
  installJotOverlay({
    accelerator: hotkey,
    sidecar,
    rendererUrl: process.env.ELECTRON_RENDERER_URL
      ? `${process.env.ELECTRON_RENDERER_URL}/overlay.html`
      : undefined,
    rendererFile: !process.env.ELECTRON_RENDERER_URL
      ? join(__dirname, '../renderer/overlay.html')
      : undefined,
  });

  if (DEMO) {
    // No backend in demo mode — tell the renderer the "sidecar" is ready so
    // the UI leaves its connecting state and renders against the fixtures.
    console.log('[demo] sidecar skipped — serving synthetic fixtures');
    BrowserWindow.getAllWindows()[0]?.webContents.send('gb:sidecar:ready');
    return;
  }

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
  isQuitting = true;
  meetingNotifier?.destroy();
  void pluginLoader?.deactivateAll();
  if (DEMO) return; // nothing to tear down — sidecar was never started
  if (!sidecarStopped) {
    event.preventDefault();
    sidecarStopped = true;
    sidecar.stop().finally(() => app.quit());
  }
});

app.on('will-quit', () => {
  globalShortcut.unregisterAll();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin' || DEMO) app.quit();
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
    if (!isAllowedMethod(m)) {
      return { ok: false, error: 'Method not allowed' };
    }
    if (!path.startsWith('/v1/')) {
      return { ok: false, error: 'Path not allowed (must start with /v1/)' };
    }
    if (DEMO) return handleDemoApi(m, path, body);
    return forward(sidecar, m, path, body);
  },
);

const stopTurn = (convId: string) => {
  stopChatStream(convId);
  // Aborting the fetch alone leaves the sidecar generator blocked on claude
  // output with the per-conversation busy guard held — tell the sidecar to
  // kill the turn as well.
  void forward(sidecar, 'POST', `/v1/chat/${encodeURIComponent(convId)}/stop`);
};

ipcMain.handle(
  'gb:chat:send',
  async (e, convId: unknown, text: unknown, attachmentPaths: unknown) => {
    if (typeof convId !== 'string' || typeof text !== 'string') {
      return { ok: false, error: 'Invalid request shape' };
    }
    const paths = Array.isArray(attachmentPaths)
      ? attachmentPaths.filter((p): p is string => typeof p === 'string')
      : [];
    const wc = e.sender;
    const send = (event: ChatStreamEvent) => {
      if (!wc.isDestroyed()) wc.send('gb:chat:event', { convId, event });
    };
    if (DEMO) {
      // Demo mode has no sidecar/vault — attachments aren't supported here.
      const onDestroyed = () => stopDemoChat(convId);
      wc.once('destroyed', onDestroyed);
      try {
        return await runDemoChatStream(convId, text, send);
      } finally {
        wc.removeListener('destroyed', onDestroyed);
      }
    }
    const onDestroyed = () => stopTurn(convId);
    wc.once('destroyed', onDestroyed);
    try {
      return await startChatStream(sidecar, convId, text, send, paths);
    } finally {
      wc.removeListener('destroyed', onDestroyed);
    }
  },
);

ipcMain.handle('gb:chat:stop', (_e, convId: unknown) => {
  if (typeof convId !== 'string') {
    return { ok: false, error: 'Invalid request shape' };
  }
  if (DEMO) stopDemoChat(convId);
  else stopTurn(convId);
  return { ok: true };
});

const stopDocsTurn = (jotId: string) => {
  stopDocsStream(jotId);
  // Aborting the fetch alone leaves the sidecar generator blocked — tell the
  // sidecar to kill the turn as well.
  void forward(sidecar, 'POST', '/v1/docs/assist/stop', { jot_id: jotId });
};

ipcMain.handle('gb:docs:assist', async (e, req: unknown) => {
  if (
    typeof req !== 'object' ||
    req === null ||
    typeof (req as Record<string, unknown>).jot_id !== 'string' ||
    typeof (req as Record<string, unknown>).mode !== 'string'
  ) {
    return { ok: false, error: 'Invalid request shape' };
  }
  const docsReq = req as import('../shared/api-types').DocsAssistRequest;
  const wc = e.sender;
  const onDestroyed = () => stopDocsTurn(docsReq.jot_id);
  wc.once('destroyed', onDestroyed);
  try {
    return await startDocsStream(sidecar, docsReq, (event) => {
      if (!wc.isDestroyed()) wc.send('gb:docs:event', { jotId: docsReq.jot_id, event });
    });
  } finally {
    wc.removeListener('destroyed', onDestroyed);
  }
});

ipcMain.handle('gb:docs:assist-stop', (_e, jotId: unknown) => {
  if (typeof jotId !== 'string') {
    return { ok: false, error: 'Invalid request shape' };
  }
  stopDocsTurn(jotId);
  return { ok: true };
});

ipcMain.handle('gb:docs:export-pdf', (e, payload: unknown) => {
  if (
    typeof payload !== 'object' ||
    payload === null ||
    typeof (payload as Record<string, unknown>).title !== 'string' ||
    typeof (payload as Record<string, unknown>).html !== 'string'
  ) {
    return { ok: false as const, error: 'export-pdf: expected { title: string, html: string }' };
  }
  return exportPdf(
    BrowserWindow.fromWebContents(e.sender),
    payload as { title: string; html: string },
  );
});

ipcMain.handle('gb:docs:open-generated', (_e, path: unknown) => {
  if (typeof path !== 'string' || path === '') {
    return { ok: false as const, error: 'open-generated: expected a path string' };
  }
  return renderVaultHtmlToPdf(settings.getAll().vaultPath ?? '', path);
});

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
