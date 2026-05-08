import '@testing-library/jest-dom/vitest';
import type { GbBridge, Settings } from '../../preload/types';

const defaultSettings: Settings = {
  theme: 'dark',
  density: 'comfortable',
  vaultPath: '/tmp/vault',
};

const stubBridge: GbBridge = {
  settings: {
    getAll: async () => ({ ...defaultSettings }),
    set: async () => {},
  },
  dialogs: { pickVaultFolder: async () => null },
  shell: { openPath: async () => '' },
  platform: 'darwin',
};

(globalThis as unknown as { window: Window & { gb: GbBridge } }).window.gb = stubBridge;
