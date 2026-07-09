import { describe, it, expect, vi } from 'vitest';

import { fetchRegistry, searchEntries, type RegistryEntry } from '../registry';

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    json: async () => body,
  } as Response;
}

describe('fetchRegistry', () => {
  it('drops invalid entries and keeps valid ones', async () => {
    const validA = { id: 'jira-import', repo: 'you/jira-import', tags: ['jira', 'import'] };
    const validB = { id: 'my-plugin', repo: 'you/my-plugin', subdir: 'pkg', ref: 'v1', author: 'you' };
    const invalid = { id: 'broken' }; // missing required `repo`

    const fetch = vi.fn(async (url: string) => {
      if (url.endsWith('/plugins')) {
        return jsonResponse([
          { name: 'jira-import.json' },
          { name: 'my-plugin.json' },
          { name: 'broken.json' },
        ]);
      }
      if (url.includes('jira-import')) return jsonResponse(validA);
      if (url.includes('my-plugin')) return jsonResponse(validB);
      if (url.includes('broken')) return jsonResponse(invalid);
      throw new Error(`unexpected url: ${url}`);
    });

    const entries = await fetchRegistry({ fetch: fetch as unknown as typeof globalThis.fetch });

    expect(fetch).toHaveBeenCalled();
    expect(entries).toHaveLength(2);
    expect(entries.map((e: RegistryEntry) => e.id).sort()).toEqual(['jira-import', 'my-plugin']);
  });

  it('does not throw when a single entry is malformed', async () => {
    const fetch = vi.fn(async (url: string) => {
      if (url.endsWith('/plugins')) {
        return jsonResponse([{ name: 'broken.json' }]);
      }
      return jsonResponse({ not: 'valid' });
    });

    await expect(
      fetchRegistry({ fetch: fetch as unknown as typeof globalThis.fetch }),
    ).resolves.toEqual([]);
    expect(fetch).toHaveBeenCalled();
  });
});

describe('searchEntries', () => {
  const entries: RegistryEntry[] = [
    { id: 'jira-import', repo: 'you/jira-import', tags: ['jira', 'import'], name: 'Jira Import' },
    {
      id: 'weather-widget',
      repo: 'you/weather-widget',
      tags: ['widget'],
      description: 'Shows current weather',
    },
  ];

  it('matches a query against tags', () => {
    expect(searchEntries(entries, 'jira')).toEqual([entries[0]]);
  });

  it('matches a substring of name or description', () => {
    expect(searchEntries(entries, 'weather')).toEqual([entries[1]]);
    expect(searchEntries(entries, 'import')).toEqual([entries[0]]);
  });

  it('returns everything for an empty or whitespace query', () => {
    expect(searchEntries(entries, '')).toEqual(entries);
    expect(searchEntries(entries, '   ')).toEqual(entries);
  });

  it('returns an empty array for a non-matching query', () => {
    expect(searchEntries(entries, 'nonexistent')).toEqual([]);
  });
});
