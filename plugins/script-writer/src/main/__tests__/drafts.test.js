import { mkdtempSync, writeFileSync, mkdirSync, readdirSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { clearDraft, readDraft, writeDraft } from '../drafts.js';

const dir = () => mkdtempSync(join(tmpdir(), 'sw-drafts-'));

describe('drafts', () => {
  it('writes, reads and clears a draft', () => {
    const d = dir();
    expect(readDraft(d, 'a-b')).toBeNull();
    writeDraft(d, { key: 'a-b', content: 'FADE IN:', savedAt: 'T' });
    expect(readDraft(d, 'a-b')).toEqual({ content: 'FADE IN:', savedAt: 'T' });
    clearDraft(d, 'a-b');
    expect(readDraft(d, 'a-b')).toBeNull();
  });
  it('rejects unsafe keys and non-string content', () => {
    const d = dir();
    expect(() => writeDraft(d, { key: '../etc', content: 'x' })).toThrow(/invalid draft key/);
    expect(() => writeDraft(d, { key: 'ok', content: 5 })).toThrow(/content/);
  });
  it('treats a corrupt draft as absent', () => {
    const d = dir();
    mkdirSync(join(d, 'drafts'));
    writeFileSync(join(d, 'drafts', 'bad.json'), '{nope');
    expect(readDraft(d, 'bad')).toBeNull();
  });
  it('leaves no .tmp file after a write', () => {
    const d = dir();
    writeDraft(d, { key: 'k', content: 'x', savedAt: 'T' });
    expect(readdirSync(join(d, 'drafts'))).toEqual(['k.json']);
  });
});
