import type { ChatStreamEvent, DocsAssistEvent, DocsAssistRequest, LiveTranscriptEvent, RecorderLevelsEvent } from './api-types';
import type { ActivePluginInfo, MarketplaceListing, PluginRecord } from './plugin-types';

export type HttpMethod = 'GET' | 'POST' | 'PATCH' | 'DELETE' | 'PUT';

/** The only non-user actor the renderer may claim (spec B §2): inline AI and
 * the docs panel's Accept. The main process sends everything else as user. */
export type WriteActor = 'assistant';

export type Theme = 'dark' | 'light';
export type Density = 'comfortable' | 'compact';
export type LlmProvider = 'claude' | 'codex' | 'gemini' | 'local';
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
  onboardingComplete: boolean;
  /** Focus mode (⌘. / Ctrl+.): hide everything but the page being edited. */
  focusMode: boolean;
  /** voiceURI of the read-aloud voice; '' = auto (match the note's language). */
  readAloudVoice: string;
  /** Read-aloud speaking rate, 0.5–2 (1 = normal). */
  readAloudRate: number;

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
    showItemInFolder(path: string): Promise<{ ok: boolean; error?: string }>;
    openExternal(url: string): Promise<{ ok: true } | { ok: false; error: string }>;
  };
  cli: {
    install(): Promise<{ path: string; onPath: boolean }>;
  };
  platform: NodeJS.Platform;
  api: {
    request<T = unknown>(
      method: HttpMethod,
      path: string,
      body?: unknown,
      opts?: { ifMatch?: string; actor?: WriteActor },
    ): Promise<
      | { ok: true; data: T }
      | { ok: false; error: string; status?: number }
    >;
  };
  sidecar: {
    retry(): Promise<{ ok: true } | { ok: false; error: string }>;
  };
  recorder: {
    /** Raise an OS notification that native capture is waiting for a target choice. */
    notifyTargetChoice(): Promise<{ ok: true }>;
    /** Follow the live transcript; events arrive on `recorder:live:event`.
     *  Resolves when the stream ends (recording finalised) or fails. */
    liveSubscribe(): Promise<{ ok: true } | { ok: false; error: string }>;
    liveUnsubscribe(): Promise<{ ok: true }>;
    /** Follow the recording's audio levels; events on `recorder:levels:event`. */
    levelsSubscribe(): Promise<{ ok: true } | { ok: false; error: string }>;
    levelsUnsubscribe(): Promise<{ ok: true }>;
  };
  chat: {
    send(
      convId: string,
      text: string,
      attachmentPaths?: string[],
    ): Promise<{ ok: true } | { ok: false; error: string }>;
    stop(convId: string): Promise<{ ok: true } | { ok: false; error: string }>;
  };
  docs: {
    assist(req: DocsAssistRequest): Promise<{ ok: true } | { ok: false; error: string }>;
    assistStop(key: string): Promise<{ ok: true } | { ok: false; error: string }>;
    exportPdf(payload: {
      title: string;
      html: string;
    }): Promise<{ ok: true; path: string } | { ok: false; error: string } | { ok: false; cancelled: true }>;
    openGenerated(
      path: string,
    ): Promise<{ ok: true; path: string } | { ok: false; error: string }>;
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
  assets: {
    write(payload: {
      jotId: string;
      ext: string;
      bytes: ArrayBuffer;
    }): Promise<{ ok: true; path: string } | { ok: false; error: string }>;
    toUrl(vaultRelPath: string): string;
  };
  jot: {
    save(body: string): Promise<{ ok: true }>;
    cancel(): Promise<{ ok: true }>;
    onFocus(cb: () => void): () => void;
    onSaveFailed(cb: (payload: { body: string; error: string }) => void): () => void;
  };
  plugins: {
    list(): Promise<PluginRecord[]>;
    active(): Promise<ActivePluginInfo[]>;
    setEnabled(id: string, on: boolean): Promise<{ ok: true } | { ok: false; error: string }>;
    reload(): Promise<{ ok: true } | { ok: false; error: string }>;
    installFromFolder(): Promise<{ ok: true } | { ok: false; error: string }>;
    installFromGit(
      url: string,
      subdir?: string,
    ): Promise<{ ok: true } | { ok: false; error: string }>;
    uninstall(id: string): Promise<{ ok: true } | { ok: false; error: string }>;
    marketplace: {
      list(): Promise<MarketplaceListing[] | { ok: false; error: string }>;
      install(id: string): Promise<{ ok: true } | { ok: false; error: string }>;
      update(id: string): Promise<{ ok: true } | { ok: false; error: string }>;
    };
    onChanged(cb: (active: ActivePluginInfo[]) => void): () => void;
  };
  plugin(id: string): {
    invoke(channel: string, ...args: unknown[]): Promise<unknown>;
    on(channel: string, cb: (payload: unknown) => void): () => void;
    settings: {
      get(key: string): Promise<unknown>;
      set(key: string, v: unknown): Promise<void>;
    };
    sidecar: {
      request(
        method: string,
        path: string,
        body?: unknown,
        opts?: { ifMatch?: string },
      ): Promise<{ ok: true; data: unknown } | { ok: false; error: string; status?: number }>;
    };
  };
  updates: {
    download(): Promise<{ ok: true } | { ok: false; error: string }>;
    install(): Promise<void>;
    onAvailable(cb: (p: { version: string; canSelfUpdate: boolean }) => void): () => void;
    onProgress(cb: (p: { percent: number }) => void): () => void;
    onDownloaded(cb: (p: { version: string }) => void): () => void;
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
  on(
    channel: 'recorder:levels:event',
    listener: (event: RecorderLevelsEvent) => void,
  ): () => void;
  on(
    channel: 'recorder:live:event',
    listener: (event: LiveTranscriptEvent) => void,
  ): () => void;
  on(
    channel: 'docs:event',
    /** `key` is the stream key (stream_id, else jot id, else `path:<path>`);
     * `jotId` repeats it for listeners written before A5. */
    listener: (payload: { key?: string; jotId: string; event: DocsAssistEvent }) => void,
  ): () => void;
}

declare global {
  interface Window {
    gb: GbBridge;
  }
}
