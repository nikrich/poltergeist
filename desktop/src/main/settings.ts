import { app } from 'electron';
import { existsSync, readFileSync, writeFileSync, renameSync, mkdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { join, dirname } from 'node:path';
import type { Settings } from '../shared/types';

const SCHEMA_VERSION = 1;

interface OnDisk extends Settings {
  version: number;
}

const defaults: Settings = {
  theme: 'dark',
  density: 'comfortable',
  vaultPath: join(homedir(), 'ghostbrain', 'vault'),

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

function configPath(): string {
  return join(app.getPath('userData'), 'config.json');
}

function read(): Settings {
  const path = configPath();
  if (!existsSync(path)) return { ...defaults };
  try {
    const raw = readFileSync(path, 'utf-8');
    const parsed = JSON.parse(raw) as Partial<OnDisk>;
    if (parsed.version !== SCHEMA_VERSION) return { ...defaults };
    return { ...defaults, ...parsed };
  } catch {
    return { ...defaults };
  }
}

function writeAtomic(value: Settings): void {
  const path = configPath();
  mkdirSync(dirname(path), { recursive: true });
  const tmp = path + '.tmp';
  const payload: OnDisk = { ...value, version: SCHEMA_VERSION };
  writeFileSync(tmp, JSON.stringify(payload, null, 2), 'utf-8');
  renameSync(tmp, path);
}

let cache: Settings | null = null;

export function getAll(): Settings {
  if (cache === null) cache = read();
  return { ...cache };
}

export function setKey<K extends keyof Settings>(key: K, value: Settings[K]): void {
  if (cache === null) cache = read();
  cache = { ...cache, [key]: value };
  writeAtomic(cache);
}
