import { describe, it, expect, beforeEach, vi } from 'vitest';
import { mkdtempSync, cpSync, existsSync, writeFileSync, readFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const STORE_DIR = mkdtempSync(join(tmpdir(), 'gb-installer-update-store-'));
vi.mock('electron', () => ({
  app: { getPath: () => STORE_DIR },
}));

import { installFromGit, updateFromGit } from '../installer';
import * as store from '../store';

const FIXTURES = join(__dirname, 'fixtures');

let pluginsRoot: string;
beforeEach(() => {
  pluginsRoot = mkdtempSync(join(tmpdir(), 'gb-installer-update-plugins-'));
  store._setPathForTest(join(mkdtempSync(join(tmpdir(), 'gb-installer-update-st-')), 'plugins.json'));
});

const git = (repo: string, args: string[]) => execFileSync('git', args, { cwd: repo });

function commit(repo: string, message: string) {
  git(repo, ['add', '-A']);
  git(repo, ['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', message]);
}

/**
 * Builds a fixture repo at pkg/dist/main.cjs whose content marks which
 * revision it is. 'some-tag' points at V1; the default branch is then
 * advanced to V2, so a ref-less clone would get V2 and only an explicit
 * `ref: 'some-tag'` checkout gets V1.
 */
function buildRefFixtureRepo(): string {
  const repo = mkdtempSync(join(tmpdir(), 'gb-git-ref-fixture-'));
  cpSync(join(FIXTURES, 'hello'), join(repo, 'pkg'), { recursive: true });
  writeFileSync(join(repo, 'pkg', 'dist', 'main.cjs'), 'module.exports = "V1";');
  git(repo, ['init', '-q']);
  commit(repo, 'v1');
  git(repo, ['tag', 'some-tag']);

  writeFileSync(join(repo, 'pkg', 'dist', 'main.cjs'), 'module.exports = "V2";');
  commit(repo, 'v2');

  return repo;
}

describe('installFromGit ref support', () => {
  it('checks out the given tag/branch instead of the default branch', async () => {
    const repo = buildRefFixtureRepo();

    const rec = await installFromGit(`file://${repo}`, 'pkg', pluginsRoot, 'some-tag');

    expect(rec.id).toBe('hello');
    const content = readFileSync(join(pluginsRoot, 'hello', 'dist', 'main.cjs'), 'utf-8');
    expect(content).toBe('module.exports = "V1";');
  });

  it('still installs via the classic 3-arg call (no ref)', async () => {
    const repo = mkdtempSync(join(tmpdir(), 'gb-git-classic-fixture-'));
    cpSync(join(FIXTURES, 'hello'), join(repo, 'pkg'), { recursive: true });
    git(repo, ['init', '-q']);
    commit(repo, 'init');

    const rec = await installFromGit(`file://${repo}`, 'pkg', pluginsRoot);

    expect(rec.id).toBe('hello');
    expect(existsSync(join(pluginsRoot, 'hello', 'dist', 'main.cjs'))).toBe(true);
    expect(store.isEnabled('hello')).toBe(true);
  });
});

describe('updateFromGit', () => {
  it('updates an already-installed plugin in place, preserving plugin data', async () => {
    const repo = mkdtempSync(join(tmpdir(), 'gb-git-update-fixture-'));
    cpSync(join(FIXTURES, 'hello'), join(repo, 'pkg'), { recursive: true });
    writeFileSync(join(repo, 'pkg', 'dist', 'main.cjs'), 'module.exports = "V1";');
    git(repo, ['init', '-q']);
    commit(repo, 'v1');

    await installFromGit(`file://${repo}`, 'pkg', pluginsRoot);
    store.setData('hello', 'keep', 'me');

    writeFileSync(join(repo, 'pkg', 'dist', 'main.cjs'), 'module.exports = "V2";');
    commit(repo, 'v2');

    const rec = await updateFromGit(`file://${repo}`, 'pkg', pluginsRoot);

    expect(rec.id).toBe('hello');
    const content = readFileSync(join(pluginsRoot, 'hello', 'dist', 'main.cjs'), 'utf-8');
    expect(content).toBe('module.exports = "V2";');
    expect(store.getData('hello', 'keep')).toBe('me');
  });

  it('does not throw the "already installed" error', async () => {
    const repo = mkdtempSync(join(tmpdir(), 'gb-git-update-noerr-fixture-'));
    cpSync(join(FIXTURES, 'hello'), join(repo, 'pkg'), { recursive: true });
    git(repo, ['init', '-q']);
    commit(repo, 'init');

    await installFromGit(`file://${repo}`, 'pkg', pluginsRoot);

    await expect(updateFromGit(`file://${repo}`, 'pkg', pluginsRoot)).resolves.not.toThrow();
  });
});
