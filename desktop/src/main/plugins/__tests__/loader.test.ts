import { describe, it, expect, beforeEach, vi } from 'vitest';
import { mkdtempSync, cpSync, mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const STORE_DIR = mkdtempSync(join(tmpdir(), 'gb-loader-store-'));
vi.mock('electron', () => ({
  app: { getPath: () => STORE_DIR },
}));

import { createLoader, type LoaderDeps } from '../loader';
import * as store from '../store';

const FIXTURES = join(__dirname, 'fixtures');

function makeDeps(pluginsRoot: string) {
  const handlers = new Map<string, (...args: unknown[]) => unknown>();
  const broadcasts: Array<{ channel: string; payload: unknown }> = [];
  const deps: LoaderDeps = {
    pluginsRoot,
    dataRoot: mkdtempSync(join(tmpdir(), 'gb-loader-data-')),
    registerHandler: (ch, fn) => handlers.set(ch, fn),
    unregisterHandler: (ch) => handlers.delete(ch),
    broadcast: (channel, payload) => broadcasts.push({ channel, payload }),
  };
  return { deps, handlers, broadcasts };
}

function freshRoot(...fixtureNames: string[]): string {
  const root = mkdtempSync(join(tmpdir(), 'gb-loader-plugins-'));
  for (const name of fixtureNames) {
    cpSync(join(FIXTURES, name), join(root, name), { recursive: true });
  }
  return root;
}

beforeEach(() => {
  store._setPathForTest(join(mkdtempSync(join(tmpdir(), 'gb-loader-st-')), 'plugins.json'));
});

describe('loader', () => {
  it('scan finds plugins and flags invalid manifests', () => {
    const root = freshRoot('hello', 'broken');
    mkdirSync(join(root, 'garbage'));
    writeFileSync(join(root, 'garbage', 'manifest.json'), '{"id":"NOT VALID!!"}');
    const { deps } = makeDeps(root);
    const loader = createLoader(deps);
    const records = loader.scan();
    const byId = Object.fromEntries(records.map((r) => [r.id, r]));
    expect(byId.hello.state).toBe('disabled');
    expect(byId.broken.state).toBe('disabled');
    expect(byId.garbage.state).toBe('invalid');
    expect(byId.garbage.manifest).toBeNull();
  });

  it('activates enabled plugins with namespaced handlers', async () => {
    const root = freshRoot('hello');
    const { deps, handlers } = makeDeps(root);
    store.setEnabled('hello', true);
    const loader = createLoader(deps);
    loader.scan();
    await loader.activateEnabled();
    const fn = handlers.get('gb:plugin:hello:ping');
    expect(fn).toBeDefined();
    expect(await fn!()).toBe('pong-hello');
    expect(loader.active()).toEqual([
      {
        id: 'hello',
        name: 'Hello',
        icon: 'ghost',
        hasRenderer: true,
        rendererEntry: 'dist/renderer.mjs',
      },
    ]);
  });

  it('a throwing activate marks the plugin errored and spares the rest', async () => {
    const root = freshRoot('hello', 'broken');
    const { deps, handlers } = makeDeps(root);
    store.setEnabled('hello', true);
    store.setEnabled('broken', true);
    const loader = createLoader(deps);
    loader.scan();
    await loader.activateEnabled();
    const broken = loader.records().find((r) => r.id === 'broken');
    expect(broken?.state).toBe('errored');
    expect(broken?.error).toContain('boom');
    expect(loader.active().map((p) => p.id)).toEqual(['hello']);
    expect(handlers.has('gb:plugin:hello:ping')).toBe(true);
  });

  it('rejects invalid ipc channel names from plugins', async () => {
    const root = freshRoot('hello');
    // mutate the fixture copy to register a bad channel
    writeFileSync(
      join(root, 'hello', 'dist', 'main.cjs'),
      `module.exports={activate(ctx){ctx.ipc.handle('BAD CHANNEL!',()=>1)},deactivate(){}}`,
    );
    const { deps, handlers } = makeDeps(root);
    store.setEnabled('hello', true);
    const loader = createLoader(deps);
    loader.scan();
    await loader.activateEnabled();
    expect(loader.records().find((r) => r.id === 'hello')?.state).toBe('errored');
    expect(handlers.size).toBe(0);
  });

  it('setEnabled(false) deactivates and unregisters handlers', async () => {
    const root = freshRoot('hello');
    const { deps, handlers } = makeDeps(root);
    store.setEnabled('hello', true);
    const loader = createLoader(deps);
    loader.scan();
    await loader.activateEnabled();
    expect(handlers.size).toBe(1);
    await loader.setEnabled('hello', false);
    expect(handlers.size).toBe(0);
    expect(store.isEnabled('hello')).toBe(false);
    expect(loader.active()).toEqual([]);
  });

  it('reloadAll picks up edited plugin code (require cache cleared)', async () => {
    const root = freshRoot('hello');
    const { deps, handlers } = makeDeps(root);
    store.setEnabled('hello', true);
    const loader = createLoader(deps);
    loader.scan();
    await loader.activateEnabled();
    expect(await handlers.get('gb:plugin:hello:ping')!()).toBe('pong-hello');
    writeFileSync(
      join(root, 'hello', 'dist', 'main.cjs'),
      `module.exports={activate(ctx){ctx.ipc.handle('ping',()=>'v2')},deactivate(){}}`,
    );
    await loader.reloadAll();
    expect(await handlers.get('gb:plugin:hello:ping')!()).toBe('v2');
  });
});
