import { mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const KEY = /^[a-z0-9-]{1,120}$/;

function draftFile(dataDir, key) {
  if (!KEY.test(String(key))) throw new Error(`invalid draft key: ${JSON.stringify(key)}`);
  return join(dataDir, 'drafts', `${key}.json`);
}

export function writeDraft(dataDir, { key, content, savedAt }) {
  const file = draftFile(dataDir, key);
  if (typeof content !== 'string') throw new Error('draft content must be a string');
  mkdirSync(join(dataDir, 'drafts'), { recursive: true });
  const tmp = `${file}.tmp`;
  writeFileSync(tmp, JSON.stringify({ content, savedAt: String(savedAt ?? '') }));
  renameSync(tmp, file);
  return true;
}

export function readDraft(dataDir, key) {
  const file = draftFile(dataDir, key);
  try {
    return JSON.parse(readFileSync(file, 'utf-8'));
  } catch (e) {
    if (e.code === 'ENOENT' || e instanceof SyntaxError) return null;
    throw e;
  }
}

export function clearDraft(dataDir, key) {
  rmSync(draftFile(dataDir, key), { force: true });
  return true;
}
