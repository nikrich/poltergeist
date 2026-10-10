/**
 * Remote (web) images in notes.
 *
 * The renderer CSP blocks remote images unless the user turns on "load remote
 * images" in Settings, which loads a document whose policy adds `https:` to
 * img-src (see shared/renderer-csp.ts). Rather than render an <img> that the
 * policy would block (a broken-image icon, and a CSP violation per image), the
 * note views ask the policy actually in force and show a placeholder instead.
 */
export const REMOTE_IMAGE_BLOCKED_TEXT =
  "Remote image blocked — enable 'Load remote images' in Settings";

/** http(s) or protocol-relative URL — anything that would hit the network. */
export function isRemoteImageSrc(src: string | null | undefined): boolean {
  return typeof src === 'string' && /^(https?:)?\/\//i.test(src.trim());
}

function directive(policy: string, name: string): string[] | null {
  for (const part of policy.split(';')) {
    const [n, ...vals] = part.trim().split(/\s+/);
    if (n?.toLowerCase() === name) return vals;
  }
  return null;
}

/**
 * True only when every CSP <meta> in the document lets img-src load https
 * images. No policy at all → false (fail closed; the app always ships one).
 */
export function remoteImagesAllowed(doc: Document = document): boolean {
  const metas = [...doc.querySelectorAll('meta[http-equiv="Content-Security-Policy" i]')];
  if (metas.length === 0) return false;
  return metas.every((m) => {
    const policy = m.getAttribute('content') ?? '';
    const sources = directive(policy, 'img-src') ?? directive(policy, 'default-src') ?? [];
    return sources.includes('https:');
  });
}

/** True when `src` is remote and the current policy would block it. */
export function isBlockedRemoteImage(src: string | null | undefined): boolean {
  return isRemoteImageSrc(src) && !remoteImagesAllowed();
}

/** DOM placeholder for the editor node view (no request is made for `src`). */
export function createRemoteImagePlaceholder(alt: string | null): HTMLElement {
  const el = document.createElement('span');
  el.className = 'gb-remote-img-blocked';
  el.setAttribute('role', 'img');
  el.setAttribute('aria-label', alt ? `${alt} — ${REMOTE_IMAGE_BLOCKED_TEXT}` : REMOTE_IMAGE_BLOCKED_TEXT);
  el.textContent = REMOTE_IMAGE_BLOCKED_TEXT;
  return el;
}
