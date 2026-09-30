import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { FONT_FILES, FONT_PLACEHOLDER } from '../render/pageHtml.js';

export const IMPORT_EXTS = ['fountain', 'spmd', 'txt', 'fdx'];
export const EXPORT_EXTS = ['fountain', 'txt', 'fdx'];
export const MAX_IMPORT_BYTES = 5 * 1024 * 1024;

export function exportName(name, ext) {
  const base = String(name ?? '').replace(/[\\/:*?"<>|]+/g, '-').trim() || 'screenplay';
  return base.toLowerCase().endsWith(`.${ext}`) ? base : `${base}.${ext}`;
}

/** Replace __FONT_BASE__<file> with data: URLs so the hidden print window needs no file:// font access. */
export function inlineFonts(html, fontDir) {
  const re = new RegExp(`${FONT_PLACEHOLDER}([^"')\\s]+)`, 'g');
  return html.replace(re, (_, name) => {
    if (!FONT_FILES.includes(name)) throw new Error(`unknown font: ${name}`);
    return `data:font/woff2;base64,${readFileSync(join(fontDir, name)).toString('base64')}`;
  });
}

/** Settle with `work`, or reject with Error(message) if it takes longer than `ms`. */
export function withTimeout(work, ms, message) {
  let timer;
  const timeout = new Promise((_, reject) => { timer = setTimeout(() => reject(new Error(message)), ms); });
  return Promise.race([work, timeout]).finally(() => clearTimeout(timer));
}
