import { describe, expect, it } from 'vitest';
import { checkFountain, stripFences } from '../validate.js';

const SCENE = 'INT. A - DAY\n\nMara waits.\n\nMARA\nNow?\n\nJOE\nNot yet.\n\nShe sits.';

describe('validate', () => {
  it('strips code fences and CRLF', () => {
    expect(stripFences('```fountain\r\nINT. A - DAY\r\n```')).toBe('INT. A - DAY');
  });
  it('accepts sound Fountain', () => {
    expect(checkFountain(SCENE, SCENE.replace('waits', 'paces'))).toEqual({ ok: true, text: SCENE.replace('waits', 'paces') });
  });
  it('rejects empty, element-less, over-shortened and heading-less results', () => {
    expect(checkFountain(SCENE, '   ')).toMatchObject({ ok: false, reason: 'empty result' });
    expect(checkFountain(SCENE, '[[just a note]]')).toMatchObject({ ok: false, reason: 'no screenplay elements' });
    expect(checkFountain(SCENE, 'INT. A - DAY\n\nMara waits.')).toMatchObject({ ok: false });
    expect(checkFountain(SCENE, 'Mara waits.\n\nMARA\nNow?\n\nJOE\nNot yet.\n\nShe sits.', { keepHeading: true })).toMatchObject({ ok: false, reason: 'scene heading removed' });
  });
  it('allows shortening when minKeep is 0', () => {
    expect(checkFountain(SCENE, 'INT. A - DAY\n\nMara waits.', { minKeep: 0 }).ok).toBe(true);
  });
  it('extracts content from first fenced block if fences exist', () => {
    expect(stripFences('Here you go:\n```fountain\nINT. A - DAY\n\nHi.\n```\nHope that helps')).toBe('INT. A - DAY\n\nHi.');
    expect(stripFences('```\nINT. A - DAY\n```')).toBe('INT. A - DAY');
  });
  it('rejects assistant chatter instead of screenplay text', () => {
    expect(checkFountain(SCENE, 'Sure: INT. A - DAY')).toMatchObject({ ok: false, reason: 'assistant chatter instead of screenplay text' });
    expect(checkFountain(SCENE, "Here's: INT. A - DAY")).toMatchObject({ ok: false, reason: 'assistant chatter instead of screenplay text' });
    expect(checkFountain(SCENE, 'Okay: INT. A - DAY')).toMatchObject({ ok: false, reason: 'assistant chatter instead of screenplay text' });
  });
  it('rejects prose-only when requireStructure is true and original has structure', () => {
    expect(checkFountain(SCENE, 'Mara waits.', { requireStructure: true })).toMatchObject({ ok: false, reason: 'lost its screenplay structure' });
  });
  it('accepts prose-only with requireStructure false and minKeep 0', () => {
    expect(checkFountain(SCENE, 'Mara waits.', { requireStructure: false, minKeep: 0 }).ok).toBe(true);
  });
  it('accepts preamble plus fenced scene, extracting inner text', () => {
    expect(checkFountain(SCENE, 'Here is the scene:\n```fountain\nINT. A - DAY\n\nMara waits.\n```').ok).toBe(true);
  });
});
