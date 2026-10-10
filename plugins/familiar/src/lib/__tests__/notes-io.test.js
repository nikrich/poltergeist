import { describe, expect, it } from 'vitest';
import { createNoteIO } from '../notes-io.js';

function fakeRequest(store) {
  const calls = [];
  let n = 0;
  const request = async (method, path, body, opts) => {
    calls.push({ method, path, body, opts });
    if (method === 'GET') {
      const p = decodeURIComponent(path.slice('/v1/notes?path='.length));
      if (!store.has(p)) return { ok: false, error: 'Note not found', status: 404 };
      return { ok: true, data: { path: p, body: store.get(p).body, etag: store.get(p).etag } };
    }
    if (store.has(body.path) && opts?.ifMatch !== store.get(body.path).etag) {
      return { ok: false, error: 'Note changed since it was read', status: 409 };
    }
    const etag = String(++n).padStart(16, '0');
    store.set(body.path, { body: body.content, etag });
    return { ok: true, data: { path: body.path, created: false, etag } };
  };
  return { request, calls };
}

describe('createNoteIO', () => {
  it('read → write sends the read etag; write → write chains the PUT etag', async () => {
    const store = new Map([['a.md', { body: 'x', etag: '0123456789abcdef' }]]);
    const { request, calls } = fakeRequest(store);
    const io = createNoteIO(request);
    expect(await io.readNote('a.md')).toBe('x');
    await io.writeNote('a.md', 'y');
    await io.writeNote('a.md', 'z');
    const puts = calls.filter((c) => c.method === 'PUT');
    expect(puts[0].opts).toEqual({ ifMatch: '0123456789abcdef' });
    expect(puts[1].opts).toEqual({ ifMatch: '0000000000000001' });
    expect(store.get('a.md').body).toBe('z');
  });

  it('a create (read 404) sends no If-Match, and never reuses an etag across paths', async () => {
    const store = new Map([['a.md', { body: 'x', etag: '0123456789abcdef' }]]);
    const { request, calls } = fakeRequest(store);
    const io = createNoteIO(request);
    await io.readNote('a.md');
    expect(await io.readNote('b.md')).toBeNull();
    await io.writeNote('b.md', 'new');
    expect(calls.at(-1).opts).toBeUndefined();
  });

  it('a 409 throws with the server message instead of retrying', async () => {
    const store = new Map([['a.md', { body: 'x', etag: '0123456789abcdef' }]]);
    const { request, calls } = fakeRequest(store);
    const io = createNoteIO(request);
    await io.readNote('a.md');
    store.set('a.md', { body: 'user edit', etag: 'fedcba9876543210' });
    await expect(io.writeNote('a.md', 'y')).rejects.toThrow('Note changed since it was read');
    expect(calls.filter((c) => c.method === 'PUT')).toHaveLength(1);
    expect(store.get('a.md').body).toBe('user edit');
  });
});
