// desktop/src/renderer/__tests__/docs-tree-model.test.ts
import { describe, expect, it } from 'vitest';
import { countDocs, decodeDrag, encodeDrag, findDoc, findFolder, groupByContext, isInside } from '../components/docs/tree-model';
import { libraryFixture } from './fixtures/library';

describe('tree-model', () => {
  it('round-trips drag payloads and rejects junk', () => {
    const p = { type: 'doc' as const, docId: 'aaaaaaaaaaaa' };
    expect(decodeDrag(encodeDrag(p))).toEqual(p);
    expect(decodeDrag('nope')).toBeNull();
    expect(decodeDrag('{"type":"x"}')).toBeNull();
  });

  it('finds folders and docs, counts recursively', () => {
    const t = libraryFixture();
    const specs = findFolder(t, { context: 'work', project: 'payments', path: 'specs' });
    expect(specs?.docs.map((d) => d.title)).toEqual(['Payments API v2']);
    const root = findFolder(t, { context: 'work', project: 'payments', path: '' });
    expect(root?.folders.map((f) => f.name)).toEqual(['diagrams', 'specs']);
    expect(countDocs(root!)).toBe(3);
    expect(findDoc(t, 'bbbbbbbbbbbb')?.title).toBe('Settlement flow');
  });

  it('groups unfiled first and detects nesting', () => {
    const groups = groupByContext(libraryFixture().scopes);
    expect(groups[0]!.context).toBe('work');
    expect(groups[0]!.scopes.map((s) => s.name)).toEqual(['unfiled', 'Payments']);
    const a = { context: 'w', project: null, path: 'a' };
    expect(isInside({ ...a, path: 'a/b' }, a)).toBe(true);
    expect(isInside({ ...a, path: 'ab' }, a)).toBe(false);
  });
});
