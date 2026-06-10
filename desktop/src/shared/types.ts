import type { ChatStreamEvent } from './api-types';

export type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE';

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

  hotkeys: {
    jotOverlay: string;
  };
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
      method: HttpMethod,
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
  chat: {
    send(
      convId: string,
      text: string,
    ): Promise<{ ok: true } | { ok: false; error: string }>;
    stop(convId: string): Promise<{ ok: true } | { ok: false; error: string }>;
  };
  tray: {
    setFailing(names: string[]): Promise<{ ok: true } | { ok: false; error: string }>;
  };
  clipboard: {
    writeRich(payload: {
      html: string;
      text: string;
    }): Promise<{ ok: true } | { ok: false; error: string }>;
  };
  jot: {
    save(body: string): Promise<{ ok: true }>;
    cancel(): Promise<{ ok: true }>;
    onFocus(cb: () => void): () => void;
    onSaveFailed(cb: (payload: { body: string; error: string }) => void): () => void;
  };
  on(channel: 'nav:settings', listener: () => void): () => void;
  on(channel: 'sidecar:ready', listener: () => void): () => void;
  on(
    channel: 'sidecar:failed',
    listener: (info: { reason: string }) => void,
  ): () => void;
  on(channel: 'meetings:openPrep', listener: (eventId: string) => void): () => void;
  on(
    channel: 'chat:event',
    listener: (payload: { convId: string; event: ChatStreamEvent }) => void,
  ): () => void;
}

declare global {
  interface Window {
    gb: GbBridge;
  }
}
