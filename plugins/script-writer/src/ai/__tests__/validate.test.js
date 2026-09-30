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
});
