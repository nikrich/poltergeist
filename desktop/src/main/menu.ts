import { Menu, BrowserWindow, app, shell, type MenuItemConstructorOptions } from 'electron';

export function buildAppMenu(): void {
  const isMac = process.platform === 'darwin';
  const isDev = !!process.env.ELECTRON_RENDERER_URL;

  const macAppMenu: MenuItemConstructorOptions = {
    label: app.name,
    submenu: [
      { role: 'about' },
      { type: 'separator' },
      {
        label: 'Settings…',
        accelerator: 'Cmd+,',
        click: () => {
          BrowserWindow.getAllWindows()[0]?.webContents.send('gb:nav:settings');
        },
      },
      { type: 'separator' },
      { role: 'services' },
      { type: 'separator' },
      { role: 'hide' },
      { role: 'hideOthers' },
      { role: 'unhide' },
      { type: 'separator' },
      { role: 'quit' },
    ],
  };

  const fileMenu: MenuItemConstructorOptions = {
    label: 'File',
    submenu: isMac
      ? [{ role: 'close' }]
      : [
          {
            label: 'Settings…',
            accelerator: 'Ctrl+,',
            click: () => {
              BrowserWindow.getAllWindows()[0]?.webContents.send('gb:nav:settings');
            },
          },
          { type: 'separator' },
          { role: 'quit' },
        ],
  };

  const editMenu: MenuItemConstructorOptions = {
    label: 'Edit',
    submenu: [
      { role: 'undo' },
      { role: 'redo' },
      { type: 'separator' },
      { role: 'cut' },
      { role: 'copy' },
      { role: 'paste' },
      ...(isMac
        ? [
            { role: 'pasteAndMatchStyle' as const },
            { role: 'delete' as const },
            { role: 'selectAll' as const },
          ]
        : [{ role: 'delete' as const }, { type: 'separator' as const }, { role: 'selectAll' as const }]),
    ],
  };

  const viewMenu: MenuItemConstructorOptions = {
    label: 'View',
    submenu: [
      ...(isDev
        ? [
            { role: 'reload' as const },
            { role: 'forceReload' as const },
            { type: 'separator' as const },
          ]
        : []),
      // DevTools available in all builds so users can inspect UI issues
      // and we don't need a debug build to diagnose layout/CSS bugs.
      // macOS default accelerator: Cmd+Option+I.
      { role: 'toggleDevTools' as const },
      { type: 'separator' as const },
      { role: 'resetZoom' },
      { role: 'zoomIn' },
      { role: 'zoomOut' },
      { type: 'separator' },
      { role: 'togglefullscreen' },
    ],
  };

  const windowMenu: MenuItemConstructorOptions = {
    label: 'Window',
    submenu: isMac
      ? [
          { role: 'minimize' },
          { role: 'zoom' },
          { type: 'separator' },
          { role: 'front' },
        ]
      : [{ role: 'minimize' }, { role: 'zoom' }, { role: 'close' }],
  };

  const helpMenu: MenuItemConstructorOptions = {
    label: 'Help',
    submenu: [
      {
        label: 'Open project on GitHub',
        click: () => void shell.openExternal('https://github.com/nikrich/poltergeist'),
      },
    ],
  };

  const template: MenuItemConstructorOptions[] = isMac
    ? [macAppMenu, fileMenu, editMenu, viewMenu, windowMenu, helpMenu]
    : [fileMenu, editMenu, viewMenu, windowMenu, helpMenu];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}
