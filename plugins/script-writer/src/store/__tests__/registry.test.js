import { describe, expect, it } from 'vitest';
import { entryFor, loadRegistry, markMissing, removeEntry, upsertEntry } from '../registry.js';

const memSettings = (init) => {
  const m = new Map(Object.entries(init ?? {}));
  return { get: async (k) => m.get(k), set: async (k, v) => { m.set(k, v); } };
};
const P = '20-contexts/personal/projects/night/draft.screenplay.md';

describe('registry', () => {
  it('starts empty and tolerates garbage', async () => {
    expect(await loadRegistry(memSettings())).toEqual([]);
    expect(await loadRegistry(memSettings({ scripts: 'nope' }))).toEqual([]);
  });
  it('upserts most-recent-first without duplicates, and clears missing', async () => {
    const s = memSettings();
    await upsertEntry(s, { path: 'a', title: 'A' });
    await upsertEntry(s, { path: 'b', title: 'B' });
    await markMissing(s, 'a');
    expect((await loadRegistry(s)).find((e) => e.path === 'a').missing).toBe(true);
    const list = await upsertEntry(s, { path: 'a', title: 'A2' });
    expect(list.map((e) => [e.path, e.title, e.missing])).toEqual([['a', 'A2', undefined], ['b', 'B', undefined]]);
  });
  it('removes entries', async () => {
    const s = memSettings({ scripts: [{ path: 'a' }, { path: 'b' }] });
    expect(await removeEntry(s, 'a')).toEqual([{ path: 'b' }]);
  });
  it('builds entries from path + meta', () => {
    expect(entryFor(P, { title: 'Night', updated: 'T' }, 3)).toEqual({
      path: P, title: 'Night', context: 'personal', project: 'night', updated: 'T', pages: 3,
    });
  });
});
