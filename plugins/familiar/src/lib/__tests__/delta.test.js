import { describe, expect, it } from 'vitest';
import { extractPaths, listDays } from '../delta.js';

describe('listDays', () => {
  it('spans the window inclusively in local time', () => {
    const days = listDays(new Date(2026, 6, 6, 15, 0).toISOString(), new Date(2026, 6, 8, 9, 0).toISOString());
    expect(days).toEqual(['2026-07-06', '2026-07-07', '2026-07-08']);
  });
  it('same-day window yields one day', () => {
    const d = new Date(2026, 6, 8, 1, 0).toISOString();
    expect(listDays(d, d)).toEqual(['2026-07-08']);
  });
});

describe('extractPaths', () => {
  it('dedupes, drops nulls, excludes Familiar/', () => {
    const rows = [
      { path: '10-daily/2026-07-07.md' },
      { path: '10-daily/2026-07-07.md' },
      { path: null },
      {},
      { path: 'Familiar/briefings/2026-07-01.md' },
      { path: '20-contexts/codeship/x.md' },
    ];
    expect(extractPaths(rows)).toEqual(['10-daily/2026-07-07.md', '20-contexts/codeship/x.md']);
  });
});
