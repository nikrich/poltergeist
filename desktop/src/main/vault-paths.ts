import { resolve, sep } from 'node:path';

/** True if `p` resolves to `vaultPath` itself or a path inside it (after normalising `..`). */
export function isInsideVault(vaultPath: string, p: string, opts: { allowRoot?: boolean } = {}): boolean {
  if (!vaultPath || !p) return false;
  const root = resolve(vaultPath);
  const resolved = resolve(p);
  if (resolved === root) return opts.allowRoot ?? true;
  const prefix = root.endsWith(sep) ? root : root + sep;
  return resolved.startsWith(prefix);
}
