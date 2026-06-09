import { describe, it, expect, vi, beforeEach } from 'vitest';

// vi.hoisted ensures these values are available when vi.mock factories run
// (vi.mock is hoisted to the top of the file by Vitest's transform, so plain
// const declarations above it are not yet initialised at that point).
const { globalShortcutMock, browserWindowMock } = vi.hoisted(() => {
  const globalShortcutMock = {
    register: vi.fn().mockReturnValue(true),
    unregister: vi.fn(),
    unregisterAll: vi.fn(),
  };

  const browserWindowMock = vi.fn().mockImplementation(() => ({
    loadFile: vi.fn(),
    loadURL: vi.fn(),
    show: vi.fn(),
    hide: vi.fn(),
    focus: vi.fn(),
    isVisible: vi.fn().mockReturnValue(false),
    on: vi.fn(),
    webContents: { send: vi.fn() },
  }));

  return { globalShortcutMock, browserWindowMock };
});

vi.mock('electron', () => ({
  app: { whenReady: () => Promise.resolve() },
  BrowserWindow: browserWindowMock,
  globalShortcut: globalShortcutMock,
  ipcMain: { handle: vi.fn(), on: vi.fn(), removeHandler: vi.fn() },
  screen: {
    getCursorScreenPoint: () => ({ x: 0, y: 0 }),
    getDisplayNearestPoint: () => ({
      bounds: { x: 0, y: 0, width: 1920, height: 1080 },
    }),
  },
}));

// Mock forward so tests don't need a real sidecar
vi.mock('../api-forwarder', () => ({
  forward: vi.fn().mockResolvedValue({ ok: true, data: null }),
}));

import { installJotOverlay, openJotOverlay } from '../jot-overlay';

describe('jot overlay', () => {
  beforeEach(() => {
    globalShortcutMock.register.mockClear();
    browserWindowMock.mockClear();
  });

  it('registers the configured accelerator at install time', () => {
    installJotOverlay({ accelerator: 'Alt+J', sidecar: null as never });
    expect(globalShortcutMock.register).toHaveBeenCalledWith(
      'Alt+J',
      expect.any(Function),
    );
  });

  it('logs but does not throw when registration fails', () => {
    globalShortcutMock.register.mockReturnValueOnce(false);
    expect(() =>
      installJotOverlay({ accelerator: 'Alt+J', sidecar: null as never }),
    ).not.toThrow();
  });

  it('creates the overlay window lazily on first open', () => {
    installJotOverlay({ accelerator: 'Alt+J', sidecar: null as never });
    expect(browserWindowMock).not.toHaveBeenCalled();
    openJotOverlay();
    expect(browserWindowMock).toHaveBeenCalledTimes(1);
    openJotOverlay();
    expect(browserWindowMock).toHaveBeenCalledTimes(1); // reused
  });
});
