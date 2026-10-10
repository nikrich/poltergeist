import type { ResolvedLink } from '../../shared/api-types';
import { toast } from '../stores/toast';
import { get } from './api/client';
import { notePathFromTarget } from './editor/link-suggest';

export const RESOLVE_TIMEOUT_MS = 2000;

export type WikilinkTarget = { kind: 'open'; path: string } | { kind: 'missing'; name: string };

/** Bare `[[Name]]` → the unique note the link index resolves it to. Never
 * rejects: a cold index, an error or a timeout falls back to `<Name>.md`
 * (the pre-A6 behaviour), so a click never does nothing. */
export async function resolveBareWikilink(
  name: string,
  timeoutMs: number = RESOLVE_TIMEOUT_MS,
): Promise<WikilinkTarget> {
  const fallback: WikilinkTarget = { kind: 'open', path: notePathFromTarget(name) };
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timeout = new Promise<null>((resolve) => {
    timer = setTimeout(() => resolve(null), timeoutMs);
  });
  try {
    const result = await Promise.race([
      get<ResolvedLink>(`/v1/vault/resolve?target=${encodeURIComponent(name)}`),
      timeout,
    ]);
    if (!result || result.indexing) return fallback;
    return result.exists ? { kind: 'open', path: result.path } : { kind: 'missing', name };
  } catch {
    return fallback;
  } finally {
    clearTimeout(timer);
  }
}

/** Wikilink click handler for both editors. Path-form targets open at once,
 * as before. Bare names resolve through the index first, so `[[Beta]]` opens
 * `20-contexts/…/Beta.md` instead of a 404, and an unwritten page says so. */
export function openWikilink(target: string, open: (path: string) => void): void {
  const bare = target.split('#')[0]!.trim();
  if (!bare) return;
  if (bare.includes('/')) {
    open(notePathFromTarget(bare));
    return;
  }
  void resolveBareWikilink(bare).then((result) => {
    if (result.kind === 'open') open(result.path);
    else toast.info(`“${result.name}” isn't written yet`);
  });
}
