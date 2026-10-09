import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useDocs } from '../stores/docs';
import { docUrl, folderKey, formatSize, kindLabel } from '../components/docs/kinds';

describe('docs store', () => {
  beforeEach(() => {
    // Node 25 ships a bare global localStorage that shadows jsdom's; use a stub.
    const mem = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => mem.get(k) ?? null,
      setItem: (k: string, v: string) => void mem.set(k, v),
      removeItem: (k: string) => void mem.delete(k),
      clear: () => mem.clear(),
    });
    useDocs.setState({ selection: null, uploads: [], quickOpen: false, viewModes: {} });
  });

  it('persists the view mode per folder', () => {
    expect(useDocs.getState().viewMode('work/_/specs')).toBe('list');
    useDocs.getState().setViewMode('work/_/specs', 'grid');
    expect(useDocs.getState().viewMode('work/_/specs')).toBe('grid');
    expect(JSON.parse(localStorage.getItem('gb.docs.viewModes')!)).toEqual({ 'work/_/specs': 'grid' });
  });

  it('tracks upload ghosts', () => {
    const s = useDocs.getState();
    s.addUpload({ id: 'u1', name: 'a.pdf', size: 3, key: 'k' });
    s.failUpload('u1', 'too large');
    expect(useDocs.getState().uploads).toEqual([
      { id: 'u1', name: 'a.pdf', size: 3, key: 'k', status: 'error', error: 'too large' },
    ]);
    useDocs.getState().removeUpload('u1');
    expect(useDocs.getState().uploads).toEqual([]);
  });
});

describe('kinds helpers', () => {
  it('builds keys, urls and labels', () => {
    expect(folderKey({ context: 'work', project: null, path: 'a/b' })).toBe('work/_/a/b');
    expect(docUrl('20-contexts/work/docs/a b.pdf')).toBe('gbdoc://doc/20-contexts/work/docs/a%20b.pdf');
    expect(docUrl('20-contexts/work/docs/a b.pdf', 'aaaaaaaaaaaa')).toBe('gbdoc://doc/20-contexts/work/docs/a%20b.pdf?v=aaaaaaaaaaaa');
    expect(kindLabel({ kind: 'text', original: 'x.md' })).toBe('MD');
    expect(kindLabel({ kind: 'text', original: 'x.py' })).toBe('PY');
    expect(kindLabel({ kind: 'image', original: 'x.png' })).toBe('IMG');
    expect(formatSize(2_150_331)).toBe('2.2 MB');
    expect(formatSize(900)).toBe('900 B');
  });
});
