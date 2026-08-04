import { describe, it, expect, vi } from 'vitest';

// The handler factory is pure over its deps; we test it directly (no ipcMain,
// no network — mirrors ipc-sidecar.test.ts).
import { makeMarketplaceHandlers } from '../marketplace';
import type { MarketplaceEntry, PluginRecord } from '../../../shared/plugin-types';

const SEANCE: MarketplaceEntry = {
  id: 'seance',
  name: 'Séance',
  version: '0.3.1',
  repo: 'nikrich/seance',
  subdir: 'poltergeist-plugin',
};

const HELLO: MarketplaceEntry = {
  id: 'hello',
  name: 'Hello',
  version: '1.0.0',
  repo: 'nikrich/hello',
};

function record(id: string, version: string): PluginRecord {
  return {
    id,
    dir: `/plugins/${id}`,
    manifest: {
      id,
      name: id,
      version,
      apiVersion: 1,
      entry: { main: 'main.cjs' },
    },
    state: 'enabled',
  };
}

function makeDeps(overrides: Partial<Parameters<typeof makeMarketplaceHandlers>[0]> = {}) {
  return {
    fetchRegistry: vi.fn(async () => [SEANCE, HELLO]),
    records: vi.fn(() => [] as PluginRecord[]),
    installFromGit: vi.fn(async () => undefined),
    updateFromGit: vi.fn(async () => undefined),
    reload: vi.fn(async () => undefined),
    pluginsRoot: '/plugins',
    ...overrides,
  };
}

describe('makeMarketplaceHandlers.list', () => {
  it('marks an entry not installed', async () => {
    const handlers = makeMarketplaceHandlers(makeDeps());
    const listing = await handlers.list();
    expect(listing).toEqual([
      { ...SEANCE, installed: false, installedVersion: null, updateAvailable: false },
      { ...HELLO, installed: false, installedVersion: null, updateAvailable: false },
    ]);
  });

  it('flags an update when the installed version is older', async () => {
    const handlers = makeMarketplaceHandlers(
      makeDeps({ records: vi.fn(() => [record('seance', '0.1.0')]) }),
    );
    const listing = await handlers.list();
    expect(listing).toContainEqual({
      ...SEANCE,
      installed: true,
      installedVersion: '0.1.0',
      updateAvailable: true,
    });
  });

  it('reports no update available when installed at the same version', async () => {
    const handlers = makeMarketplaceHandlers(
      makeDeps({ records: vi.fn(() => [record('seance', '0.3.1')]) }),
    );
    const listing = await handlers.list();
    expect(listing).toContainEqual({
      ...SEANCE,
      installed: true,
      installedVersion: '0.3.1',
      updateAvailable: false,
    });
  });

  it('surfaces a failure result when fetchRegistry throws', async () => {
    const handlers = makeMarketplaceHandlers(
      makeDeps({
        fetchRegistry: vi.fn(async () => {
          throw new Error('network down');
        }),
      }),
    );
    expect(await handlers.list()).toEqual({ ok: false, error: 'network down' });
  });
});

describe('makeMarketplaceHandlers.install', () => {
  it('installs from the derived github url and reloads', async () => {
    const deps = makeDeps();
    const handlers = makeMarketplaceHandlers(deps);
    const result = await handlers.install('seance');
    expect(deps.installFromGit).toHaveBeenCalledWith(
      'https://github.com/nikrich/seance.git',
      'poltergeist-plugin',
      '/plugins',
    );
    expect(deps.reload).toHaveBeenCalled();
    expect(result).toEqual({ ok: true });
  });

  it('returns a failure result for an id not in the registry', async () => {
    const handlers = makeMarketplaceHandlers(makeDeps());
    const result = await handlers.install('nope');
    expect(result).toEqual({ ok: false, error: expect.stringContaining('nope') });
  });
});

describe('makeMarketplaceHandlers.update', () => {
  it('updates via the derived url, subdir, id, and root, then reloads', async () => {
    const deps = makeDeps({ records: vi.fn(() => [record('seance', '0.1.0')]) });
    const handlers = makeMarketplaceHandlers(deps);
    const result = await handlers.update('seance');
    expect(deps.updateFromGit).toHaveBeenCalledWith(
      'https://github.com/nikrich/seance.git',
      'poltergeist-plugin',
      'seance',
      '/plugins',
    );
    expect(deps.reload).toHaveBeenCalled();
    expect(result).toEqual({ ok: true });
  });

  it('returns a failure result for an id not present in the registry', async () => {
    const deps = makeDeps({ records: vi.fn(() => [record('seance', '0.1.0')]) });
    const handlers = makeMarketplaceHandlers(deps);
    const result = await handlers.update('nope');
    expect(result).toEqual({ ok: false, error: expect.stringContaining('nope') });
    expect(deps.updateFromGit).not.toHaveBeenCalled();
  });
});
