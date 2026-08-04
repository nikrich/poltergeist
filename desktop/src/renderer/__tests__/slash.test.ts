import { describe, it, expect } from 'vitest';
import { filterSlashItems, SLASH_ITEMS } from '../lib/editor/slash';

describe('filterSlashItems', () => {
  it('returns all items for empty query', () => {
    expect(filterSlashItems('')).toHaveLength(SLASH_ITEMS.length);
  });
  it('filters by title prefix, case-insensitive', () => {
    const r = filterSlashItems('head');
    expect(r.every((i) => i.title.toLowerCase().includes('head'))).toBe(true);
    expect(r.length).toBeGreaterThan(0);
  });
  it('matches the photo command on "photo"', () => {
    expect(filterSlashItems('photo').map((i) => i.key)).toContain('photo');
  });
});
