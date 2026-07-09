import '@testing-library/jest-dom/vitest';
import type { GbBridge, Settings } from '../../shared/types';

// jsdom does not implement Blob.prototype.arrayBuffer — polyfill it so tests
// that call file.arrayBuffer() work without a real browser environment.
if (!Blob.prototype.arrayBuffer) {
  Blob.prototype.arrayBuffer = function (): Promise<ArrayBuffer> {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as ArrayBuffer);
      reader.onerror = () => reject(reader.error);
      reader.readAsArrayBuffer(this);
    });
  };
}

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
  onboardingComplete: false,

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
  chat: {
    send: async () => ({ ok: true }),
    stop: async () => ({ ok: true }),
  },
  docs: {
    assist: async () => ({ ok: true }),
    assistStop: async () => ({ ok: true }),
    exportPdf: async () => ({ ok: true, path: '/tmp/doc.pdf' }),
    openGenerated: async () => ({ ok: true, path: '/tmp/doc.pdf' }),
  },
  tray: { setFailing: async () => ({ ok: true }) },
  clipboard: { writeRich: async () => ({ ok: true }) },
  assets: {
    write: async () => ({ ok: true as const, path: '90-meta/assets/jots/2026/06/stub-x.jpg' }),
    toUrl: (p: string) => 'gbasset://asset/' + p,
  },
  jot: {
    save: async () => ({ ok: true as const }),
    cancel: async () => ({ ok: true as const }),
    onFocus: () => () => {},
    onSaveFailed: () => () => {},
  },
  plugins: {
    list: async () => [],
    active: async () => [],
    setEnabled: async () => ({ ok: true }),
    reload: async () => ({ ok: true }),
    installFromFolder: async () => ({ ok: true }),
    installFromGit: async () => ({ ok: true }),
    uninstall: async () => ({ ok: true }),
    marketplace: {
      list: async () => [],
      install: async () => ({ ok: true }),
      update: async () => ({ ok: true }),
    },
    onChanged: () => () => {},
  },
  plugin: () => ({
    invoke: async () => undefined,
    on: () => () => {},
    settings: { get: async () => undefined, set: async () => {} },
    sidecar: { request: async () => ({ ok: true, data: null }) },
  }),
  on: (() => () => {}) as GbBridge['on'],
};

(globalThis as unknown as { window: Window & { gb: GbBridge } }).window.gb = stubBridge;
