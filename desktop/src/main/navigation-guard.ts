import { shell, type WebContents } from 'electron';
import { isAbsolute, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

/**
 * Navigation guard for every webContents the app creates.
 *
 * The preload bridge (`window.gb`) can read and write the user's whole vault
 * via the sidecar. If any rendered content (markdown links, mermaid SVG
 * anchors, imported HTML, plugin UI) could navigate a window to a foreign URL,
 * that page would inherit the bridge. So:
 *
 * - `will-navigate` / `will-redirect` are allowed only for the app's own
 *   renderer (electron-vite dev server origin in dev, files inside the packaged
 *   renderer directory in prod). Everything else is cancelled; http(s)/mailto
 *   targets are handed to the OS browser instead.
 * - `window.open` / `target=_blank` is ALWAYS denied. No feature opens child
 *   windows from a renderer (all app windows are created in main), so there is
 *   no exception here; http(s)/mailto targets go to the OS browser.
 *
 * Programmatic loads from main (`loadURL` / `loadFile` — main window, jot
 * overlay, pdf-export's temp HTML files) do not emit `will-navigate`, so they
 * are unaffected. Plugin UI is loaded via dynamic `import('plugin://…')`
 * inside the renderer, which is a module fetch, not a navigation.
 */

export interface NavigationGuardOptions {
  /** electron-vite dev server URL (process.env.ELECTRON_RENDERER_URL), dev only. */
  devServerUrl?: string;
  /** Directory holding the packaged renderer HTML (out/renderer). */
  rendererRoot: string;
}

export interface NavigationGuardDeps {
  openExternal: (url: string) => Promise<unknown> | unknown;
}

function parse(url: string): URL | null {
  try {
    return new URL(url);
  } catch {
    return null;
  }
}

function isInsideRendererRoot(u: URL, rendererRoot: string): boolean {
  // Encoded separators could smuggle traversal past URL normalisation
  // (`..%2f`, and `..%5c` which Windows treats as a separator).
  if (/%2f|%5c/i.test(u.pathname)) return false;
  let filePath: string;
  try {
    filePath = fileURLToPath(u);
  } catch {
    return false;
  }
  const rel = relative(resolve(rendererRoot), resolve(filePath));
  // rel === '' is the directory itself, not a page.
  return rel !== '' && !rel.startsWith('..') && !isAbsolute(rel);
}

/** True only for URLs belonging to the app's own renderer. */
export function isAppUrl(url: string, opts: NavigationGuardOptions): boolean {
  if (typeof url !== 'string' || url === '') return false;
  // about:blank is inert (empty document); the only about: URL allowed.
  if (url === 'about:blank') return true;
  const u = parse(url);
  if (!u) return false;

  if (u.protocol === 'http:' || u.protocol === 'https:') {
    if (!opts.devServerUrl) return false;
    const dev = parse(opts.devServerUrl);
    return dev !== null && dev.origin === u.origin;
  }
  if (u.protocol === 'file:') {
    return isInsideRendererRoot(u, opts.rendererRoot);
  }
  return false;
}

/** The URL if it is safe to hand to the OS (http/https/mailto), else null. */
export function externalOpenTarget(url: string): string | null {
  if (typeof url !== 'string' || url === '') return null;
  const u = parse(url);
  if (!u) return null;
  return u.protocol === 'http:' || u.protocol === 'https:' || u.protocol === 'mailto:'
    ? url
    : null;
}

export function installNavigationGuard(
  contents: WebContents,
  opts: NavigationGuardOptions,
  deps: NavigationGuardDeps = { openExternal: (url) => shell.openExternal(url) },
): void {
  const openOutside = (url: string): void => {
    const target = externalOpenTarget(url);
    if (!target) return;
    try {
      void Promise.resolve(deps.openExternal(target)).catch((err: unknown) => {
        console.warn('[navigation-guard] openExternal failed:', err);
      });
    } catch (err) {
      console.warn('[navigation-guard] openExternal failed:', err);
    }
  };

  const guard = (event: { preventDefault: () => void }, url: string): void => {
    if (isAppUrl(url, opts)) return;
    event.preventDefault();
    openOutside(url);
  };

  contents.on('will-navigate', (event, url) => guard(event, url));
  contents.on('will-redirect', (event, url) => guard(event, url));

  contents.setWindowOpenHandler(({ url }) => {
    // Never let a renderer spawn a window: a child window would get the
    // preload bridge. Web links open in the OS browser instead. App-origin
    // URLs are denied too (no feature needs them) and not opened externally.
    if (!isAppUrl(url, opts)) openOutside(url);
    return { action: 'deny' };
  });
}
