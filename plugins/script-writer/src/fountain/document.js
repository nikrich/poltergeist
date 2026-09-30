// Script file model: frontmatter ⇄ meta, Fountain title page ⇄ meta, slugs, paths.

export const DEFAULT_META = Object.freeze({
  title: 'Untitled', credit: 'Written by', author: '', source: '',
  draft_date: '', contact: '', scene_numbers: false, updated: '', extra: Object.freeze({}),
});
const KEYS = ['title', 'credit', 'author', 'source', 'draft_date', 'contact', 'scene_numbers', 'updated'];
const TITLE_KEYS = [
  ['title', 'Title'], ['credit', 'Credit'], ['author', 'Author'],
  ['source', 'Source'], ['draft_date', 'Draft date'], ['contact', 'Contact'],
];
const LABEL_TO_KEY = { ...Object.fromEntries(TITLE_KEYS.map(([k, l]) => [l.toLowerCase(), k])), authors: 'author' };

const RESERVED = new Set(['type', ...KEYS]);
const isPlainObject = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);

// Frontmatter keys the plugin does not own (e.g. `related:`, `tags:`) live in
// meta.extra so a save writes them back. A plain-object `extra` is an already
// normalised meta's passthrough; any other key not owned here is collected.
export function normalizeMeta(fm = {}) {
  const m = { ...DEFAULT_META };
  for (const k of KEYS) {
    const v = fm?.[k];
    if (v === undefined || v === null) continue;
    m[k] = k === 'scene_numbers' ? Boolean(v) : String(v);
  }
  const extra = {};
  const add = (k, v) => { if (!RESERVED.has(k) && v !== undefined) extra[k] = v; };
  for (const [k, v] of Object.entries(fm ?? {})) {
    if (k === 'extra' && isPlainObject(v)) Object.entries(v).forEach(([ek, ev]) => add(ek, ev));
    else add(k, v);
  }
  m.extra = extra;
  return m;
}

const yamlKey = (k) => (/^[A-Za-z_][A-Za-z0-9_-]*$/.test(k) ? k : JSON.stringify(k));

export function serializeFile(meta, body) {
  const m = normalizeMeta(meta);
  const fm = KEYS.map((k) => `${k}: ${k === 'scene_numbers' ? String(m[k]) : JSON.stringify(m[k])}`);
  // JSON is valid YAML: scalars stay quoted/typed, arrays and objects become flow style.
  const rest = Object.entries(m.extra).map(([k, v]) => `${yamlKey(k)}: ${JSON.stringify(v) ?? 'null'}`);
  return ['---', 'type: screenplay', ...fm, ...rest, '---', String(body ?? '').replace(/^\n+/, '')].join('\n');
}

export function toFountain(meta, body) {
  const m = normalizeMeta(meta);
  const tp = TITLE_KEYS.filter(([k]) => m[k]).map(([k, label]) => (
    m[k].includes('\n') ? `${label}:\n${m[k].split('\n').map((l) => `    ${l}`).join('\n')}` : `${label}: ${m[k]}`
  ));
  return (tp.length ? `${tp.join('\n')}\n\n` : '') + String(body ?? '').replace(/^\n+/, '');
}

export function fromFountain(text) {
  const src = String(text ?? '').replace(/^\uFEFF/, '').replace(/\r\n?/g, '\n');
  const lines = src.replace(/^(?:[ \t]*\n)+/, '').split('\n');
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
