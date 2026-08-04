import { describe, it, expect, beforeEach, vi } from 'vitest';
import { mkdtempSync, writeFileSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const TESTDIR = mkdtempSync(join(tmpdir(), 'gb-plugins-store-'));

vi.mock('electron', () => ({
  app: { getPath: () => TESTDIR },
}));

import * as store from '../store';

describe('plugins store', () => {
  beforeEach(() => {
    store._resetForTest();
    writeFileSync(join(TESTDIR, 'plugins.json'), JSON.stringify({ version: 1, enabled: {}, data: {} }));
  });

  it('unknown plugin is disabled by default', () => {
    expect(store.isEnabled('nope')).toBe(false);
  });

  it('setEnabled persists across cache reset', () => {
    store.setEnabled('seance', true);
    store._resetForTest();
    expect(store.isEnabled('seance')).toBe(true);
    // and it actually hit the disk
    const disk = JSON.parse(readFileSync(join(TESTDIR, 'plugins.json'), 'utf-8'));
    expect(disk.enabled.seance).toBe(true);
  });

  it('data get/set roundtrip, namespaced per plugin', () => {
    store.setData('seance', 'seanceRepoPath', '/x/y');
    store.setData('other', 'seanceRepoPath', '/z');
    store._resetForTest();
    expect(store.getData('seance', 'seanceRepoPath')).toBe('/x/y');
    expect(store.getData('other', 'seanceRepoPath')).toBe('/z');
    expect(store.getData('seance', 'missing')).toBeUndefined();
  });

  it('forget drops enabled flag but keeps data', () => {
    store.setEnabled('seance', true);
    store.setData('seance', 'k', 1);
    store.forget('seance');
    store._resetForTest();
    expect(store.isEnabled('seance')).toBe(false);
    expect(store.getData('seance', 'k')).toBe(1);
  });

  it('corrupted file falls back to defaults without throwing', () => {
    writeFileSync(join(TESTDIR, 'plugins.json'), '{nope');
    store._resetForTest();
    expect(store.isEnabled('anything')).toBe(false);
    // and writes still work afterwards
    store.setEnabled('a', true);
    expect(store.isEnabled('a')).toBe(true);
  });
});
