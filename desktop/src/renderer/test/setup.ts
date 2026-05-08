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
};

const stubBridge: GbBridge = {
  settings: {
    getAll: async () => ({ ...defaultSettings }),
    set: async () => ({ ok: true }),
  },
  dialogs: { pickVaultFolder: async () => null },
  shell: { openPath: async () => ({ ok: true }) },
  platform: 'darwin',
};

(globalThis as unknown as { window: Window & { gb: GbBridge } }).window.gb = stubBridge;
