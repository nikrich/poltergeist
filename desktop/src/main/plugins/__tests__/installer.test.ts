import { describe, it, expect, beforeEach, vi } from 'vitest';
import { mkdtempSync, cpSync, existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const STORE_DIR = mkdtempSync(join(tmpdir(), 'gb-installer-store-'));
vi.mock('electron', () => ({
  app: { getPath: () => STORE_DIR },
}));

import { installFromFolder, installFromGit, uninstall } from '../installer';
import * as store from '../store';

const FIXTURES = join(__dirname, 'fixtures');

let pluginsRoot: string;
beforeEach(() => {
  pluginsRoot = mkdtempSync(join(tmpdir(), 'gb-installer-plugins-'));
  store._setPathForTest(join(mkdtempSync(join(tmpdir(), 'gb-installer-st-')), 'plugins.json'));
});

describe('installFromFolder', () => {
  it('copies a valid plugin and enables it', async () => {
    const rec = await installFromFolder(join(FIXTURES, 'hello'), pluginsRoot);
    expect(rec.id).toBe('hello');
    expect(existsSync(join(pluginsRoot, 'hello', 'dist', 'main.cjs'))).toBe(true);
    expect(store.isEnabled('hello')).toBe(true);
  });

  it('refuses an id collision', async () => {
    await installFromFolder(join(FIXTURES, 'hello'), pluginsRoot);
    await expect(installFromFolder(join(FIXTURES, 'hello'), pluginsRoot)).rejects.toThrow(
      /already installed/,
    );
  });

  it('rejects an invalid manifest and leaves pluginsRoot untouched', async () => {
    const bad = mkdtempSync(join(tmpdir(), 'gb-bad-plugin-'));
    writeFileSync(join(bad, 'manifest.json'), JSON.stringify({ id: 'NOT OK' }));
    await expect(installFromFolder(bad, pluginsRoot)).rejects.toThrow();
    expect(existsSync(join(pluginsRoot, 'NOT OK'))).toBe(false);
  });
});

describe('installFromGit', () => {
  it('clones, takes the subdir, skips .git, installs', async () => {
    // local fixture git repo with the plugin under pkg/
    const repo = mkdtempSync(join(tmpdir(), 'gb-git-fixture-'));
    cpSync(join(FIXTURES, 'hello'), join(repo, 'pkg'), { recursive: true });
    mkdirSync(join(repo, 'unrelated'));
    writeFileSync(join(repo, 'unrelated', 'x.txt'), 'x');
    execFileSync('git', ['init', '-q'], { cwd: repo });
    execFileSync('git', ['add', '-A'], { cwd: repo });
    execFileSync('git', ['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'x'], {
      cwd: repo,
    });

    const rec = await installFromGit(`file://${repo}`, 'pkg', pluginsRoot);
    expect(rec.id).toBe('hello');
    expect(existsSync(join(pluginsRoot, 'hello', 'dist', 'renderer.mjs'))).toBe(true);
    expect(existsSync(join(pluginsRoot, 'hello', '.git'))).toBe(false);
    expect(existsSync(join(pluginsRoot, 'hello', 'unrelated'))).toBe(false);
  });

  it('rejects disallowed url schemes', async () => {
    await expect(installFromGit('http://insecure.example/x', undefined, pluginsRoot)).rejects.toThrow(
      /url/i,
    );
  });
});

describe('uninstall', () => {
  it('removes the dir and forgets the enabled flag', async () => {
    await installFromFolder(join(FIXTURES, 'hello'), pluginsRoot);
    store.setData('hello', 'keep', 'me');
    await uninstall('hello', pluginsRoot);
    expect(existsSync(join(pluginsRoot, 'hello'))).toBe(false);
    expect(store.isEnabled('hello')).toBe(false);
    expect(store.getData('hello', 'keep')).toBe('me'); // data survives
  });
});
