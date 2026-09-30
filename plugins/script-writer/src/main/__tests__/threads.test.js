import { mkdtempSync, mkdirSync, readdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { clearThread, readThread, writeThread } from '../threads.js';

const dir = () => mkdtempSync(join(tmpdir(), 'sw-threads-'));
const M = [{ role: 'user', text: 'Who is Mara?' }, { role: 'assistant', text: 'Mara is 40 [1].', sources: [{ n: 1, path: 'a.md', title: 'Bio', snippet: 's' }] }];

describe('threads', () => {
  it('round-trips, clears, and leaves no tmp file', () => {
    const d = dir();
    expect(readThread(d, 'k')).toEqual([]);
    writeThread(d, { key: 'k', messages: M });
    expect(readThread(d, 'k')).toEqual(M);
    expect(readdirSync(join(d, 'threads'))).toEqual(['k.json']);
    clearThread(d, 'k');
    expect(readThread(d, 'k')).toEqual([]);
  });
  it('validates key, shape and size', () => {
    const d = dir();
    expect(() => writeThread(d, { key: '../x', messages: [] })).toThrow(/invalid thread key/);
    expect(() => writeThread(d, { key: 'k', messages: 'no' })).toThrow(/array/);
    expect(() => writeThread(d, { key: 'k', messages: [{ role: 'system', text: 'x' }] })).toThrow(/role/);
    expect(() => writeThread(d, { key: 'k', messages: Array.from({ length: 201 }, () => ({ role: 'user', text: 'x' })) })).toThrow(/200/);
  });
  it('treats a corrupt thread as empty', () => {
    const d = dir();
    mkdirSync(join(d, 'threads'));
    writeFileSync(join(d, 'threads', 'bad.json'), '{nope');
    expect(readThread(d, 'bad')).toEqual([]);
  });
});
