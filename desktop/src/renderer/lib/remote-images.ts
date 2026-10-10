/**
 * Remote (web) images in notes.
 *
 * The renderer CSP blocks remote images unless the user turns on "load remote
 * images" in Settings, which loads a document whose policy adds `https:` to
 * img-src (see shared/renderer-csp.ts). The CSP stays the authoritative
 * control; this module is the second layer: note views never create an <img>
 * for a source that could hit the network unless the policy in force allows
 * it, and show a placeholder instead (no request, no broken-image icon).
 */
export const REMOTE_IMAGE_BLOCKED_TEXT =
  "Remote image blocked — enable 'Load remote images' in Settings";
/** With the setting on, anything that isn't https (http, ftp, file:, //host…) stays blocked. */
export const INSECURE_IMAGE_BLOCKED_TEXT =
  'Image blocked — only https images can load from the web';

/**
 * The URL the browser would actually request: entities decoded (in case the
 * string ever reaches an HTML parser), tab/CR/LF removed anywhere (the URL
 * parser drops them, so `ht<TAB>tps:` is `https:`), and leading/trailing C0
 * controls and spaces trimmed (the URL parser strips those too).
 */
export function normalizeImageSrc(src: string | null | undefined): string {
  let s = typeof src === 'string' ? src : '';
  if (s.includes('&')) {
    // <textarea> content is RCDATA: decodes entities, never creates elements.
    const t = document.createElement('textarea');
    t.innerHTML = s;
    s = t.value;
  }
  // eslint-disable-next-line no-control-regex
  return s.replace(/[\t\n\r]/g, '').replace(/^[\u0000- ]+|[\u0000- ]+$/g, '');
}

const LOCAL_SCHEMES = new Set(['gbasset', 'gbdoc', 'plugin']);

/**
 * Fail-closed allowlist: true only for sources that never touch the network —
 * gbasset:/gbdoc:/plugin:, data:image/…, scheme-less app/vault paths, and ''
 * (nothing to load). Anything else — http(s) in any case, //host, \\unc,
 * ftp:, file:, blob:, javascript:, other data: types, drive letters — is
 * treated as remote.
 */
export function isLocalImageSrc(src: string | null | undefined): boolean {
  const s = normalizeImageSrc(src);
  if (s === '') return true;
  // Protocol-relative / UNC, with either slash (the URL parser treats \ as /).
  if (/^[\\/]{2}/.test(s)) return false;
  const scheme = /^([a-z][a-z0-9+.-]*):/i.exec(s);
  if (!scheme) return true;
  const name = scheme[1]!.toLowerCase();
  if (LOCAL_SCHEMES.has(name)) return true;
  return name === 'data' && /^data:image\//i.test(s);
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

/**
 * Placeholder text when `src` must not be requested, else null (render it).
 * Off: every non-local src is blocked. On: only https is let through, which is
 * exactly what the relaxed CSP (img-src … https:) allows.
 */
export function blockedRemoteImageText(src: string | null | undefined): string | null {
  if (isLocalImageSrc(src)) return null;
  if (!remoteImagesAllowed()) return REMOTE_IMAGE_BLOCKED_TEXT;
  return /^https:/i.test(normalizeImageSrc(src)) ? null : INSECURE_IMAGE_BLOCKED_TEXT;
}

/** DOM placeholder for the editor node view (no request is made for `src`). */
export function createRemoteImagePlaceholder(alt: string | null, text: string): HTMLElement {
  const el = document.createElement('span');
  el.className = 'gb-remote-img-blocked';
  el.setAttribute('role', 'img');
  el.setAttribute('aria-label', alt ? `${alt} — ${text}` : text);
  el.textContent = text;
  return el;
}
