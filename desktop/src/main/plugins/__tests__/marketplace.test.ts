import { describe, it, expect, vi } from 'vitest';

import { makeMarketplaceHandlers } from '../marketplace';
import type { RegistryEntry } from '../registry';

const ENTRIES: RegistryEntry[] = [
  { id: 'my-plugin', repo: 'you/my-plugin', subdir: 'pkg', ref: 'v1' },
  { id: 'other', repo: 'you/other' },
];

function makeDeps(overrides: Partial<Parameters<typeof makeMarketplaceHandlers>[0]> = {}) {
  return {
    fetchRegistry: vi.fn(async () => ENTRIES),
    searchEntries: vi.fn((entries: RegistryEntry[], query: string) =>
      entries.filter((e) => e.id.includes(query)),
    ),
    installFromGit: vi.fn(async () => ({}) as never),
    updateFromGit: vi.fn(async () => ({}) as never),
    pluginsRoot: '/tmp/plugins',
    ...overrides,
  };
}

describe('makeMarketplaceHandlers', () => {
  it('list() returns the entries from the injected fetchRegistry', async () => {
    const deps = makeDeps();
    const handlers = makeMarketplaceHandlers(deps);

    await expect(handlers.list()).resolves.toEqual(ENTRIES);
    expect(deps.fetchRegistry).toHaveBeenCalled();
  });

  it('search(query) delegates to searchEntries and returns the filtered list', async () => {
    const deps = makeDeps();
    const handlers = makeMarketplaceHandlers(deps);

    const result = await handlers.search('my');

    expect(deps.searchEntries).toHaveBeenCalledWith(ENTRIES, 'my');
    expect(result).toEqual([ENTRIES[0]]);
  });

  it('install(id) maps the entry to a git install and returns { ok: true }', async () => {
    const deps = makeDeps();
    const handlers = makeMarketplaceHandlers(deps);

    const result = await handlers.install('my-plugin');

    expect(deps.installFromGit).toHaveBeenCalledWith(
      'https://github.com/you/my-plugin.git',
      'pkg',
      '/tmp/plugins',
      'v1',
    );
    expect(result).toEqual({ ok: true });
  });

  it('install(missing) returns an error and does NOT call installFromGit', async () => {
    const deps = makeDeps();
    const handlers = makeMarketplaceHandlers(deps);

    const result = await handlers.install('missing');

    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.error).toMatch(/missing/);
    expect(deps.installFromGit).not.toHaveBeenCalled();
  });

  it('update(id) maps the entry to a git install via updateFromGit', async () => {
    const deps = makeDeps();
    const handlers = makeMarketplaceHandlers(deps);

    const result = await handlers.update('my-plugin');

    expect(deps.updateFromGit).toHaveBeenCalledWith(
      'https://github.com/you/my-plugin.git',
      'pkg',
      '/tmp/plugins',
      'v1',
    );
    expect(result).toEqual({ ok: true });
  });

  it('install() maps an entry with no subdir/ref to undefined args', async () => {
    const deps = makeDeps();
    const handlers = makeMarketplaceHandlers(deps);

    await handlers.install('other');

    expect(deps.installFromGit).toHaveBeenCalledWith(
      'https://github.com/you/other.git',
      undefined,
      '/tmp/plugins',
      undefined,
    );
  });
});
