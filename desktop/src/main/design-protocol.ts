import { protocol, net } from 'electron';
import { createHash } from 'node:crypto';
import { realpath } from 'node:fs/promises';
import { extname, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { isInsideVault } from './vault-paths';

// gbproto://proto/<path> serves the prototype folder of the live design
// session (dist/ bundle + design-pack/ tokens) into the panel / pop-out
// iframe, each bundled folder under its own prefix. Its own origin keeps the
// prototype away from window.gb.

const HOST = 'proto';

const MIME: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript; charset=utf-8',
  '.mjs': 'text/javascript; charset=utf-8',
  '.css': 'text/css; charset=utf-8',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.jpg': 'image/jpeg',
  '.jpeg': 'image/jpeg',
  '.gif': 'image/gif',
  '.webp': 'image/webp',
  '.woff': 'font/woff',
  '.woff2': 'font/woff2',
};

// Each bundled folder gets its own path prefix (gbproto://proto/<id>/…), so
// the live panel, its pop-out and an Artefacts preview of another folder can
// be open at once. Only folders main has bundled are ever served.
const MAX_ROOTS = 16;
const roots = new Map<string, string>(); // id -> folder, oldest first

/** Allow serving `dir`; returns its URL prefix id. */
export function serveRoot(dir: string): string {
  const id = createHash('sha256').update(dir).digest('hex').slice(0, 16);
  roots.delete(id);
  roots.set(id, dir);
  while (roots.size > MAX_ROOTS) roots.delete(roots.keys().next().value as string);
  return id;
}

/** `gbproto://proto/dist/…` from the bundler -> the folder's own prefix. */
export function rootUrl(id: string, url: string): string {
  return url.replace(/^gbproto:\/\/proto\//, `gbproto://${HOST}/${id}/`);
}

/** Split `gbproto://proto/<id>/<rest>` into the folder and a root-relative
 *  URL; null when the id is unknown. */
export function splitServedUrl(url: string): { root: string; url: string } | null {
  let u: URL;
  try {
    u = new URL(url);
  } catch {
    return null;
  }
  if (u.hostname !== HOST) return null;
  const m = /^\/([0-9a-f]{16})(\/.*)$/.exec(u.pathname);
  const root = m ? roots.get(m[1] as string) : undefined;
  if (!m || !root) return null;
  return { root, url: `gbproto://${HOST}${m[2]}${u.search}` };
}

export function contentTypeFor(file: string): string {
  return MIME[extname(file).toLowerCase()] ?? 'application/octet-stream';
}

/** Root-relative path -> absolute path inside `root`, or null if it could escape. */
export function resolveProtoPath(root: string, rel: string): string | null {
  if (!rel || rel.startsWith('/') || rel.includes('\\')) return null;
  if (rel.split('/').some((s) => s === '..' || s === '.' || s === '')) return null;
  const abs = resolve(root, rel);
  return isInsideVault(root, abs, { allowRoot: false }) ? abs : null;
}

/** URL -> absolute path; null = forbidden, 'bad-request' = malformed escape. */
export function protoPathFromUrl(root: string, url: string): string | null | 'bad-request' {
  let u: URL;
  try {
    u = new URL(url);
  } catch {
    return 'bad-request';
  }
  if (u.hostname !== HOST) return null;
  let rel: string;
  try {
    rel = decodeURIComponent(u.pathname).replace(/^\/+/, '');
  } catch {
    return 'bad-request';
  }
  return resolveProtoPath(root, rel);
}

/** The real file to serve for `url`, or null (forbidden / missing / no root).
 *  Symlink guard: the real file must still live inside the real root. */
export async function resolveServedFile(root: string | null, url: string): Promise<string | null> {
  if (!root) return null;
  const abs = protoPathFromUrl(root, url);
  if (!abs || abs === 'bad-request') return null;
  try {
    const real = await realpath(abs);
    return isInsideVault(await realpath(root), real, { allowRoot: false }) ? real : null;
  } catch {
    return null;
  }
}

/** Must run BEFORE app ready. */
export function registerDesignScheme(): void {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: 'gbproto',
      privileges: {
        standard: true,
        secure: true,
        supportFetchAPI: true,
        corsEnabled: false,
        stream: true,
      },
    },
  ]);
}

// Generated prototype code is untrusted (meeting speech steers the agent):
// it may run, style itself and load Google Fonts, but never reach the network
// — no fetch/XHR/websocket, no remote images, no form posts.
export const PROTOTYPE_CSP = [
  "default-src 'self' gbproto:",
  "script-src 'self' gbproto: 'unsafe-inline'",
  "style-src 'self' gbproto: 'unsafe-inline' https://fonts.googleapis.com",
  "font-src 'self' gbproto: data: https://fonts.gstatic.com",
  "img-src 'self' gbproto: data: blob:",
  "connect-src 'none'",
  "form-action 'none'",
  "frame-src 'none'",
  "object-src 'none'",
  "base-uri 'none'",
].join('; ');

export function prototypeHeaders(file: string): Record<string, string> {
  return {
    'content-type': contentTypeFor(file),
    'cache-control': 'no-store',
    'content-security-policy': PROTOTYPE_CSP,
    'x-dns-prefetch-control': 'off',
  };
}

/** Must run AFTER app ready. */
export function registerDesignProtocol(): void {
  protocol.handle('gbproto', async (request) => {
    const hit = splitServedUrl(request.url);
    const file = hit ? await resolveServedFile(hit.root, hit.url) : null;
    if (!file) return new Response('not found', { status: 404 });
    try {
      const res = await net.fetch(pathToFileURL(file).toString());
      return new Response(res.body, {
        status: res.status,
        headers: prototypeHeaders(file),
      });
    } catch {
      return new Response('not found', { status: 404 });
    }
  });
}
