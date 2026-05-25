export type Theme = 'dark' | 'light';
export type Density = 'comfortable' | 'compact';
export type LlmProvider = 'local' | 'anthropic' | 'openai';
export type AudioRetention = '30d' | '7d' | 'immediate' | 'forever';
export type TranscriptModel = 'whisper-large-v3' | 'whisper-medium';
export type FolderStructure = 'by-source' | 'by-date' | 'by-person';

export interface Settings {
  theme: Theme;
  density: Density;
  vaultPath: string;

  dailyNoteEnabled: boolean;
  markdownFrontmatter: boolean;
  autoLinkMentions: boolean;

  cloudSync: boolean;
  e2eEncryption: boolean;
  telemetry: boolean;
  llmProvider: LlmProvider;

  autoRecordFromCalendar: boolean;
  diarizeSpeakers: boolean;
  extractActionItems: boolean;
  audioRetention: AudioRetention;
  transcriptModel: TranscriptModel;

  folderStructure: FolderStructure;

  schedulerEnabled: boolean;
}

export interface GbBridge {
  settings: {
    getAll(): Promise<Settings>;
    set<K extends keyof Settings>(
      key: K,
      value: Settings[K],
    ): Promise<{ ok: true } | { ok: false; error: string }>;
  };
  dialogs: {
    pickVaultFolder(): Promise<string | null>;
  };
  shell: {
    openPath(path: string): Promise<{ ok: true } | { ok: false; error: string }>;
    openExternal(url: string): Promise<{ ok: true } | { ok: false; error: string }>;
  };
  platform: NodeJS.Platform;
  api: {
    request<T = unknown>(
      method: 'GET' | 'POST',
      path: string,
      body?: unknown,
    ): Promise<
      | { ok: true; data: T }
      | { ok: false; error: string; status?: number }
    >;
  };
  sidecar: {
    retry(): Promise<{ ok: true } | { ok: false; error: string }>;
  };
  tray: {
    setFailing(names: string[]): Promise<{ ok: true } | { ok: false; error: string }>;
  };
  on(channel: 'nav:settings', listener: () => void): () => void;
  on(channel: 'sidecar:ready', listener: () => void): () => void;
  on(
    channel: 'sidecar:failed',
    listener: (info: { reason: string }) => void,
  ): () => void;
  on(channel: 'meetings:openPrep', listener: (eventId: string) => void): () => void;
}

declare global {
  interface Window {
    gb: GbBridge;
  }
}
