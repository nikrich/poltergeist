import { mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const KEY = /^[a-z0-9-]{1,120}$/;
const MAX_MESSAGES = 200;

function threadFile(dataDir, key) {
  if (!KEY.test(String(key))) throw new Error(`invalid thread key: ${JSON.stringify(key)}`);
  return join(dataDir, 'threads', `${key}.json`);
}

export function readThread(dataDir, key) {
  try {
    const v = JSON.parse(readFileSync(threadFile(dataDir, key), 'utf-8'));
    return Array.isArray(v) ? v : [];
  } catch (e) {
    if (e.code === 'ENOENT' || e instanceof SyntaxError) return [];
    throw e;
  }
}

export function writeThread(dataDir, { key, messages } = {}) {
  const file = threadFile(dataDir, key);
  if (!Array.isArray(messages)) throw new Error('thread messages must be an array');
  if (messages.length > MAX_MESSAGES) throw new Error(`a thread holds at most ${MAX_MESSAGES} messages`);
  for (const m of messages) {
    if (!m || (m.role !== 'user' && m.role !== 'assistant')) throw new Error('each message needs role user|assistant');
    if (typeof m.text !== 'string') throw new Error('each message needs a text string');
  }
  mkdirSync(join(dataDir, 'threads'), { recursive: true });
  const tmp = `${file}.tmp`;
  writeFileSync(tmp, JSON.stringify(messages));
  renameSync(tmp, file);
  return true;
}

export function clearThread(dataDir, key) {
  rmSync(threadFile(dataDir, key), { force: true });
  return true;
}
