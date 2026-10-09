import { protocol, net } from 'electron';
import { resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';

// Docs roots only: 20-contexts/{ctx}/docs/… and 20-contexts/{ctx}/projects/{slug}/docs/…
const DOC_REL_RE = /^20-contexts\/[^/]+\/(?:projects\/[^/]+\/)?docs\/.+/;

/** Resolve a vault-relative path served by gbdoc://, or null if it is not inside a docs root. */
export function resolveDocPath(vaultRoot: string, vaultRel: string): string | null {
  const rel = vaultRel.replace(/\\/g, '/');
  if (rel.startsWith('/') || !DOC_REL_RE.test(rel)) return null;
  if (rel.split('/').some((s) => s === '..' || s === '.' || s === '')) return null;
  const root = resolve(vaultRoot);
  const abs = resolve(root, rel);
  if (!abs.startsWith(root + sep)) return null;
  return abs;
}

/** gbdoc://doc/<vault-relative path>. CORS-enabled so pdf.js can fetch it from the renderer origin. */
export function registerDocProtocol(getVaultRoot: () => string): void {
  protocol.handle('gbdoc', async (request) => {
    const vaultRoot = getVaultRoot();
    if (!vaultRoot) return new Response('vault not configured', { status: 404 });
    const rel = decodeURIComponent(new URL(request.url).pathname).replace(/^\/+/, '');
    const abs = resolveDocPath(vaultRoot, rel);
    if (!abs) return new Response('forbidden', { status: 403 });
    try {
      const res = await net.fetch(pathToFileURL(abs).toString());
      const headers = new Headers(res.headers);
      headers.set('Access-Control-Allow-Origin', '*');
      return new Response(res.body, { status: res.status, headers });
    } catch {
      return new Response('not found', { status: 404 });
    }
  });
}
