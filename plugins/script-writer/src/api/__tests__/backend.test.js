import { describe, expect, it } from 'vitest';
import { createProject, listContexts, readScript, writeScript } from '../backend.js';

function fakePlugin(routes) {
  const calls = [];
  return {
    calls,
    api: {
      fetch: async (method, path, body) => {
        calls.push({ method, path, body });
        const h = routes[`${method} ${path.split('?')[0]}`];
        return h ? h(path, body) : { ok: false, error: 'no route', status: 500 };
      },
    },
  };
}

describe('backend', () => {
  it('reads a script, normalising meta; returns null on 404', async () => {
    const p = fakePlugin({
      'GET /v1/notes': (path) => (path.includes('missing')
        ? { ok: false, error: 'Note not found', status: 404 }
        : { ok: true, data: { body: 'FADE IN:', frontmatter: { title: 'X', scene_numbers: true } } }),
    });
    expect(await readScript(p, 'a/b.screenplay.md')).toMatchObject({ meta: { title: 'X', scene_numbers: true }, body: 'FADE IN:' });
    expect(await readScript(p, 'missing.md')).toBeNull();
    expect(p.calls[0].path).toBe('/v1/notes?path=a%2Fb.screenplay.md');
  });

  it('writes the full file via PUT and surfaces errors', async () => {
    const p = fakePlugin({ 'PUT /v1/notes': () => ({ ok: false, error: 'disk full', status: 500 }) });
    await expect(writeScript(p, 'a.md', { title: 'X' }, 'Go.')).rejects.toThrow('disk full');
    expect(p.calls[0].body.content).toMatch(/^---\ntype: screenplay\n/);
  });

  it('lists contexts', async () => {
    const p = fakePlugin({ 'GET /v1/vault/contexts': () => ({ ok: true, data: { contexts: ['personal', 'codeship'], archived: [] } }) });
    expect(await listContexts(p)).toEqual(['personal', 'codeship']);
  });

  it('createProject falls back to the existing project on 409', async () => {
    const existing = { id: 'personal/long-night', context: 'personal', slug: 'long-night', name: 'Long Night' };
    const p = fakePlugin({
      'POST /v1/projects': () => ({ ok: false, error: 'exists', status: 409 }),
      'GET /v1/projects': () => ({ ok: true, data: [existing] }),
    });
    expect(await createProject(p, 'personal', 'long night')).toEqual(existing);
  });
});
