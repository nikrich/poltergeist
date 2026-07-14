import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// vi.hoisted ensures these are available when the vi.mock factories run below
// (vi.mock is hoisted above plain const declarations by Vitest's transform).
const { appMock, ipcMainMock, browserWindowMock, autoUpdaterMock, sendMock } = vi.hoisted(() => {
  const sendMock = vi.fn();
  const browserWindowMock = {
    getAllWindows: vi.fn(() => [{ webContents: { send: sendMock } }]),
  };
  const appMock = { isPackaged: true };
  const ipcMainMock = { handle: vi.fn() };
  const autoUpdaterMock = {
    autoDownload: true,
    on: vi.fn(),
    checkForUpdates: vi.fn().mockResolvedValue(null),
    downloadUpdate: vi.fn().mockResolvedValue([]),
    quitAndInstall: vi.fn(),
  };
  return { appMock, ipcMainMock, browserWindowMock, autoUpdaterMock, sendMock };
});

vi.mock('electron', () => ({
  app: appMock,
  BrowserWindow: browserWindowMock,
  ipcMain: ipcMainMock,
}));

vi.mock('electron-updater', () => ({
  autoUpdater: autoUpdaterMock,
}));

import { installUpdater } from '../updater';

// Pulls the handler registered for a given autoUpdater event/ipcMain channel
// out of the mock's call list.
function listenerFor(event: string): (...args: unknown[]) => void {
  const call = autoUpdaterMock.on.mock.calls.find(([name]) => name === event);
  if (!call) throw new Error(`no listener registered for ${event}`);
  return call[1] as (...args: unknown[]) => void;
}

function handlerFor(channel: string): (...args: unknown[]) => unknown {
  const call = ipcMainMock.handle.mock.calls.find(([name]) => name === channel);
  if (!call) throw new Error(`no ipcMain.handle registered for ${channel}`);
  return call[1] as (...args: unknown[]) => unknown;
}

describe('installUpdater', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    appMock.isPackaged = true;
    delete process.env.APPIMAGE;
    Object.defineProperty(process, 'platform', { value: 'darwin' });
    sendMock.mockClear();
    ipcMainMock.handle.mockClear();
    autoUpdaterMock.on.mockClear();
    autoUpdaterMock.autoDownload = true;
    autoUpdaterMock.checkForUpdates.mockClear().mockResolvedValue(null);
    autoUpdaterMock.downloadUpdate.mockClear().mockResolvedValue([]);
    autoUpdaterMock.quitAndInstall.mockClear();
    browserWindowMock.getAllWindows.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('does nothing when app.isPackaged is false', () => {
    appMock.isPackaged = false;
    installUpdater();
    expect(autoUpdaterMock.on).not.toHaveBeenCalled();
    expect(ipcMainMock.handle).not.toHaveBeenCalled();
    expect(autoUpdaterMock.checkForUpdates).not.toHaveBeenCalled();
    vi.advanceTimersByTime(4 * 60 * 60 * 1000);
    expect(autoUpdaterMock.checkForUpdates).not.toHaveBeenCalled();
  });

  it('disables autoDownload and checks for updates immediately, then every 4 hours', () => {
    installUpdater();
    expect(autoUpdaterMock.autoDownload).toBe(false);
    expect(autoUpdaterMock.checkForUpdates).toHaveBeenCalledTimes(1);

    vi.advanceTimersByTime(4 * 60 * 60 * 1000);
    expect(autoUpdaterMock.checkForUpdates).toHaveBeenCalledTimes(2);

    vi.advanceTimersByTime(4 * 60 * 60 * 1000);
    expect(autoUpdaterMock.checkForUpdates).toHaveBeenCalledTimes(3);
  });

  it('forwards update-available to the main window with canSelfUpdate true on macOS', () => {
    installUpdater();
    listenerFor('update-available')({ version: '1.2.3' });
    expect(sendMock).toHaveBeenCalledWith('gb:updates:available', {
      version: '1.2.3',
      canSelfUpdate: true,
    });
  });

  it('reports canSelfUpdate false on linux without APPIMAGE', () => {
    Object.defineProperty(process, 'platform', { value: 'linux' });
    delete process.env.APPIMAGE;
    installUpdater();
    listenerFor('update-available')({ version: '1.2.3' });
    expect(sendMock).toHaveBeenCalledWith('gb:updates:available', {
      version: '1.2.3',
      canSelfUpdate: false,
    });
  });

  it('reports canSelfUpdate true on linux with APPIMAGE set', () => {
    Object.defineProperty(process, 'platform', { value: 'linux' });
    process.env.APPIMAGE = '/path/to/App.AppImage';
    installUpdater();
    listenerFor('update-available')({ version: '1.2.3' });
    expect(sendMock).toHaveBeenCalledWith('gb:updates:available', {
      version: '1.2.3',
      canSelfUpdate: true,
    });
  });

  it('forwards download-progress to the main window', () => {
    installUpdater();
    listenerFor('download-progress')({ percent: 42.5 });
    expect(sendMock).toHaveBeenCalledWith('gb:updates:progress', { percent: 42.5 });
  });

  it('forwards update-downloaded to the main window', () => {
    installUpdater();
    listenerFor('update-downloaded')({ version: '1.2.3', downloadedFile: '/tmp/x' });
    expect(sendMock).toHaveBeenCalledWith('gb:updates:downloaded', { version: '1.2.3' });
  });

  it('gb:updates:download invokes downloadUpdate and resolves ok:true on success', async () => {
    installUpdater();
    const result = await handlerFor('gb:updates:download')();
    expect(autoUpdaterMock.downloadUpdate).toHaveBeenCalled();
    expect(result).toEqual({ ok: true });
  });

  it('gb:updates:download resolves ok:false with an error message instead of rejecting', async () => {
    autoUpdaterMock.downloadUpdate.mockRejectedValueOnce(new Error('network down'));
    installUpdater();
    const result = await handlerFor('gb:updates:download')();
    expect(result).toEqual({ ok: false, error: 'network down' });
  });

  it('gb:updates:install calls quitAndInstall', () => {
    installUpdater();
    handlerFor('gb:updates:install')();
    expect(autoUpdaterMock.quitAndInstall).toHaveBeenCalled();
  });

  it('swallows a failed checkForUpdates and retries on the next interval', async () => {
    autoUpdaterMock.checkForUpdates.mockRejectedValueOnce(new Error('offline'));
    installUpdater();
    // let the rejected initial-check promise settle before advancing timers
    await Promise.resolve();
    await Promise.resolve();
    expect(autoUpdaterMock.checkForUpdates).toHaveBeenCalledTimes(1);

    autoUpdaterMock.checkForUpdates.mockResolvedValueOnce(null);
    vi.advanceTimersByTime(4 * 60 * 60 * 1000);
    expect(autoUpdaterMock.checkForUpdates).toHaveBeenCalledTimes(2);
  });
});
