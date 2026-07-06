import { createRequire } from 'node:module';
import { existsSync, readdirSync, readFileSync, mkdirSync, realpathSync } from 'node:fs';
import { join } from 'node:path';
import {
  manifestSchema,
  type ActivePluginInfo,
  type PluginManifest,
  type PluginRecord,
} from '../../shared/plugin-types';
import * as store from './store';

// Loads trusted plugin code. Every call into a plugin is fenced: a throw marks
// the plugin `errored`, removes its IPC handlers, and never propagates.

const CHANNEL_RE = /^[a-z0-9:_-]+$/;
const DEACTIVATE_TIMEOUT_MS = 2000;

export interface PluginContext {
  pluginId: string;
  pluginDir: string;
  dataDir: string;
  settings: {
    get<T>(key: string): T | undefined;
    set(key: string, v: unknown): void;
  };
  ipc: {
    handle(channel: string, fn: (...args: unknown[]) => unknown): void;
    send(channel: string, payload: unknown): void;
  };
  log: (...args: unknown[]) => void;
}

export interface LoaderDeps {
  pluginsRoot: string;
  dataRoot: string;
  registerHandler(channel: string, fn: (...args: unknown[]) => unknown): void;
  unregisterHandler(channel: string): void;
  broadcast(channel: string, payload: unknown): void;
}

interface PluginModule {
  activate?: (ctx: PluginContext) => unknown;
  deactivate?: () => unknown;
}

interface LiveEntry {
  module: PluginModule;
  channels: Set<string>;
}

const nodeRequire = createRequire(__filename);

export function createLoader(deps: LoaderDeps) {
  let recordList: PluginRecord[] = [];
  const live = new Map<string, LiveEntry>();

  function fail(record: PluginRecord, err: unknown): void {
    record.state = 'errored';
    record.error = err instanceof Error ? err.message : String(err);
    const entry = live.get(record.id);
    if (entry) {
      for (const ch of entry.channels) deps.unregisterHandler(ch);
      live.delete(record.id);
    }
    console.error(`[plugin:${record.id}] errored:`, record.error);
  }

  function scan(): PluginRecord[] {
    recordList = [];
    if (!existsSync(deps.pluginsRoot)) return recordList;
    for (const name of readdirSync(deps.pluginsRoot, { withFileTypes: true })) {
      if (!name.isDirectory()) continue;
      const dir = join(deps.pluginsRoot, name.name);
      const manifestPath = join(dir, 'manifest.json');
      let manifest: PluginManifest | null = null;
      let error: string | undefined;
      try {
        const raw = JSON.parse(readFileSync(manifestPath, 'utf-8'));
        const parsed = manifestSchema.safeParse(raw);
        if (parsed.success) manifest = parsed.data;
        else error = parsed.error.issues[0]?.message ?? 'invalid manifest';
      } catch (e) {
        error = e instanceof Error ? e.message : String(e);
      }
      // Freshly scanned records start 'disabled' even when the enabled flag is
      // set — activation is what earns the 'enabled' state (or 'errored').
      recordList.push(
        manifest
          ? { id: manifest.id, dir, manifest, state: 'disabled', error: undefined }
          : { id: name.name, dir, manifest: null, state: 'invalid', error },
      );
    }
    return recordList;
  }

  function makeContext(record: PluginRecord, channels: Set<string>): PluginContext {
    const dataDir = join(deps.dataRoot, record.id);
    return {
      pluginId: record.id,
      pluginDir: record.dir,
      dataDir,
      settings: {
        get: <T>(key: string) => store.getData(record.id, key) as T | undefined,
        set: (key, v) => store.setData(record.id, key, v),
      },
      ipc: {
        handle: (channel, fn) => {
          if (!CHANNEL_RE.test(channel)) {
            throw new Error(`invalid ipc channel name: ${JSON.stringify(channel)}`);
          }
          const full = `gb:plugin:${record.id}:${channel}`;
          if (channels.has(full)) {
            throw new Error(`ipc channel registered twice: ${channel}`);
          }
          channels.add(full);
          // A throwing handler rejects that one call (the renderer sees the
          // error); it does NOT mark the plugin errored — only activate/load
          // failures do. A validation error must not kill the plugin.
          deps.registerHandler(full, (...args) => fn(...args));
        },
        send: (channel, payload) => {
          if (!CHANNEL_RE.test(channel)) return;
          deps.broadcast(`gb:plugin:${record.id}:${channel}`, payload);
        },
      },
      log: (...args) => console.log(`[plugin:${record.id}]`, ...args),
    };
  }

  async function activate(record: PluginRecord): Promise<void> {
    if (!record.manifest) return;
    if (!record.manifest.entry.main) {
      // renderer-only plugin: nothing to run in the main process
      record.state = 'enabled';
      return;
    }
    const entryPath = join(record.dir, record.manifest.entry.main);
    const channels = new Set<string>();
    try {
      mkdirSync(join(deps.dataRoot, record.id), { recursive: true });
      const mod = nodeRequire(entryPath) as PluginModule;
      live.set(record.id, { module: mod, channels });
      await mod.activate?.(makeContext(record, channels));
      record.state = 'enabled';
      record.error = undefined;
    } catch (err) {
      live.set(record.id, { module: {}, channels });
      fail(record, err);
    }
  }

  async function deactivate(record: PluginRecord): Promise<void> {
    const entry = live.get(record.id);
    if (!entry) return;
    for (const ch of entry.channels) deps.unregisterHandler(ch);
    live.delete(record.id);
    try {
      await Promise.race([
        Promise.resolve(entry.module.deactivate?.()),
        new Promise((resolve) => setTimeout(resolve, DEACTIVATE_TIMEOUT_MS)),
      ]);
    } catch (err) {
      console.error(`[plugin:${record.id}] deactivate failed:`, err);
    }
    clearRequireCache(record.dir);
    if (record.state === 'enabled') record.state = 'disabled';
  }

  function clearRequireCache(dir: string): void {
    // require cache keys are realpaths (e.g. /private/var on macOS while the
    // plugin dir may be addressed via the /var symlink) — compare realpaths.
    let real: string;
    try {
      real = realpathSync(dir);
    } catch {
      real = dir;
    }
    for (const key of Object.keys(nodeRequire.cache)) {
      for (const prefix of [dir, real]) {
        if (key.startsWith(prefix + '/') || key.startsWith(prefix + '\\')) {
          delete nodeRequire.cache[key];
          break;
        }
      }
    }
  }

  async function activateEnabled(): Promise<void> {
    for (const record of recordList) {
      if (record.manifest && store.isEnabled(record.id) && !live.has(record.id)) {
        await activate(record);
      }
    }
  }

  return {
    scan,
    activateEnabled,

    async setEnabled(id: string, on: boolean): Promise<void> {
      store.setEnabled(id, on);
      const record = recordList.find((r) => r.id === id);
      if (!record || !record.manifest) return;
      if (on) {
        await activate(record);
      } else {
        await deactivate(record);
        record.state = 'disabled';
        record.error = undefined;
      }
    },

    async deactivateAll(): Promise<void> {
      for (const record of recordList) await deactivate(record);
    },

    async reloadAll(): Promise<void> {
      for (const record of recordList) await deactivate(record);
      scan();
      await activateEnabled();
    },

    records(): PluginRecord[] {
      return recordList.map((r) => ({ ...r }));
    },

    active(): ActivePluginInfo[] {
      return recordList
        .filter((r) => r.manifest && r.state === 'enabled')
        .map((r) => ({
          id: r.id,
          name: r.manifest!.name,
          icon: r.manifest!.icon ?? 'puzzle',
          hasRenderer: Boolean(r.manifest!.entry.renderer),
          rendererEntry: r.manifest!.entry.renderer ?? null,
        }));
    },

    /** Directory for an installed plugin id — used by the plugin:// protocol. */
    dirFor(id: string): string | null {
      const r = recordList.find((x) => x.id === id && x.manifest);
      return r ? r.dir : null;
    },
  };
}

export type PluginLoader = ReturnType<typeof createLoader>;
