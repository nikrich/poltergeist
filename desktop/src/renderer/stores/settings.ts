import { create } from 'zustand';
import type { Settings } from '../../shared/types';

interface SettingsState extends Settings {
  ready: boolean;
  hydrate: () => Promise<void>;
  set: <K extends keyof Settings>(
    key: K,
    value: Settings[K],
  ) => Promise<{ ok: true } | { ok: false; error: string }>;
}

export const useSettings = create<SettingsState>((set) => ({
  // placeholder defaults — overwritten on hydrate()
  theme: 'dark',
  density: 'comfortable',
  vaultPath: '',

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

  ready: false,
  hydrate: async () => {
    const all = await window.gb.settings.getAll();
    set({ ...all, ready: true });
  },
  set: async (key, value) => {
    const result = await window.gb.settings.set(key, value);
    if (result.ok) {
      set({ [key]: value } as Pick<Settings, typeof key>);
    }
    return result;
  },
}));
