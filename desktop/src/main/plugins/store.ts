import { app } from 'electron';
import { existsSync, readFileSync, writeFileSync, renameSync, mkdirSync } from 'node:fs';
import { join, dirname } from 'node:path';

// Plugin enabled-state and per-plugin settings. Deliberately NOT in the app
// settings store: gb:settings:set validates against a closed zod shape, while
// plugin data is dynamic per plugin id. Same atomic-write pattern as
// src/main/settings.ts.

const SCHEMA_VERSION = 1;

interface OnDisk {
  version: number;
  enabled: Record<string, boolean>;
  data: Record<string, Record<string, unknown>>;
}

const defaults: OnDisk = { version: SCHEMA_VERSION, enabled: {}, data: {} };

let overriddenPath: string | null = null;

function storePath(): string {
  return overriddenPath ?? join(app.getPath('userData'), 'plugins.json');
}

function read(): OnDisk {
  const path = storePath();
  if (!existsSync(path)) return structuredClone(defaults);
  try {
    const parsed = JSON.parse(readFileSync(path, 'utf-8')) as Partial<OnDisk>;
    if (parsed.version !== SCHEMA_VERSION) return structuredClone(defaults);
    return {
      version: SCHEMA_VERSION,
      enabled: parsed.enabled ?? {},
      data: parsed.data ?? {},
    };
  } catch {
    return structuredClone(defaults);
  }
}

function writeAtomic(value: OnDisk): void {
  const path = storePath();
  mkdirSync(dirname(path), { recursive: true });
  const tmp = path + '.tmp';
  writeFileSync(tmp, JSON.stringify(value, null, 2), 'utf-8');
  renameSync(tmp, path);
}

let cache: OnDisk | null = null;

function state(): OnDisk {
  if (cache === null) cache = read();
  return cache;
}

export function isEnabled(id: string): boolean {
  return state().enabled[id] === true;
}

export function setEnabled(id: string, on: boolean): void {
  const s = state();
  cache = { ...s, enabled: { ...s.enabled, [id]: on } };
  writeAtomic(cache);
}

export function getData(id: string, key: string): unknown {
  return state().data[id]?.[key];
}

export function setData(id: string, key: string, value: unknown): void {
  const s = state();
  cache = {
    ...s,
    data: { ...s.data, [id]: { ...(s.data[id] ?? {}), [key]: value } },
  };
  writeAtomic(cache);
}

/** Uninstall: drop the enabled flag; plugin data intentionally survives. */
export function forget(id: string): void {
  const s = state();
  const enabled = { ...s.enabled };
  delete enabled[id];
  cache = { ...s, enabled };
  writeAtomic(cache);
}

export function _resetForTest(): void {
  cache = null;
}

export function _setPathForTest(p: string): void {
  overriddenPath = p;
  cache = null;
}
