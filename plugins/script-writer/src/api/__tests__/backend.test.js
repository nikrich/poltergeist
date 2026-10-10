import { describe, expect, it } from 'vitest';
import { call, createProject, listContexts, readScript, writeScript } from '../backend.js';

function fakePlugin(routes) {
  const calls = [];
  return {
    calls,
    sidecar: {
      request: async (method, path, body, opts) => {
        calls.push(opts === undefined ? { method, path, body } : { method, path, body, opts });
        const h = routes[`${method} ${path.split('?')[0]}`];
        return h ? h(path, body) : { ok: false, error: 'no route', status: 500 };
      },
    },
  };
}

describe('backend', () => {
  it('call() goes through plugin.sidecar.request and returns data', async () => {
    const p = fakePlugin({ 'GET /v1/projects': () => ({ ok: true, data: ['x'] }) });
    expect(await call(p, 'GET', '/v1/projects')).toEqual(['x']);
    expect(p.calls).toEqual([{ method: 'GET', path: '/v1/projects', body: undefined }]);
  });

  it('call() throws a clear Error when plugin.sidecar is missing', async () => {
    await expect(call({ api: { fetch: async () => ({ ok: true }) } }, 'GET', '/v1/projects'))
      .rejects.toThrow('plugin.sidecar.request is unavailable');
  });

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
    const p = fakePlugin({ 'GET /v1/vault/contexts': () => ({ ok: true, data: { contexts: ['personal', 'work'], archived: [] } }) });
    expect(await listContexts(p)).toEqual(['personal', 'work']);
  });

  it('createProject falls back to the existing project on 409', async () => {
    const existing = { id: 'personal/long-night', context: 'personal', slug: 'long-night', name: 'Long Night' };
    const p = fakePlugin({
      'POST /v1/projects': () => ({ ok: false, error: 'exists', status: 409 }),
      'GET /v1/projects': () => ({ ok: true, data: [existing] }),
    });
    expect(await createProject(p, 'personal', 'long night')).toEqual(existing);
  });

  describe('If-Match on rewrites', () => {
    const ETAG_READ = '0123456789abcdef';
    const ETAG_PUT1 = '1111111111111111';
    const ETAG_PUT2 = '2222222222222222';

    function notesPlugin() {
      const putEtags = [ETAG_PUT1, ETAG_PUT2];
      return fakePlugin({
        'GET /v1/notes': (path) => (path.includes('missing')
          ? { ok: false, error: 'Note not found', status: 404 }
          : { ok: true, data: { body: 'FADE IN:', frontmatter: { title: 'X' }, etag: ETAG_READ } }),
        'PUT /v1/notes': (_path, body) => ({ ok: true, data: { path: body.path, created: false, etag: putEtags.shift() } }),
      });
    }
    const puts = (p) => p.calls.filter((c) => c.method === 'PUT');

    it('read → write sends the etag the read returned', async () => {
      const p = notesPlugin();
      await readScript(p, 'a.screenplay.md');
      await writeScript(p, 'a.screenplay.md', { title: 'X' }, 'Go.');
      expect(puts(p)[0].opts).toEqual({ ifMatch: ETAG_READ });
    });

    it('write → write sends the etag the first PUT returned', async () => {
      const p = notesPlugin();
      await readScript(p, 'a.screenplay.md');
      await writeScript(p, 'a.screenplay.md', { title: 'X' }, 'Go.');
      await writeScript(p, 'a.screenplay.md', { title: 'X' }, 'Go on.');
      expect(puts(p)[1].opts).toEqual({ ifMatch: ETAG_PUT1 });
    });

    it('a new script (read 404) sends no If-Match, nor an etag from another path', async () => {
      const p = notesPlugin();
      await readScript(p, 'a.screenplay.md');
      expect(await readScript(p, 'missing.screenplay.md')).toBeNull();
      await writeScript(p, 'missing.screenplay.md', { title: 'New' }, 'FADE IN:');
      expect(puts(p)[0].opts).toBeUndefined();
    });

    it('a refused rewrite (409/428) throws with the server message and is not retried', async () => {
      const p = fakePlugin({
        'GET /v1/notes': () => ({ ok: true, data: { body: 'x', frontmatter: {}, etag: ETAG_READ } }),
        'PUT /v1/notes': () => ({ ok: false, error: 'Note changed since it was read', status: 409 }),
      });
      await readScript(p, 'a.md');
      await expect(writeScript(p, 'a.md', { title: 'X' }, 'Go.')).rejects.toMatchObject({ status: 409, message: 'Note changed since it was read' });
      expect(puts(p)).toHaveLength(1);
    });
  });
});
