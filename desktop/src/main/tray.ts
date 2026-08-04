import {
  Tray,
  Menu,
  app,
  nativeImage,
  BrowserWindow,
  Notification,
  type MenuItemConstructorOptions,
} from 'electron';
import { join } from 'node:path';

let tray: Tray | null = null;
let failingConnectors: Set<string> = new Set();

function trayIconPath(): string {
  // electron-vite outputs main/preload/renderer next to one another. The icon
  // is shipped via the `build` directory which electron-builder copies into
  // the .app's Resources at packaging time, and which lives under
  // app.getAppPath()/build in dev.
  return join(app.getAppPath(), 'build', 'trayIcon.png');
}

function buildMenu(opts: {
  onShow: () => void;
  onSyncNow: () => void;
  onQuit: () => void;
}): Menu {
  const items: MenuItemConstructorOptions[] = [
    {
      label: failingConnectors.size > 0
        ? `${failingConnectors.size} connector${failingConnectors.size > 1 ? 's' : ''} failing`
        : 'All connectors healthy',
      enabled: false,
    },
    { type: 'separator' },
    { label: 'Show GhostBrain', click: opts.onShow },
    { label: 'Sync now', click: opts.onSyncNow },
    { type: 'separator' },
    { label: 'Quit GhostBrain', click: opts.onQuit, accelerator: 'CmdOrCtrl+Q' },
  ];
  return Menu.buildFromTemplate(items);
}

export interface TrayController {
  setFailing(names: string[]): void;
  destroy(): void;
}

export function installTray(opts: {
  onShow: () => void;
  onSyncNow: () => void;
  onQuit: () => void;
}): TrayController {
  if (tray) return makeController(opts);

  const image = nativeImage.createFromPath(trayIconPath());
  // 22pt is the macOS menubar height (44pt on retina). resize() handles both.
  const resized = image.resize({ width: 22, height: 22 });
  tray = new Tray(resized);
  tray.setToolTip('GhostBrain');
  tray.setContextMenu(buildMenu(opts));
  tray.on('click', () => opts.onShow());
  return makeController(opts);
}

function makeController(opts: {
  onShow: () => void;
  onSyncNow: () => void;
  onQuit: () => void;
}): TrayController {
  return {
    setFailing(names: string[]) {
      const prev = failingConnectors;
      failingConnectors = new Set(names);
      tray?.setContextMenu(buildMenu(opts));
      // Use the title slot for a visible alert mark — the bundled tray PNG is
      // a colored icon, not a template, so we can't recolor it to indicate
      // state. A leading "●" beside the icon is the next-best signal.
      if (failingConnectors.size > 0) {
        tray?.setTitle(' ●');
        tray?.setToolTip(`GhostBrain — ${failingConnectors.size} connector(s) failing`);
      } else {
        tray?.setTitle('');
        tray?.setToolTip('GhostBrain');
      }
      // Fire a one-shot notification for each connector that just transitioned.
      // We rely on the scheduler's own cooldown to avoid spamming on repeat
      // failures — by the time setFailing() is called again, the cooldown
      // window controls whether it appears in `names`.
      for (const name of failingConnectors) {
        if (!prev.has(name)) {
          notifyFailure(name);
        }
      }
    },
    destroy() {
      tray?.destroy();
      tray = null;
    },
  };
}

function notifyFailure(name: string): void {
  if (!Notification.isSupported()) return;
  const notification = new Notification({
    title: 'GhostBrain — connector failing',
    body: `${name} hasn't synced successfully. Open GhostBrain to see why.`,
    silent: false,
  });
  notification.on('click', () => {
    for (const win of BrowserWindow.getAllWindows()) {
      if (win.isMinimized()) win.restore();
      win.show();
      win.focus();
    }
  });
  notification.show();
}
