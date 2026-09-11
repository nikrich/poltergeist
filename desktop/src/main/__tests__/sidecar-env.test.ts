import { describe, expect, it, vi } from 'vitest';

vi.mock('electron', () => ({ app: { isPackaged: false, getPath: () => '/tmp' } }));

import { buildSidecarEnv } from '../sidecar';

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
