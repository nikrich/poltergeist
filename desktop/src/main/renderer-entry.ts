import { join } from 'node:path';

/**
 * Which renderer HTML entry the main window loads. The two entries differ only
 * in their CSP <meta> (see shared/renderer-csp.ts): a meta policy can't be
 * loosened at runtime and file:// responses get no headers, so the "load remote
 * images" setting switches documents instead. Both share an origin (file:// in
 * prod, the dev server in dev), so storage and hash routes are unaffected.
 */
export const REMOTE_IMAGES_ENTRY = 'index-remote-images.html';

export function rendererEntry(remoteImages: boolean): string {
  return remoteImages ? REMOTE_IMAGES_ENTRY : 'index.html';
}

export type RendererLoadTarget =
  | { kind: 'url'; url: string }
  | { kind: 'file'; path: string; hash?: string };

export function rendererLoadTarget(opts: {
  remoteImages: boolean;
  rendererDir: string;
  devServerUrl?: string;
  /** location.hash of the page being replaced ('' / '#' = none). */
  hash?: string;
}): RendererLoadTarget {
  const entry = rendererEntry(opts.remoteImages);
  const hash = opts.hash && opts.hash !== '#' ? opts.hash.replace(/^#/, '') : '';
  if (opts.devServerUrl) {
    const base = opts.devServerUrl.endsWith('/') ? opts.devServerUrl : `${opts.devServerUrl}/`;
    // index.html is served at the dev server root; keep that URL as before.
    const page = entry === 'index.html' ? '' : entry;
    return { kind: 'url', url: `${base}${page}${hash ? `#${hash}` : ''}` };
  }
  const path = join(opts.rendererDir, entry);
  return hash ? { kind: 'file', path, hash } : { kind: 'file', path };
}
