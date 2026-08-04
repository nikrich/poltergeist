import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { mkdtempSync, rmSync, readFileSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

let workDir: string;

vi.mock('electron', () => ({
  app: { getPath: () => workDir },
}));

beforeEach(() => {
  workDir = mkdtempSync(join(tmpdir(), 'gb-settings-'));
  vi.resetModules();
});

afterEach(() => {
  rmSync(workDir, { recursive: true, force: true });
});

describe('settings store', () => {
  it('returns defaults when no file exists', async () => {
    const { getAll } = await import('./settings');
    const s = getAll();
    expect(s.theme).toBe('dark');
    expect(s.density).toBe('comfortable');
    expect(s.vaultPath).toMatch(/ghostbrain[/\\]vault$/);
  });

  it('persists set values to disk and reads them back', async () => {
    const { getAll, setKey } = await import('./settings');
    setKey('theme', 'light');
    expect(existsSync(join(workDir, 'config.json'))).toBe(true);
    const onDisk = JSON.parse(readFileSync(join(workDir, 'config.json'), 'utf-8'));
    expect(onDisk.theme).toBe('light');
    expect(getAll().theme).toBe('light');
  });

  it('merges defaults with on-disk values when a key is missing', async () => {
    const { writeFileSync } = await import('node:fs');
    writeFileSync(join(workDir, 'config.json'), JSON.stringify({ version: 1, theme: 'light' }));
    const { getAll } = await import('./settings');
    expect(getAll().theme).toBe('light');
    expect(getAll().density).toBe('comfortable');
  });

  it('falls back to defaults on corrupt JSON', async () => {
    const { writeFileSync } = await import('node:fs');
    writeFileSync(join(workDir, 'config.json'), '{ not valid json');
    const { getAll } = await import('./settings');
    expect(getAll().theme).toBe('dark');
  });
});
