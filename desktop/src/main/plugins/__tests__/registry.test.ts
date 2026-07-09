import { describe, it, expect } from 'vitest';
import { fetchRegistry, isNewerVersion, marketplaceRepoUrl, REGISTRY_URL } from '../registry';

const SAMPLE_ENTRY = {
  id: 'seance',
  name: 'Séance',
  version: '0.3.1',
  description: 'An agent orchestrator',
  icon: 'sparkles',
  author: 'nikrich',
  tags: ['agents', 'coding'],
  repo: 'nikrich/seance',
  subdir: 'poltergeist-plugin',
  ref: 'main',
  download: '/dl/seance-0.3.1.zip',
};

function fakeFetch(body: unknown, ok = true, status = 200): typeof fetch {
  return (async (url: string) => {
    expect(url).toBe(REGISTRY_URL);
    return {
      ok,
      status,
      json: async () => body,
    } as Response;
  }) as typeof fetch;
}

describe('fetchRegistry', () => {
  it('resolves to the entry array for a valid payload', async () => {
    const payload = {
      apiVersion: 1,
      generatedAt: '2026-07-09T12:52:42.298Z',
      plugins: [SAMPLE_ENTRY],
    };
    const entries = await fetchRegistry(fakeFetch(payload));
    expect(entries).toEqual([SAMPLE_ENTRY]);
  });

  it('throws on a non-ok response', async () => {
    await expect(fetchRegistry(fakeFetch({}, false, 500))).rejects.toThrow();
  });

  it('throws on a malformed payload (missing plugins)', async () => {
    const payload = { apiVersion: 1, generatedAt: '2026-07-09T12:52:42.298Z' };
    await expect(fetchRegistry(fakeFetch(payload))).rejects.toThrow();
  });
});

describe('isNewerVersion', () => {
  it('returns true when the candidate is numerically greater', () => {
    expect(isNewerVersion('0.3.1', '0.1.0')).toBe(true);
  });

  it('returns false when versions are equal', () => {
    expect(isNewerVersion('1.0.0', '1.0.0')).toBe(false);
  });

  it('compares numerically, not lexically', () => {
    expect(isNewerVersion('0.2.0', '0.10.0')).toBe(false);
  });
});

describe('marketplaceRepoUrl', () => {
  it('maps owner/name to a github .git URL', () => {
    expect(marketplaceRepoUrl({ repo: 'nikrich/seance' })).toBe(
      'https://github.com/nikrich/seance.git',
    );
  });

  it('passes a full https url through unchanged', () => {
    expect(marketplaceRepoUrl({ repo: 'https://example.com/foo.git' })).toBe(
      'https://example.com/foo.git',
    );
  });

  it('passes a git@ url through unchanged', () => {
    expect(marketplaceRepoUrl({ repo: 'git@github.com:nikrich/seance.git' })).toBe(
      'git@github.com:nikrich/seance.git',
    );
  });
});
