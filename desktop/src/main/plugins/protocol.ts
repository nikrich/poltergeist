import { protocol, net } from 'electron';
import { realpathSync } from 'node:fs';
import { isAbsolute, join, resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';

// plugin://<id>/<path> serves files from installed plugin directories so the
// renderer can dynamic-import() plugin UI bundles. Containment is absolute:
// the realpath of the requested file must stay inside the plugin dir.

const MIME: Record<string, string> = {
  '.mjs': 'text/javascript',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.json': 'application/json',
  '.svg': 'image/svg+xml',
  '.png': 'image/png',
  '.woff2': 'font/woff2',
};

/** Must run BEFORE app ready. */
export function registerPluginScheme(): void {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: 'plugin',
      privileges: { standard: true, secure: true, supportFetchAPI: true, corsEnabled: true },
    },
  ]);
}

/**
 * Pure containment check: returns the absolute file path if `urlPath` stays
 * inside `rootDir` after resolution (symlinks included), else null.
 */
export function resolvePluginPath(rootDir: string, urlPath: string): string | null {
  if (!urlPath || isAbsolute(urlPath)) return null;
  const joined = resolve(join(rootDir, urlPath));
  let realRoot: string;
  let realTarget: string;
  try {
    realRoot = realpathSync(rootDir);
    realTarget = realpathSync(joined); // also 404s files that don't exist
  } catch {
    return null;
  }
  if (realTarget !== realRoot && !realTarget.startsWith(realRoot + sep)) return null;
  return joined;
}

/** Must run AFTER app ready. `resolveDir` maps plugin id → installed dir. */
export function installPluginProtocol(resolveDir: (id: string) => string | null): void {
  protocol.handle('plugin', (request) => {
    try {
      const url = new URL(request.url);
      const id = url.hostname;
      const dir = resolveDir(id);
      if (!dir) return new Response('plugin not found', { status: 404 });
      const decoded = decodeURIComponent(url.pathname.replace(/^\//, ''));
      const filePath = resolvePluginPath(dir, decoded);
      if (!filePath) return new Response('not found', { status: 404 });
      const ext = filePath.slice(filePath.lastIndexOf('.'));
      const mime = MIME[ext] ?? 'application/octet-stream';
      return net
        .fetch(pathToFileURL(filePath).toString())
        .then(
          (res) =>
            new Response(res.body, { status: res.status, headers: { 'content-type': mime } }),
        );
    } catch {
      return new Response('bad request', { status: 400 });
    }
  });
}
