import { beforeEach, describe, expect, it, vi } from 'vitest';

const { windows, BrowserWindowMock } = vi.hoisted(() => {
  type Handler = (...args: unknown[]) => void;
  type Mock = ReturnType<typeof vi.fn>;
  interface FakeWindow {
    handlers: Record<string, Handler>;
    loadURL: Mock;
    loadFile: Mock;
    focus: Mock;
  }
  const windows: FakeWindow[] = [];
  const BrowserWindowMock = vi.fn().mockImplementation(() => {
    const handlers: Record<string, Handler> = {};
    const win = {
      handlers,
      loadURL: vi.fn().mockResolvedValue(undefined),
      loadFile: vi.fn().mockResolvedValue(undefined),
      show: vi.fn(),
      focus: vi.fn(),
      restore: vi.fn(),
      close: vi.fn(() => handlers.closed?.()),
      isMinimized: vi.fn().mockReturnValue(false),
      isDestroyed: vi.fn().mockReturnValue(false),
      on: vi.fn((name: string, fn: Handler) => {
        handlers[name] = fn;
      }),
    };
    windows.push(win);
    return win;
  });
  return { windows, BrowserWindowMock };
});

vi.mock('electron', () => ({ BrowserWindow: BrowserWindowMock }));

import { closeDesignPopout, openDesignPopout } from '../design-popout';

describe('openDesignPopout', () => {
  beforeEach(() => {
    closeDesignPopout();
    windows.length = 0;
    BrowserWindowMock.mockClear();
    delete process.env.ELECTRON_RENDERER_URL;
  });

  it('loads the renderer at the pop-out route with the shared preload', () => {
    openDesignPopout();
    expect(BrowserWindowMock).toHaveBeenCalledTimes(1);
    const opts = BrowserWindowMock.mock.calls[0]![0] as {
      title: string;
      webPreferences: { preload: string; contextIsolation: boolean; sandbox: boolean };
    };
    expect(opts.title).toBe('Poltergeist — Live design');
    expect(opts.webPreferences).toMatchObject({ contextIsolation: true, sandbox: true });
    expect(opts.webPreferences.preload).toMatch(/preload[/\\]index\.js$/);
    expect(windows[0]!.loadFile).toHaveBeenCalledWith(expect.stringMatching(/renderer[/\\]index\.html$/), {
      hash: '/design-popout',
    });
  });

  it('uses the dev server URL in dev', () => {
    process.env.ELECTRON_RENDERER_URL = 'http://localhost:5173';
    openDesignPopout();
    expect(windows[0]!.loadURL).toHaveBeenCalledWith('http://localhost:5173#/design-popout');
  });

  it('focuses the existing window instead of opening a second', () => {
    openDesignPopout();
    openDesignPopout();
    expect(BrowserWindowMock).toHaveBeenCalledTimes(1);
    expect(windows[0]!.focus).toHaveBeenCalled();
  });

  it('opens a fresh window after the previous one closed', () => {
    openDesignPopout();
    windows[0]!.handlers.closed!();
    openDesignPopout();
    expect(BrowserWindowMock).toHaveBeenCalledTimes(2);
  });
});
