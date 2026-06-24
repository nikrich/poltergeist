import { protocol, net, ipcMain } from 'electron';
import { mkdir, writeFile } from 'node:fs/promises';
import { dirname, resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';

const ASSET_ROOT_REL = '90-meta/assets/jots';

/** Pure: vault-relative path for a new asset. Forward slashes regardless of OS. */
export function assetVaultRelPath(jotId: string, ext: string, rand: string, now: Date): string {
  const yyyy = String(now.getUTCFullYear());
  const mm = String(now.getUTCMonth() + 1).padStart(2, '0');
  const safeId = jotId.replace(/[^A-Za-z0-9_-]/g, '');
  const safeExt = ext.replace(/[^a-z0-9]/gi, '').toLowerCase() || 'jpg';
  return `${ASSET_ROOT_REL}/${yyyy}/${mm}/${safeId}-${rand}.${safeExt}`;
}

/** Resolve a vault-relative asset path and guard it stays under the asset dir. */
export function resolveAssetPath(vaultRoot: string, vaultRel: string): string | null {
  const assetDir = resolve(vaultRoot, '90-meta', 'assets');
  const candidate = resolve(vaultRoot, vaultRel);
  if (candidate !== assetDir && !candidate.startsWith(assetDir + sep)) return null;
  return candidate;
}

/** Must run before app `whenReady`. */
export function registerGbAssetScheme(): void {
  protocol.registerSchemesAsPrivileged([
    {
      scheme: 'gbasset',
      privileges: { standard: true, secure: true, supportFetchAPI: true, stream: true },
    },
  ]);
}

/** Decode the vault-relative path from a gbasset:// URL. Host is the fixed
 * literal "asset"; the pathname carries the encoded vault-relative path. */
function urlToVaultRel(rawUrl: string): string {
  const u = new URL(rawUrl);
  return decodeURIComponent(u.pathname).replace(/^\/+/, '');
}

export function registerAssetProtocol(getVaultRoot: () => string): void {
  protocol.handle('gbasset', async (request) => {
    const vaultRoot = getVaultRoot();
    if (!vaultRoot) return new Response('vault not configured', { status: 404 });
    const abs = resolveAssetPath(vaultRoot, urlToVaultRel(request.url));
    if (!abs) return new Response('forbidden', { status: 403 });
    try {
      return await net.fetch(pathToFileURL(abs).toString());
    } catch {
      return new Response('not found', { status: 404 });
    }
  });
}

function toBuffer(bytes: unknown): Buffer | null {
  if (bytes instanceof ArrayBuffer) return Buffer.from(bytes);
  if (ArrayBuffer.isView(bytes)) return Buffer.from(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  return null;
}

function randSuffix(): string {
  return Math.random().toString(36).slice(2, 8);
}

export function installAssetBridge(getVaultRoot: () => string): void {
  ipcMain.removeHandler('gb:assets:write');
  ipcMain.handle('gb:assets:write', async (_e, payload: unknown) => {
    const p = payload as { jotId?: unknown; ext?: unknown; bytes?: unknown };
    if (typeof p?.jotId !== 'string' || typeof p?.ext !== 'string') {
      return { ok: false as const, error: 'assets:write expects { jotId, ext, bytes }' };
    }
    const buf = toBuffer(p.bytes);
    if (!buf) return { ok: false as const, error: 'assets:write: bytes must be ArrayBuffer/TypedArray' };
    const vaultRoot = getVaultRoot();
    if (!vaultRoot) return { ok: false as const, error: 'assets:write: vault not configured' };
    const rel = assetVaultRelPath(p.jotId, p.ext, randSuffix(), new Date());
    const abs = resolveAssetPath(vaultRoot, rel);
    if (!abs) return { ok: false as const, error: 'assets:write: path escaped asset dir' };
    try {
      await mkdir(dirname(abs), { recursive: true });
      await writeFile(abs, buf);
      return { ok: true as const, path: rel };
    } catch (err) {
      return { ok: false as const, error: err instanceof Error ? err.message : String(err) };
    }
  });
}
