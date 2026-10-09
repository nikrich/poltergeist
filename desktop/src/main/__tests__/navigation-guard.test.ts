import { describe, it, expect, vi } from 'vitest';
import { EventEmitter } from 'node:events';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import type { WebContents } from 'electron';

vi.mock('electron', () => ({
  shell: { openExternal: vi.fn() },
}));

import {
  isAppUrl,
  externalOpenTarget,
  installNavigationGuard,
} from '../navigation-guard';

// Build paths with path.join/resolve + pathToFileURL so the table holds on
// Windows (release builds run desktop tests on windows-2022) as well as POSIX.
const rendererRoot = resolve(join(__dirname, 'fake-app', 'out', 'renderer'));
const fileUrl = (...parts: string[]) => pathToFileURL(join(rendererRoot, ...parts)).toString();
const rootUrl = pathToFileURL(rendererRoot).toString();

describe('isAppUrl', () => {
  const dev = { devServerUrl: 'http://localhost:5173', rendererRoot };
  const prod = { rendererRoot };

  it.each([
    ['http://localhost:5173', true],
    ['http://localhost:5173/', true],
    ['http://localhost:5173/overlay.html', true],
    ['http://localhost:5173/index.html#/notes', true],
    ['http://localhost:5174/', false],
    ['https://localhost:5173/', false],
    ['http://127.0.0.1:5173/', false],
    ['http://localhost.evil.com:5173/', false],
    ['https://example.com/', false],
    ['javascript:alert(1)', false],
    ['data:text/html,<script>alert(1)</script>', false],
    ['about:blank', true],
    ['about:srcdoc', false],
    ['not a url', false],
    ['', false],
  ])('dev: %s -> %s', (url, expected) => {
    expect(isAppUrl(url, dev)).toBe(expected);
  });

  it('dev: renderer files are still app URLs', () => {
    expect(isAppUrl(fileUrl('index.html'), dev)).toBe(true);
  });

  it('prod: dev-server origin is not trusted when no dev server is configured', () => {
    expect(isAppUrl('http://localhost:5173/', prod)).toBe(false);
  });

  it('prod: files inside the renderer root are app URLs', () => {
    expect(isAppUrl(fileUrl('index.html'), prod)).toBe(true);
    expect(isAppUrl(fileUrl('overlay.html'), prod)).toBe(true);
    expect(isAppUrl(`${fileUrl('index.html')}#/notes`, prod)).toBe(true);
    expect(isAppUrl(fileUrl('assets', 'x.svg'), prod)).toBe(true);
  });

  it('prod: files outside the renderer root are rejected', () => {
    expect(isAppUrl(pathToFileURL(join(rendererRoot, '..', 'main', 'index.js')).toString(), prod)).toBe(false);
    expect(isAppUrl(pathToFileURL(resolve(rendererRoot, '..', 'renderer-evil', 'x.html')).toString(), prod)).toBe(false);
    expect(isAppUrl(pathToFileURL(resolve('/tmp/evil.html')).toString(), prod)).toBe(false);
  });

  it('prod: ../ traversal (literal and URL-encoded) is rejected', () => {
    expect(isAppUrl(`${rootUrl}/../main/index.js`, prod)).toBe(false);
    expect(isAppUrl(`${rootUrl}/%2e%2e/main/index.js`, prod)).toBe(false);
    expect(isAppUrl(`${rootUrl}/%2E%2E/%2E%2E/secret.html`, prod)).toBe(false);
    expect(isAppUrl(`${rootUrl}/..%2fmain%2findex.js`, prod)).toBe(false);
    expect(isAppUrl(`${rootUrl}/..%5cmain%5cindex.js`, prod)).toBe(false);
  });

  it('prod: the renderer root directory itself is not a page', () => {
    expect(isAppUrl(rootUrl, prod)).toBe(false);
  });
});

describe('externalOpenTarget', () => {
  it.each([
    ['https://example.com/a?b=c', 'https://example.com/a?b=c'],
    ['http://example.com', 'http://example.com'],
    ['HTTPS://EXAMPLE.COM/', 'HTTPS://EXAMPLE.COM/'],
    ['mailto:a@b.c', 'mailto:a@b.c'],
    ['javascript:alert(1)', null],
    ['data:text/html,hi', null],
    ['file:///etc/passwd', null],
    ['vscode://open', null],
    ['about:blank', null],
    ['not a url', null],
    ['', null],
  ])('%s -> %s', (url, expected) => {
    expect(externalOpenTarget(url)).toBe(expected);
  });
});

type OpenHandler = (details: { url: string }) => { action: 'allow' | 'deny' };

function fakeContents() {
  const emitter = new EventEmitter();
  let openHandler: OpenHandler | null = null;
  const contents = Object.assign(emitter, {
    setWindowOpenHandler: (h: OpenHandler) => {
      openHandler = h;
    },
  });
  const navigate = (event: 'will-navigate' | 'will-redirect', url: string) => {
    const e = { preventDefault: vi.fn(), url };
    emitter.emit(event, e, url);
    return e;
  };
  return {
    contents: contents as unknown as WebContents,
    navigate,
    open: (url: string) => {
      if (!openHandler) throw new Error('setWindowOpenHandler was not called');
      return openHandler({ url });
    },
  };
}

describe('installNavigationGuard', () => {
  const opts = { devServerUrl: 'http://localhost:5173', rendererRoot };

  it.each(['will-navigate', 'will-redirect'] as const)(
    '%s: foreign URL is prevented and opened externally once',
    (event) => {
      const openExternal = vi.fn();
      const f = fakeContents();
      installNavigationGuard(f.contents, opts, { openExternal });
      const e = f.navigate(event, 'https://evil.example/phish');
      expect(e.preventDefault).toHaveBeenCalledTimes(1);
      expect(openExternal).toHaveBeenCalledTimes(1);
      expect(openExternal).toHaveBeenCalledWith('https://evil.example/phish');
    },
  );

  it.each(['will-navigate', 'will-redirect'] as const)('%s: app URL is allowed', (event) => {
    const openExternal = vi.fn();
    const f = fakeContents();
    installNavigationGuard(f.contents, opts, { openExternal });
    const e1 = f.navigate(event, 'http://localhost:5173/overlay.html');
    const e2 = f.navigate(event, fileUrl('index.html'));
    expect(e1.preventDefault).not.toHaveBeenCalled();
    expect(e2.preventDefault).not.toHaveBeenCalled();
    expect(openExternal).not.toHaveBeenCalled();
  });

  it.each([
    'javascript:alert(1)',
    'data:text/html,<h1>x</h1>',
    'file:///etc/passwd',
    'vscode://file/x',
  ])('non-web URL %s is prevented and NOT opened', (url) => {
    const openExternal = vi.fn();
    const f = fakeContents();
    installNavigationGuard(f.contents, opts, { openExternal });
    const e = f.navigate('will-navigate', url);
    expect(e.preventDefault).toHaveBeenCalledTimes(1);
    expect(openExternal).not.toHaveBeenCalled();
  });

  it('window.open is always denied; http(s) targets open externally', () => {
    const openExternal = vi.fn();
    const f = fakeContents();
    installNavigationGuard(f.contents, opts, { openExternal });
    expect(f.open('https://example.com/')).toEqual({ action: 'deny' });
    expect(openExternal).toHaveBeenCalledTimes(1);
    expect(openExternal).toHaveBeenCalledWith('https://example.com/');
  });

  it('window.open of app or non-web URLs is denied and not opened', () => {
    const openExternal = vi.fn();
    const f = fakeContents();
    installNavigationGuard(f.contents, opts, { openExternal });
    expect(f.open('http://localhost:5173/')).toEqual({ action: 'deny' });
    expect(f.open(fileUrl('index.html'))).toEqual({ action: 'deny' });
    expect(f.open('javascript:alert(1)')).toEqual({ action: 'deny' });
    expect(f.open('about:blank')).toEqual({ action: 'deny' });
    expect(openExternal).not.toHaveBeenCalled();
  });

  it('a rejected openExternal promise does not throw out of the handler', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    const openExternal = vi.fn().mockRejectedValue(new Error('no handler'));
    const f = fakeContents();
    installNavigationGuard(f.contents, opts, { openExternal });
    expect(() => f.navigate('will-navigate', 'https://example.com')).not.toThrow();
    expect(() => f.open('https://example.com')).not.toThrow();
    await new Promise((r) => setTimeout(r, 0));
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it('defaults to electron shell.openExternal', async () => {
    const { shell } = await import('electron');
    vi.mocked(shell.openExternal).mockResolvedValue(undefined);
    const f = fakeContents();
    installNavigationGuard(f.contents, opts);
    f.navigate('will-navigate', 'https://example.com/');
    expect(shell.openExternal).toHaveBeenCalledWith('https://example.com/');
  });
});
