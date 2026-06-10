import '@testing-library/jest-dom/vitest';
import type { GbBridge, Settings } from '../../shared/types';

const defaultSettings: Settings = {
  theme: 'dark',
  density: 'comfortable',
  vaultPath: '/tmp/vault',

  dailyNoteEnabled: true,
  markdownFrontmatter: true,
  autoLinkMentions: true,

  cloudSync: false,
  e2eEncryption: true,
  telemetry: false,
  llmProvider: 'local',

  autoRecordFromCalendar: true,
  diarizeSpeakers: true,
  extractActionItems: true,
  audioRetention: '30d',
  transcriptModel: 'whisper-large-v3',

  folderStructure: 'by-source',

  schedulerEnabled: false,

  hotkeys: {
    jotOverlay: 'Alt+J',
  },
};

const stubBridge: GbBridge = {
  settings: {
    getAll: async () => ({ ...defaultSettings }),
    set: async () => ({ ok: true }),
  },
  dialogs: { pickVaultFolder: async () => null },
  shell: {
    openPath: async () => ({ ok: true }),
    openExternal: async () => ({ ok: true }),
  },
  platform: 'darwin',
  api: { request: (async () => ({ ok: true, data: null })) as GbBridge['api']['request'] },
  sidecar: { retry: async () => ({ ok: true }) },
  tray: { setFailing: async () => ({ ok: true }) },
  clipboard: { writeRich: async () => ({ ok: true }) },
  jot: {
    save: async () => ({ ok: true as const }),
    cancel: async () => ({ ok: true as const }),
    onFocus: () => () => {},
    onSaveFailed: () => () => {},
  },
  on: (() => () => {}) as GbBridge['on'],
};

(globalThis as unknown as { window: Window & { gb: GbBridge } }).window.gb = stubBridge;
