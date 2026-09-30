// Vault retrieval for the co-writer: semantic search, scoped by path prefix.
import { call } from '../api/backend.js';
import { parseScriptPath } from '../fountain/document.js';

export const SCOPES = ['project', 'context', 'vault'];
const MAX_SOURCES = 8;
const FULL_SOURCES = 4;
const FULL_CHARS = 4000;
const WIDEN_BELOW = 3;

export function scopePrefix(scriptPath, scope) {
  const p = parseScriptPath(scriptPath);
  if (!p || scope === 'vault') return '';
  if (scope === 'context') return `20-contexts/${p.context}/`;
  return `20-contexts/${p.context}/projects/${p.project}/`;
}

export async function retrieve(plugin, { query, scriptPath, scope = 'project' }) {
  const q = String(query ?? '').trim().slice(0, 500);
  if (!q) return { sources: [], scopeUsed: scope, widened: false };
  const res = await call(plugin, 'POST', '/v1/search', { q, limit: 50 });
  const items = (res?.items ?? []).filter((h) => h && h.path !== scriptPath);
  const pick = (s) => items.filter((h) => h.path.startsWith(scopePrefix(scriptPath, s))).slice(0, MAX_SOURCES);
  let scopeUsed = scope;
  let hits = pick(scope);
  let widened = false;
  if (scope === 'project' && hits.length < WIDEN_BELOW) {
    hits = pick('context');
    scopeUsed = 'context';
    widened = true;
  }
  const sources = await Promise.all(hits.map(async (h, k) => {
    const src = { n: k + 1, path: h.path, title: h.title, snippet: h.snippet, score: h.score };
    if (k < FULL_SOURCES) {
      try {
        const note = await call(plugin, 'GET', `/v1/notes?path=${encodeURIComponent(h.path)}`);
        src.content = String(note?.body ?? '').slice(0, FULL_CHARS);
      } catch {
        // snippet only: one unreadable note must not fail the question
      }
    }
    return src;
  }));
  return { sources, scopeUsed, widened };
}
