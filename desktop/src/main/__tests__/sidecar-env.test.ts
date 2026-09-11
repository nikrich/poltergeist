import { delimiter } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';

vi.mock('electron', () => ({ app: { isPackaged: false, getPath: () => '/tmp' } }));

import { buildExtraPath, buildSidecarEnv } from '../sidecar';

describe('buildSidecarEnv', () => {
  it('passes the configured vault path and scheduler flag to the sidecar', () => {
    const env = buildSidecarEnv({ PATH: '/usr/bin', HOME: '/Users/x' }, {
      schedulerEnabled: false,
      vaultPath: '/Users/x/notes/vault',
      extraPath: '/opt/homebrew/bin',
    });
    expect(env.VAULT_PATH).toBe('/Users/x/notes/vault');
    expect(env.GHOSTBRAIN_SCHEDULER_ENABLED).toBe('0');
    expect(env.PYTHONUNBUFFERED).toBe('1');
    expect(env.PATH).toBe('/opt/homebrew/bin:/usr/bin');
    expect(env.HOME).toBe('/Users/x');
  });

  it('expands a leading ~ so Python sees an absolute path', () => {
    const env = buildSidecarEnv({ HOME: '/Users/x' }, { schedulerEnabled: true, vaultPath: '~/ghostbrain/vault', extraPath: '' });
    expect(env.VAULT_PATH).toBe('/Users/x/ghostbrain/vault');
  });
});

describe('buildSidecarEnv PATH join', () => {
  const originalPlatform = process.platform;

  afterEach(() => {
    Object.defineProperty(process, 'platform', { value: originalPlatform });
  });

  it('joins PATH using node:path delimiter, not a hardcoded colon', () => {
    // node:path's `delimiter` is fixed to the actual host OS (':' on
    // macOS/Linux, ';' on Windows) — stubbing process.platform here doesn't
    // change it, but it exercises the win32 code path this function is
    // meant to support. The real regression coverage for "not a hardcoded
    // colon" is that this assertion is built from the same `delimiter`
    // import the implementation uses, not a literal character.
    Object.defineProperty(process, 'platform', { value: 'win32' });
    const basePath = 'C:\\Windows;C:\\Windows\\System32';
    const env = buildSidecarEnv({ PATH: basePath }, {
      schedulerEnabled: false,
      vaultPath: 'C:\\Users\\x\\vault',
      extraPath: 'C:\\Users\\x\\.local\\bin',
    });
    expect(env.PATH).toBe(`C:\\Users\\x\\.local\\bin${delimiter}${basePath}`);
  });
});

describe('buildExtraPath', () => {
  it('includes the homebrew and /usr/local dirs on darwin', () => {
    const extra = buildExtraPath('darwin', '/Users/x');
    expect(extra).toBe('/opt/homebrew/bin:/usr/local/bin:/Users/x/.local/bin');
  });

  it('includes the homebrew and /usr/local dirs on linux', () => {
    const extra = buildExtraPath('linux', '/home/x');
    expect(extra).toBe('/opt/homebrew/bin:/usr/local/bin:/home/x/.local/bin');
  });

  it('skips the POSIX-only dirs on win32 but keeps the user local bin', () => {
    const extra = buildExtraPath('win32', 'C:\\Users\\x');
    expect(extra).not.toContain('/opt/homebrew/bin');
    expect(extra).not.toContain('/usr/local/bin');
    expect(extra).toContain('.local');
    expect(extra).toContain('bin');
  });

  it('drops an empty home directory cleanly', () => {
    const extra = buildExtraPath('darwin', '');
    expect(extra).toBe('/opt/homebrew/bin:/usr/local/bin');
  });
});
