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

describe('inline ai shortcut (A5)', () => {
  const kj = (over: Partial<KeyLike>) => k('j', over);

  it('is ⌘J on macOS and Ctrl+J elsewhere, either letter case', () => {
    expect(matchesShortcut(kj({ metaKey: true }), 'inlineAi', true)).toBe(true);
    expect(matchesShortcut(k('J', { metaKey: true }), 'inlineAi', true)).toBe(true);
    expect(matchesShortcut(kj({ ctrlKey: true }), 'inlineAi', false)).toBe(true);
    expect(matchesShortcut(kj({ ctrlKey: true }), 'inlineAi', true)).toBe(false);
    expect(matchesShortcut(kj({ metaKey: true }), 'inlineAi', false)).toBe(false);
    expect(matchesShortcut(kj({}), 'inlineAi', true)).toBe(false);
  });

  it('never fires for the ⌥J jot overlay or ⌘⇧J', () => {
    expect(matchesShortcut(kj({ altKey: true }), 'inlineAi', true)).toBe(false);
    expect(matchesShortcut(kj({ metaKey: true, altKey: true }), 'inlineAi', true)).toBe(false);
    expect(matchesShortcut(kj({ ctrlKey: true, altKey: true }), 'inlineAi', false)).toBe(false);
    expect(matchesShortcut(kj({ metaKey: true, shiftKey: true }), 'inlineAi', true)).toBe(false);
    expect(matchesShortcut(k('J', { ctrlKey: true, shiftKey: true }), 'inlineAi', false)).toBe(false);
  });

  it('does not collide with focus mode, read-aloud or copy formatted', () => {
    expect(matchesShortcut(k('.', { metaKey: true }), 'inlineAi', true)).toBe(false);
    expect(matchesShortcut(k('L', { metaKey: true, shiftKey: true }), 'inlineAi', true)).toBe(false);
    expect(matchesShortcut(k('C', { metaKey: true, shiftKey: true }), 'inlineAi', true)).toBe(false);
    expect(matchesShortcut(kj({ metaKey: true }), 'focus', true)).toBe(false);
    expect(matchesShortcut(kj({ metaKey: true }), 'readAloud', true)).toBe(false);
  });

  it('labels per platform', () => {
    expect(shortcutLabel('inlineAi', true)).toBe('⌘ J');
    expect(shortcutLabel('inlineAi', false)).toBe('Ctrl J');
  });
});
