import { app, BrowserWindow, globalShortcut, ipcMain, session, shell } from 'electron';
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { realpath, stat } from 'node:fs/promises';
import { delimiter, dirname, isAbsolute, join } from 'node:path';
import * as settings from './settings';
import { pickVaultFolder } from './dialogs';
import { settingsSchema } from '../shared/settings-schema';
import type { Settings } from '../shared/types';
import { loadInitialState, attachStatePersistence } from './window-state';
import { buildAppMenu } from './menu';
import { Sidecar, buildExtraPath } from './sidecar';
import { forward, isAllowedMethod, requestHeadersFrom } from './api-forwarder';
import { startChatStream, stopChatStream } from './chat-stream';
import type { ChatStreamEvent } from '../shared/api-types';
import { docsStreamKey, isDocsAssistRequest, startDocsStream, stopDocsStream } from './docs-stream';
import { startRecorderStream, stopRecorderStream } from './recorder-stream';
import { exportPdf, renderVaultHtmlToPdf } from './pdf-export';
import { installTray, type TrayController } from './tray';
import {
  installMeetingNotifier,
  fireTargetChoiceNotification,
  type MeetingNotifierController,
} from './meeting-notifier';
import { installJotOverlay } from './jot-overlay';
import { installUpdater } from './updater';
import { installClipboardBridge } from './clipboard';
import { installCliShim } from './cli-shim';
import { isAllowedExternalUrl } from './external-url';
import { installNavigationGuard, prototypeRequestAllowed } from './navigation-guard';
import { rendererLoadTarget } from './renderer-entry';
import {
  registerGbAssetScheme,
  registerAssetProtocol,
  installAssetBridge,
} from './assets';
import { isInsideVault } from './vault-paths';
import { registerDocProtocol } from './doc-protocol';
import { handleDemoApi, DEMO_SETTINGS } from './demo/fixtures';
import { runDemoChatStream, stopDemoChat } from './demo/chat';
import { createLoader, type PluginLoader } from './plugins/loader';
import { installPluginsIpc, makeSidecarHandler } from './plugins/ipc';
import { registerPluginScheme, installPluginProtocol } from './plugins/protocol';
import { bundlePrototype } from './design-bundler';
import { registerDesignScheme, registerDesignProtocol, rootUrl, serveRoot } from './design-protocol';
import { closeDesignPopout, openDesignPopout } from './design-popout';
import {
  devServerCsp,
  DevServers,
  isAllowedWorktree,
  isPoltergeistWorktree,
  setSandboxVault,
} from './design-devserver';
import type { DesignBuildResult, DesignLiveEvent, DevServerResult } from '../shared/design-types';

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
  vaultPath: settings.getAll().vaultPath,
});

let trayController: TrayController | null = null;
let meetingNotifier: MeetingNotifierController | null = null;
let pluginLoader: PluginLoader | null = null;

// plugin:// and gbproto:// must be registered as privileged before app ready.
registerPluginScheme();
registerDesignScheme();

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
    fetchApi: (method, path, body, headers) => forward(sidecar, method, path, body, 900_000, headers),
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
    forward: (m, p, b, h) => forward(sidecar, m as never, p, b, undefined, h),
    isAllowedMethod,
    isKnownPlugin: (id) => loader.records().some((r) => r.id === id),
    demo: DEMO,
    handleDemoApi: (m, p, b) => handleDemoApi(m as never, p, b),
  });
  installPluginsIpc({ loader, pluginsRoot, sidecarBridge });
}

// The main window. Other windows (jot overlay, design pop-out) exist too, so
// "show the app" must not just grab the first BrowserWindow.
let mainWindow: BrowserWindow | null = null;

function showWindow(): void {
  if (!mainWindow || mainWindow.isDestroyed()) createWindow();
  const win = mainWindow;
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
  mainWindow = win;
  win.on('closed', () => {
    if (mainWindow === win) mainWindow = null;
    // The pop-out is a companion of the main window; without this it would
    // keep the app alive on Windows/Linux after the main window closed.
    closeDesignPopout();
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
  loadRenderer(win);
}

/**
 * Load (or reload) the main renderer. The "load remote images" setting selects
 * the HTML entry whose CSP <meta> allows https images; a meta policy can't be
 * loosened in place and file:// gets no response headers, so toggling the
 * setting swaps documents. `hash` carries the current route across the swap.
 */
function loadRenderer(win: BrowserWindow, hash?: string): void {
  const target = rendererLoadTarget({
    remoteImages: !DEMO && settings.getAll().loadRemoteImages === true,
    rendererDir: join(__dirname, '../renderer'),
    devServerUrl: process.env.ELECTRON_RENDERER_URL,
    hash,
  });
  if (target.kind === 'url') void win.loadURL(target.url);
  else void win.loadFile(target.path, target.hash ? { hash: target.hash } : undefined);
}

// Every webContents (main window, jot overlay, pdf-export, anything added
// later) gets the navigation guard: foreign navigations are cancelled and
// window.open is always denied so no external page inherits the preload
// bridge. Registered at module load, before any window exists.
app.on('web-contents-created', (_event, contents) => {
  installNavigationGuard(
    contents,
    {
      devServerUrl: process.env.ELECTRON_RENDERER_URL,
      rendererRoot: join(__dirname, '../renderer'),
    },
    {
      openExternal: (url) => shell.openExternal(url),
      isKnownDevServer: (origin) => devServers.isKnownOrigin(origin),
    },
  );
});

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
  if (key === 'loadRemoteImages') {
    // The CSP only changes with a new document: reload into the other entry
    // once this IPC reply is on its way.
    const win = mainWindow;
    if (win && !win.isDestroyed()) {
      let hash = '';
      try {
        hash = new URL(win.webContents.getURL()).hash;
      } catch {
        // no current URL — load the default route
      }
      setImmediate(() => {
        if (!win.isDestroyed()) loadRenderer(win, hash);
      });
    }
  }
  if (key === 'schedulerEnabled' || key === 'vaultPath') {
    // Both are read from the sidecar's launch env, so changing either needs a restart.
    if (key === 'schedulerEnabled') sidecar.setSchedulerEnabled(parsed.data as boolean);
    if (key === 'vaultPath') sidecar.setVaultPath(parsed.data as string);
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

ipcMain.handle('gb:shell:showItemInFolder', (_e, p: unknown) => {
  if (typeof p !== 'string' || p === '') {
    return { ok: false, error: 'showItemInFolder: path must be a non-empty string' };
  }
  const vaultPath = settings.getAll().vaultPath;
  if (!vaultPath || !isInsideVault(vaultPath, p, { allowRoot: false })) {
    return { ok: false, error: 'showItemInFolder: only paths inside the vault are allowed' };
  }
  shell.showItemInFolder(p);
  return { ok: true };
});

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
  // Allowlist lives in external-url.ts (http(s)/mailto everywhere; the macOS
  // Privacy & Security deep link on darwin only).
  if (!isAllowedExternalUrl(url, process.platform)) {
    return { ok: false, error: `openExternal: protocol not allowed: ${url.slice(0, 32)}` };
  }
  try {
    await shell.openExternal(url);
    return { ok: true };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : String(e) };
  }
});

ipcMain.handle('gb:cli:install', () => {
  if (process.platform !== 'darwin') {
    throw new Error('CLI shim install is only supported on macOS');
  }
  const binaryPath = join(process.resourcesPath, 'sidecar', 'ghostbrain-api', 'ghostbrain-api');
  if (!existsSync(binaryPath)) {
    throw new Error('bundled backend not found — dev build?');
  }
  return installCliShim({ binaryPath });
});

app.whenReady().then(async () => {
  registerAssetProtocol(vaultRoot);
  registerDocProtocol(vaultRoot);
  registerDesignProtocol();
  // Worktree dev servers serve agent-edited code: pin what it may reach.
  // Prototype frames (gbproto: and worktree dev servers) may only reach their
  // own origin and Google Fonts, whatever their page tries.
  session.defaultSession.webRequest.onBeforeRequest((details, callback) => {
    let frameUrl = '';
    try {
      frameUrl = details.frame?.url ?? '';
    } catch {
      // frame already gone
    }
    const known = (o: string) => devServers.isKnownOrigin(o);
    // Workers (service workers included) have no frame: judge them by their
    // referrer. A worker that suppresses its referrer still runs under the
    // CSP main injects into its own script response. Frameless requests
    // from main itself (updater) have neither and pass.
    const from = frameUrl || details.referrer || '';
    callback({ cancel: prototypeRequestAllowed(from, details.url, known) === false });
  });
  // No URL filter: match patterns can't express "any port"; the origin check
  // below does the filtering.
  session.defaultSession.webRequest.onHeadersReceived(
    (details, callback) => {
      let origin = '';
      try {
        origin = new URL(details.url).origin;
      } catch {
        // fall through untouched
      }
      if (!origin || !devServers.isKnownOrigin(origin)) {
        callback({});
        return;
      }
      callback({
        responseHeaders: {
          ...details.responseHeaders,
          'Content-Security-Policy': [devServerCsp(origin)],
          'X-DNS-Prefetch-Control': ['off'],
        },
      });
    },
  );
  installAssetBridge(vaultRoot);
  buildAppMenu();
  installPlugins();
  createWindow();
  // First-party renderer (loaded from our own bundle / dev server). Grant
  // camera/mic for webcam capture; deny everything else.
  session.defaultSession.setPermissionRequestHandler((_wc, permission, callback, details) => {
    // Generated live-design prototypes run in gbproto:// frames — never hand
    // them the microphone or camera.
    // Worktree dev servers (http://127.0.0.1:<port>) run agent-edited code:
    // nothing for them either.
    const from = details?.requestingUrl ?? '';
    const designFrame =
      from.startsWith('gbproto:') || from.startsWith('http://127.0.0.1:') || from.startsWith('http://localhost:');
    callback(permission === 'media' && !designFrame);
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

  // beforeInstall flips isQuitting so the main window's hide-on-close handler
  // lets Electron actually close it — otherwise quitAndInstall never proceeds.
  installUpdater({ beforeInstall: () => { isQuitting = true; } });

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
  devServers.stopAll();
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin' || DEMO) app.quit();
});
app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

ipcMain.handle(
  'gb:api:request',
  async (_e, method: unknown, path: unknown, body: unknown, opts: unknown) => {
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
    return forward(sidecar, m, path, body, undefined, requestHeadersFrom(opts));
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

// Recorder SSE routes the renderer follows: the live transcript and the
// waveform levels. Each is forwarded to `gb:recorder:<name>:event`.
for (const name of ['live', 'levels'] as const) {
  const path = `/v1/recorder/${name}`;
  ipcMain.handle(`gb:recorder:${name}:subscribe`, async (e) => {
    if (DEMO) return { ok: false, error: 'Not available in demo mode' };
    const wc = e.sender;
    const key = wc.id;
    const onDestroyed = () => stopRecorderStream(path, key);
    wc.once('destroyed', onDestroyed);
    try {
      return await startRecorderStream(sidecar, path, key, (event: unknown) => {
        if (!wc.isDestroyed()) wc.send(`gb:recorder:${name}:event`, event);
      });
    } finally {
      wc.removeListener('destroyed', onDestroyed);
    }
  });
  ipcMain.handle(`gb:recorder:${name}:unsubscribe`, (e) => {
    stopRecorderStream(path, e.sender.id);
    return { ok: true };
  });
}

// Live design session: follow /v1/design/live (same shape as the recorder
// streams), bundle prototypes in-process, and open the screen-share pop-out.
const DESIGN_LIVE_PATH = '/v1/design/live';

ipcMain.handle('gb:design:live:subscribe', async (e) => {
  if (DEMO) return { ok: false, error: 'Not available in demo mode' };
  const wc = e.sender;
  const key = wc.id;
  const onDestroyed = () => stopRecorderStream(DESIGN_LIVE_PATH, key);
  wc.once('destroyed', onDestroyed);
  try {
    return await startRecorderStream(sidecar, DESIGN_LIVE_PATH, key, (event: DesignLiveEvent) => {
      if (!wc.isDestroyed()) wc.send('gb:design:live:event', event);
    });
  } finally {
    wc.removeListener('destroyed', onDestroyed);
  }
});

ipcMain.handle('gb:design:live:unsubscribe', (e) => {
  stopRecorderStream(DESIGN_LIVE_PATH, e.sender.id);
  return { ok: true };
});

ipcMain.handle(
  'gb:design:build',
  async (_e, prototypeDir: unknown, rev: unknown): Promise<DesignBuildResult> => {
    const revNo = typeof rev === 'number' && Number.isInteger(rev) && rev >= 0 ? rev : 0;
    if (typeof prototypeDir !== 'string' || revNo !== rev) {
      return { ok: false, rev: revNo, error: 'Invalid request shape' };
    }
    if (DEMO) return { ok: false, rev: revNo, error: 'Not available in demo mode' };
    const vault = vaultRoot();
    if (!vault || !isAbsolute(prototypeDir)) {
      return { ok: false, rev: revNo, error: 'Prototype folder must be inside the vault' };
    }
    let dir: string;
    try {
      dir = await realpath(prototypeDir);
      if (!isInsideVault(await realpath(vault), dir, { allowRoot: false })) {
        return { ok: false, rev: revNo, error: 'Prototype folder must be inside the vault' };
      }
    } catch {
      return { ok: false, rev: revNo, error: 'Prototype folder not found' };
    }
    if (!existsSync(join(dir, 'src', 'main.tsx'))) {
      return { ok: false, rev: revNo, error: 'Prototype has no src/main.tsx' };
    }
    const id = serveRoot(dir);
    const res = await bundlePrototype(dir, revNo);
    return res.ok ? { ...res, url: rootUrl(id, res.url) } : res;
  },
);

ipcMain.handle('gb:design:popout', () => {
  openDesignPopout();
  return { ok: true };
});

// Worktree sessions preview the repo's own dev server. Each window is one
// viewer (it calls ensure on every rev, release on unmount); a closed window
// releases everything it was viewing.
const devServers = new DevServers();
const devServerViewers = new Set<number>();

ipcMain.handle(
  'gb:design:devserver:ensure',
  async (e, worktree: unknown, appDir: unknown): Promise<DevServerResult> => {
    if (typeof worktree !== 'string' || typeof appDir !== 'string') {
      return { ok: false, error: 'Invalid request shape' };
    }
    if (DEMO) return { ok: false, error: 'Not available in demo mode' };
    if (!isAbsolute(worktree) || !isAbsolute(appDir)) {
      return { ok: false, error: 'Not a Poltergeist worktree' };
    }
    let wt: string;
    let appReal: string;
    try {
      wt = await realpath(worktree);
      appReal = await realpath(appDir);
    } catch {
      return { ok: false, error: 'Worktree not found' };
    }
    if (!isAllowedWorktree(wt, appReal)) return { ok: false, error: 'Not a Poltergeist worktree' };
    const wc = e.sender;
    if (!devServerViewers.has(wc.id)) {
      devServerViewers.add(wc.id);
      const id = wc.id;
      wc.once('destroyed', () => {
        devServerViewers.delete(id);
        devServers.releaseViewer(String(id));
      });
    }
    const vault = vaultRoot();
    setSandboxVault(vault ? await realpath(vault).catch(() => vault) : null);
    return devServers.ensure(wt, appReal, String(wc.id));
  },
);

ipcMain.handle('gb:design:devserver:release', async (e, worktree: unknown) => {
  if (typeof worktree === 'string' && isAbsolute(worktree)) {
    // The worktree may already be gone (removed from the Artefacts tab).
    const wt = await realpath(worktree).catch(() => worktree);
    devServers.release(wt, String(e.sender.id));
  }
  return { ok: true };
});

/** `p` (a realpath) is a Poltergeist worktree or inside one. */
function inPoltergeistWorktree(p: string): boolean {
  for (let dir = p; ; dir = dirname(dir)) {
    if (isPoltergeistWorktree(dir)) return true;
    if (dirname(dir) === dir) return false;
  }
}

ipcMain.handle(
  'gb:design:open-path',
  async (_e, path: unknown, how: unknown): Promise<{ ok: boolean; error?: string }> => {
    if (typeof path !== 'string' || !isAbsolute(path) || (how !== 'editor' && how !== 'finder')) {
      return { ok: false, error: 'Invalid request shape' };
    }
    if (DEMO) return { ok: false, error: 'Not available in demo mode' };
    let target: string;
    try {
      target = await realpath(path);
    } catch {
      return { ok: false, error: 'Path not found' };
    }
    const vault = vaultRoot();
    const vaultReal = vault ? await realpath(vault).catch(() => '') : '';
    const allowed =
      (vaultReal !== '' && isInsideVault(vaultReal, target, { allowRoot: false })) ||
      inPoltergeistWorktree(target);
    if (!allowed) return { ok: false, error: 'Only artefact folders and Poltergeist worktrees can be opened' };
    if (how === 'finder') {
      shell.showItemInFolder(target);
      return { ok: true };
    }
    // Artefacts are folders; handing a file to the OS default opener could
    // launch it.
    if (!(await stat(target).then((st) => st.isDirectory()).catch(() => false))) {
      return { ok: false, error: 'Only folders can be opened in the editor' };
    }
    const extra = buildExtraPath(process.platform, process.env.HOME ?? '');
    const inherited = process.env.PATH ?? '';
    const env = { ...process.env, PATH: inherited ? `${extra}${delimiter}${inherited}` : extra };
    const viaCode = await new Promise<boolean>((resolveSpawn) => {
      try {
        const child = spawn('code', [target], { detached: true, shell: false, stdio: 'ignore', env });
        child.once('error', () => resolveSpawn(false));
        child.once('spawn', () => {
          child.unref();
          resolveSpawn(true);
        });
      } catch {
        resolveSpawn(false);
      }
    });
    if (viaCode) return { ok: true };
    const err = await shell.openPath(target);
    return err ? { ok: false, error: err } : { ok: true };
  },
);

const stopDocsTurn = (key: string) => {
  stopDocsStream(key);
  // Aborting the fetch alone leaves the sidecar generator blocked — tell the
  // sidecar to kill the turn as well (turn key docs:<key>).
  void forward(sidecar, 'POST', '/v1/docs/assist/stop', { stream_id: key });
};

ipcMain.handle('gb:docs:assist', async (e, req: unknown) => {
  if (!isDocsAssistRequest(req)) {
    return { ok: false, error: 'Invalid request shape' };
  }
  const key = docsStreamKey(req);
  const wc = e.sender;
  const onDestroyed = () => stopDocsTurn(key);
  wc.once('destroyed', onDestroyed);
  try {
    return await startDocsStream(sidecar, req, (event) => {
      if (!wc.isDestroyed()) wc.send('gb:docs:event', { key, jotId: key, event });
    });
  } finally {
    wc.removeListener('destroyed', onDestroyed);
  }
});

ipcMain.handle('gb:docs:assist-stop', (_e, key: unknown) => {
  if (typeof key !== 'string' || key === '') {
    return { ok: false, error: 'Invalid request shape' };
  }
  stopDocsTurn(key);
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

// The renderer polls /v1/recorder/status while recording; when the native
// capture helper reports it found no meeting window it asks main to raise an
// OS notification so a hidden/minimised window still surfaces the choice.
ipcMain.handle('gb:recorder:notifyTargetChoice', () => {
  fireTargetChoiceNotification({ onClick: showWindow });
  return { ok: true };
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
