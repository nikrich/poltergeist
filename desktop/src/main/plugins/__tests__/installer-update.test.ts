import { describe, it, expect, beforeEach, vi } from 'vitest';
import { mkdtempSync, cpSync, existsSync, readFileSync, writeFileSync, rmSync } from 'node:fs';
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

function initGitRepo(dir: string, message: string) {
  execFileSync('git', ['init', '-q'], { cwd: dir });
  execFileSync('git', ['add', '-A'], { cwd: dir });
  execFileSync('git', ['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', message], {
    cwd: dir,
  });
}

function commitAll(dir: string, message: string) {
  execFileSync('git', ['add', '-A'], { cwd: dir });
  execFileSync('git', ['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', message], {
    cwd: dir,
  });
}

describe('updateFromGit', () => {
  it('replaces the install with the new version, preserving enabled flag and data', async () => {
    const repo = mkdtempSync(join(tmpdir(), 'gb-git-update-fixture-'));
    cpSync(join(FIXTURES, 'hello'), repo, { recursive: true });
    initGitRepo(repo, 'v1');

    const rec = await installFromGit(`file://${repo}`, undefined, pluginsRoot);
    expect(rec.id).toBe('hello');
    store.setData('hello', 'k', 'v');
    expect(store.isEnabled('hello')).toBe(true);

    // bump the version, drop renderer.mjs, add a new file
    const manifest = JSON.parse(readFileSync(join(repo, 'manifest.json'), 'utf-8'));
    manifest.version = '2.0.0';
    writeFileSync(join(repo, 'manifest.json'), JSON.stringify(manifest, null, 2));
    rmSync(join(repo, 'dist', 'renderer.mjs'));
    writeFileSync(join(repo, 'dist', 'new-file.txt'), 'new');
    commitAll(repo, 'v2');

    const updated = await updateFromGit(`file://${repo}`, undefined, 'hello', pluginsRoot);
    expect(updated.id).toBe('hello');
    expect(updated.manifest?.version).toBe('2.0.0');
    expect(updated.state).toBe('enabled');

    const onDisk = JSON.parse(readFileSync(join(pluginsRoot, 'hello', 'manifest.json'), 'utf-8'));
    expect(onDisk.version).toBe('2.0.0');
    expect(existsSync(join(pluginsRoot, 'hello', 'dist', 'renderer.mjs'))).toBe(false);
    expect(existsSync(join(pluginsRoot, 'hello', 'dist', 'new-file.txt'))).toBe(true);
    expect(existsSync(join(pluginsRoot, 'hello', '.git'))).toBe(false);

    expect(store.isEnabled('hello')).toBe(true);
    expect(store.getData('hello', 'k')).toBe('v');
  });

  it('rejects when the fetched manifest id does not match expectedId', async () => {
    const repo = mkdtempSync(join(tmpdir(), 'gb-git-update-mismatch-'));
    cpSync(join(FIXTURES, 'hello'), repo, { recursive: true });
    initGitRepo(repo, 'v1');

    await expect(updateFromGit(`file://${repo}`, undefined, 'not-hello', pluginsRoot)).rejects.toThrow(
      /update fetched a different plugin id/,
    );
  });
});
