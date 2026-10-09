import { describe, expect, it } from 'vitest';
import { matchesShortcut, shortcutLabel, type KeyLike } from '../lib/editor-shortcuts';

const k = (key: string, mods: Partial<KeyLike> = {}): KeyLike => ({
  key,
  metaKey: false,
  ctrlKey: false,
  shiftKey: false,
  altKey: false,
  ...mods,
});

describe('editor shortcuts', () => {
  it('focus is ⌘. on macOS and Ctrl+. elsewhere', () => {
    expect(matchesShortcut(k('.', { metaKey: true }), 'focus', true)).toBe(true);
    expect(matchesShortcut(k('.', { ctrlKey: true }), 'focus', true)).toBe(false);
    expect(matchesShortcut(k('.', { ctrlKey: true }), 'focus', false)).toBe(true);
    expect(matchesShortcut(k('.', { metaKey: true }), 'focus', false)).toBe(false);
  });

  it('focus ignores shifted and alt variants', () => {
    expect(matchesShortcut(k('>', { metaKey: true, shiftKey: true }), 'focus', true)).toBe(false);
    expect(matchesShortcut(k('.', { metaKey: true, shiftKey: true }), 'focus', true)).toBe(false);
    expect(matchesShortcut(k('.', { metaKey: true, altKey: true }), 'focus', true)).toBe(false);
    expect(matchesShortcut(k('.'), 'focus', true)).toBe(false);
  });

  it('read aloud is ⌘⇧L / Ctrl+Shift+L in either letter case', () => {
    expect(matchesShortcut(k('L', { metaKey: true, shiftKey: true }), 'readAloud', true)).toBe(true);
    expect(matchesShortcut(k('l', { metaKey: true, shiftKey: true }), 'readAloud', true)).toBe(true);
    expect(matchesShortcut(k('L', { ctrlKey: true, shiftKey: true }), 'readAloud', false)).toBe(true);
    expect(matchesShortcut(k('l', { metaKey: true }), 'readAloud', true)).toBe(false);
    expect(matchesShortcut(k('L', { ctrlKey: true, shiftKey: true }), 'readAloud', true)).toBe(false);
  });

  it('labels per platform', () => {
    expect(shortcutLabel('focus', true)).toBe('⌘ .');
    expect(shortcutLabel('focus', false)).toBe('Ctrl .');
    expect(shortcutLabel('readAloud', true)).toBe('⌘ ⇧ L');
    expect(shortcutLabel('readAloud', false)).toBe('Ctrl ⇧ L');
  });
});
