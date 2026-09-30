import { describe, expect, it } from 'vitest';
import { retrieve, scopePrefix } from '../retrieve.js';

const SCRIPT = '20-contexts/personal/projects/night/draft.screenplay.md';
const hit = (path, k) => ({ path, title: `T${k}`, snippet: `S${k}`, score: 1 - k / 100 });

function fake(items, notes = {}) {
  const calls = [];
  return {
    calls,
    sidecar: {
      request: async (method, path, body) => {
        calls.push({ method, path, body });
        if (method === 'POST' && path === '/v1/search') return { ok: true, data: { query: body.q, total: items.length, items } };
        if (method === 'GET' && path.startsWith('/v1/notes?path=')) {
          const p = decodeURIComponent(path.slice('/v1/notes?path='.length));
          if (notes[p] instanceof Error) return { ok: false, error: notes[p].message, status: 500 };
          return notes[p] !== undefined ? { ok: true, data: { path: p, body: notes[p] } } : { ok: false, error: 'nf', status: 404 };
        }
        return { ok: false, error: 'no route', status: 500 };
      },
    },
  };
}

describe('scopePrefix', () => {
  it('maps scopes to vault prefixes', () => {
    expect(scopePrefix(SCRIPT, 'project')).toBe('20-contexts/personal/projects/night/');
    expect(scopePrefix(SCRIPT, 'context')).toBe('20-contexts/personal/');
    expect(scopePrefix(SCRIPT, 'vault')).toBe('');
    expect(scopePrefix('odd/path.md', 'project')).toBe('');
  });
});

describe('retrieve', () => {
  it('filters to the project, drops the script itself, numbers from 1 and fetches top-4 bodies truncated', async () => {
    const items = [
      hit(SCRIPT, 0),
      ...Array.from({ length: 6 }, (_, k) => hit(`20-contexts/personal/projects/night/n${k}.md`, k + 1)),
      hit('20-contexts/personal/other.md', 9),
    ];
    const notes = Object.fromEntries(items.map((h) => [h.path, 'x'.repeat(5000)]));
    const p = fake(items, notes);
    const r = await retrieve(p, { query: 'Who is Mara?', scriptPath: SCRIPT, scope: 'project' });
    expect(p.calls[0]).toEqual({ method: 'POST', path: '/v1/search', body: { q: 'Who is Mara?', limit: 50 } });
    expect(r.widened).toBe(false);
    expect(r.sources.map((s) => s.n)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(r.sources.every((s) => s.path.includes('/projects/night/n'))).toBe(true);
    expect(r.sources.slice(0, 4).every((s) => s.content.length === 4000)).toBe(true);
    expect(r.sources[4].content).toBeUndefined();
  });
  it('widens project to context below 3 hits and says so', async () => {
    const items = [hit('20-contexts/personal/projects/night/a.md', 1), hit('20-contexts/personal/b.md', 2), hit('20-contexts/personal/c.md', 3)];
    const r = await retrieve(fake(items), { query: 'q', scriptPath: SCRIPT, scope: 'project' });
    expect(r).toMatchObject({ widened: true, scopeUsed: 'context' });
    expect(r.sources).toHaveLength(3);
  });
  it('keeps at most 8 sources, tolerates a failing note fetch, skips empty queries', async () => {
    const items = Array.from({ length: 12 }, (_, k) => hit(`20-contexts/work/n${k}.md`, k));
    const notes = { '20-contexts/work/n0.md': new Error('boom'), '20-contexts/work/n1.md': 'body' };
    const r = await retrieve(fake(items, notes), { query: 'q', scriptPath: SCRIPT, scope: 'vault' });
    expect(r.sources).toHaveLength(8);
    expect(r.sources[0].content).toBeUndefined();
    expect(r.sources[1].content).toBe('body');
    const p = fake(items);
    expect(await retrieve(p, { query: '   ', scriptPath: SCRIPT })).toEqual({ sources: [], scopeUsed: 'project', widened: false });
    expect(p.calls).toHaveLength(0);
  });
});
