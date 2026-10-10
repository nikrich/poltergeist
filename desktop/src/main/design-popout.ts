import { BrowserWindow } from 'electron';
import { join } from 'node:path';

// The live design pop-out: a plain renderer window at #/design-popout that
// shows only the prototype / board, sized for screen-sharing. One at a time;
// opening again focuses it. The app-wide web-contents-created hook gives it
// the navigation guard like every other window.

let popout: BrowserWindow | null = null;

export function openDesignPopout(): void {
  if (popout && !popout.isDestroyed()) {
    if (popout.isMinimized()) popout.restore();
    popout.show();
    popout.focus();
    return;
  }
  const win = new BrowserWindow({
    width: 1280,
    height: 800,
    minWidth: 480,
    minHeight: 360,
    title: 'Poltergeist — Live design',
    backgroundColor: '#0E0F12',
    show: false,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      sandbox: true,
    },
  });
  popout = win;
  win.on('ready-to-show', () => win.show());
  // Keep our title; the renderer's <title> would replace it on load.
  win.on('page-title-updated', (event) => event.preventDefault());
  win.on('closed', () => {
    if (popout === win) popout = null;
  });
  if (process.env.ELECTRON_RENDERER_URL) {
    void win.loadURL(`${process.env.ELECTRON_RENDERER_URL}#/design-popout`);
  } else {
    void win.loadFile(join(__dirname, '../renderer/index.html'), { hash: '/design-popout' });
  }
}

export function closeDesignPopout(): void {
  if (popout && !popout.isDestroyed()) popout.close();
  popout = null;
}
