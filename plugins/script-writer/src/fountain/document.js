// Script file model: frontmatter ⇄ meta, Fountain title page ⇄ meta, slugs, paths.

export const DEFAULT_META = Object.freeze({
  title: 'Untitled', credit: 'Written by', author: '', source: '',
  draft_date: '', contact: '', scene_numbers: false, updated: '',
});
const KEYS = ['title', 'credit', 'author', 'source', 'draft_date', 'contact', 'scene_numbers', 'updated'];
const TITLE_KEYS = [
  ['title', 'Title'], ['credit', 'Credit'], ['author', 'Author'],
  ['source', 'Source'], ['draft_date', 'Draft date'], ['contact', 'Contact'],
];
const LABEL_TO_KEY = { ...Object.fromEntries(TITLE_KEYS.map(([k, l]) => [l.toLowerCase(), k])), authors: 'author' };

export function normalizeMeta(fm = {}) {
  const m = { ...DEFAULT_META };
  for (const k of KEYS) {
    const v = fm?.[k];
    if (v === undefined || v === null) continue;
    m[k] = k === 'scene_numbers' ? Boolean(v) : String(v);
  }
  return m;
}

export function serializeFile(meta, body) {
  const m = normalizeMeta(meta);
  const fm = KEYS.map((k) => `${k}: ${k === 'scene_numbers' ? String(m[k]) : JSON.stringify(m[k])}`);
  return ['---', 'type: screenplay', ...fm, '---', String(body ?? '').replace(/^\n+/, '')].join('\n');
}

export function toFountain(meta, body) {
  const m = normalizeMeta(meta);
  const tp = TITLE_KEYS.filter(([k]) => m[k]).map(([k, label]) => (
    m[k].includes('\n') ? `${label}:\n${m[k].split('\n').map((l) => `    ${l}`).join('\n')}` : `${label}: ${m[k]}`
  ));
  return (tp.length ? `${tp.join('\n')}\n\n` : '') + String(body ?? '').replace(/^\n+/, '');
}

export function fromFountain(text) {
  const src = String(text ?? '').replace(/\r\n?/g, '\n');
  const lines = src.split('\n');
  const first = lines[0]?.match(/^([A-Za-z][A-Za-z ]*):/);
  if (!first || !LABEL_TO_KEY[first[1].toLowerCase()]) return { meta: { ...DEFAULT_META }, body: src };
  const found = {};
  let key = null;
  let i = 0;
  for (; i < lines.length && lines[i].trim() !== ''; i++) {
    const m = lines[i].match(/^([A-Za-z][A-Za-z ]*):\s*(.*)$/);
    if (m && !/^\s/.test(lines[i])) {
      key = LABEL_TO_KEY[m[1].toLowerCase()] ?? null;
      if (key) found[key] = m[2].trim();
    } else if (key) {
      found[key] = found[key] ? `${found[key]}\n${lines[i].trim()}` : lines[i].trim();
    }
  }
  return { meta: normalizeMeta(found), body: lines.slice(i).join('\n').replace(/^\n+/, '') };
}

export function slugify(s) {
  const slug = String(s ?? '').toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '')
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 60).replace(/-+$/, '');
  return slug || 'untitled';
}

export function uniqueSlug(base, taken) {
  let s = base;
  for (let n = 2; taken.has(s); n++) s = `${base}-${n}`;
  return s;
}

export const scriptPath = (context, project, slug) => `20-contexts/${context}/projects/${project}/${slug}.screenplay.md`;

export function parseScriptPath(path) {
  const m = String(path).match(/^20-contexts\/([^/]+)\/projects\/([^/]+)\/([^/]+)\.screenplay\.md$/);
  return m ? { context: m[1], project: m[2], slug: m[3] } : null;
}

export function draftKey(path) {
  return String(path).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(-120) || 'draft';
}

export async function freeScriptPath({ context, project, title, exists }) {
  const base = slugify(title);
  const taken = new Set();
  for (let guard = 0; guard < 100; guard++) {
    const slug = uniqueSlug(base, taken);
    const path = scriptPath(context, project, slug);
    if (!(await exists(path))) return path;
    taken.add(slug);
  }
  throw new Error(`could not find a free file name for "${title}"`);
}
