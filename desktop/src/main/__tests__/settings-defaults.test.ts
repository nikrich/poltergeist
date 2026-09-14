import { describe, expect, it, vi } from 'vitest';

vi.mock('electron', () => ({ app: { getPath: () => '/tmp/ghostbrain-desktop-test' } }));

import { DEFAULT_SETTINGS } from '../settings';

describe('settings defaults', () => {
  it('runs the scheduler in-app by default so connectors sync without a hidden toggle', () => {
    expect(DEFAULT_SETTINGS.schedulerEnabled).toBe(true);
  });
});
