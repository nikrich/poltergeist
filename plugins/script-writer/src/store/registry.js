// Library registry in plugin settings (no list-by-folder API exists).
import { parseScriptPath } from '../fountain/document.js';

const KEY = 'scripts';

export async function loadRegistry(settings) {
  const v = await settings.get(KEY);
  return Array.isArray(v) ? v : [];
}

export async function upsertEntry(settings, entry) {
  const { missing, ...clean } = entry;
  const list = [clean, ...(await loadRegistry(settings)).filter((e) => e.path !== entry.path)];
  await settings.set(KEY, list);
  return list;
}

export async function removeEntry(settings, path) {
  const list = (await loadRegistry(settings)).filter((e) => e.path !== path);
  await settings.set(KEY, list);
  return list;
}

export async function markMissing(settings, path) {
  const list = (await loadRegistry(settings)).map((e) => (e.path === path ? { ...e, missing: true } : e));
  await settings.set(KEY, list);
  return list;
}

export function entryFor(path, meta, pages) {
  const p = parseScriptPath(path) ?? { context: '', project: '' };
  return { path, title: meta.title, context: p.context, project: p.project, updated: meta.updated, pages };
}
