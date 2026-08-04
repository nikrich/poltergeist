import { describe, it, expect, vi, beforeEach } from 'vitest';

// vi.hoisted: vi.mock factories are hoisted above plain const declarations.
const { clipboardMock, ipcMainMock } = vi.hoisted(() => {
  const clipboardMock = { write: vi.fn() };
  const ipcMainMock = { handle: vi.fn(), removeHandler: vi.fn() };
  return { clipboardMock, ipcMainMock };
});

vi.mock('electron', () => ({
  clipboard: clipboardMock,
  ipcMain: ipcMainMock,
}));

import { installClipboardBridge } from '../clipboard';

type Handler = (
  event: unknown,
  payload: unknown,
) => { ok: true } | { ok: false; error: string };

function registeredHandler(): Handler {
  const call = ipcMainMock.handle.mock.calls.find(
    ([channel]) => channel === 'gb:clipboard:write-rich',
  );
  if (!call) throw new Error('gb:clipboard:write-rich was not registered');
  return call[1] as Handler;
}

describe('clipboard bridge', () => {
  beforeEach(() => {
    clipboardMock.write.mockClear();
    ipcMainMock.handle.mockClear();
    ipcMainMock.removeHandler.mockClear();
  });

  it('registers the gb:clipboard:write-rich handler', () => {
    installClipboardBridge();
    expect(ipcMainMock.handle).toHaveBeenCalledWith(
      'gb:clipboard:write-rich',
      expect.any(Function),
    );
  });

  it('writes both flavours to the system clipboard', () => {
    installClipboardBridge();
    const result = registeredHandler()(null, { html: '<h1>x</h1>', text: '# x' });
    expect(clipboardMock.write).toHaveBeenCalledWith({ html: '<h1>x</h1>', text: '# x' });
    expect(result).toEqual({ ok: true });
  });

  it('rejects malformed payloads without touching the clipboard', () => {
    installClipboardBridge();
    const result = registeredHandler()(null, { html: 42 });
    expect(clipboardMock.write).not.toHaveBeenCalled();
    expect(result.ok).toBe(false);
  });

  it('removes a previous handler before re-registering', () => {
    installClipboardBridge();
    installClipboardBridge();
    expect(ipcMainMock.removeHandler).toHaveBeenCalledWith('gb:clipboard:write-rich');
  });
});
