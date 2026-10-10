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
  /** True for the origin of a worktree dev server main is running. */
  isKnownDevServer?: (origin: string) => boolean;
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

/** Origin of a worktree dev server URL (`http://127.0.0.1:<port>` or
 *  `http://localhost:<port>`), else null. */
export function devServerOrigin(url: string): string | null {
  const u = parse(url);
  if (!u || u.protocol !== 'http:') return null;
  return u.hostname === '127.0.0.1' || u.hostname === 'localhost' ? u.origin : null;
}

/** Subframe rule for live-design frames: prototypes (gbproto:) stay on
 *  gbproto:, worktree dev-server frames stay on their own origin. Null when
 *  the frame is neither (no opinion). */
function frameMayGo(from: string, to: string): boolean | null {
  // No about:blank: once blank, the frame would no longer be recognisable as
  // a prototype and could go anywhere next.
  if (from.startsWith('gbproto:')) return to.startsWith('gbproto:');
  const origin = devServerOrigin(from);
  if (origin) return devServerOrigin(to) === origin;
  return null;
}

/** Prototype / dev-server content: its popups are dropped, never opened. */
function isPrototypeUrl(url: string): boolean {
  return url.startsWith('gbproto:') || devServerOrigin(url) !== null;
}

const FONT_HOSTS = new Set(['fonts.googleapis.com', 'fonts.gstatic.com']);

/** Network-layer rule for requests made by prototype frames (the CSP is the
 *  first line; this also covers what CSP doesn't, like pings and beacons).
 *  `frameUrl` is the requesting frame's current URL. Null = not a prototype
 *  frame (no opinion). */
export function prototypeRequestAllowed(
  frameUrl: string,
  requestUrl: string,
  isKnownDevServer: (origin: string) => boolean,
): boolean | null {
  const fromProto = frameUrl.startsWith('gbproto:');
  // Only servers main started: the app's own dev renderer is localhost too.
  const candidate = devServerOrigin(frameUrl);
  const origin = candidate && isKnownDevServer(candidate) ? candidate : null;
  if (!fromProto && !origin) return null;
  const u = parse(requestUrl);
  if (!u) return false;
  if (u.protocol === 'data:' || u.protocol === 'blob:') return true;
  if (u.protocol === 'https:' && FONT_HOSTS.has(u.hostname)) return true;
  if (fromProto) return u.protocol === 'gbproto:';
  const own = parse(origin as string) as URL;
  if (u.protocol === 'http:') return u.origin === origin;
  if (u.protocol === 'ws:') return u.host === own.host;
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
  contents.on('will-redirect', (event, url) => {
    // A worktree dev server may redirect inside its own origin (e.g. / ->
    // /login). Mid-navigation the frame still shows its previous document,
    // so a blank frame's first load may redirect within any dev-server origin.
    // Other subframe redirects are cancelled without opening anything.
    const e = event as typeof event & { isMainFrame?: boolean; frame?: { url?: string } | null };
    if (e.isMainFrame === false) {
      const from = e.frame?.url ?? '';
      const origin = devServerOrigin(url);
      const may =
        from === '' || from === 'about:blank'
          ? origin !== null && (deps.isKnownDevServer?.(origin) ?? false)
          : frameMayGo(from, url);
      if (may === true) return;
      if (may === false) {
        event.preventDefault();
        return;
      }
    }
    guard(event, url);
  });

  // Live-design prototypes (gbproto://) run generated, untrusted code. Their
  // CSP blocks fetch/images/forms but not navigation, so a frame could carry
  // meeting content out as `location = 'https://…?d=…'`. Keep them home.
  // Worktree dev-server frames (http://127.0.0.1:<port>) run agent-edited
  // code too: same-origin only.
  contents.on('will-frame-navigate', (event) => {
    if (event.isMainFrame) return;
    if (frameMayGo(event.frame?.url ?? '', event.url) === false) event.preventDefault();
  });

  contents.setWindowOpenHandler(({ url, referrer }) => {
    // A prototype could carry meeting content out through a popup URL.
    if (isPrototypeUrl(referrer?.url ?? '')) return { action: 'deny' };
    // Never let a renderer spawn a window: a child window would get the
    // preload bridge. Web links open in the OS browser instead. App-origin
    // URLs are denied too (no feature needs them) and not opened externally.
    if (!isAppUrl(url, opts)) openOutside(url);
    return { action: 'deny' };
  });
}
