import { isMac } from './platform';

/** Editor-scope shortcuts: A4 (focus mode, read-aloud) and A5 (inline AI).
 *
 * Collision check (2026-10-09): ⌘⇧C copy-formatted, ⌘K Today search, ⌘,
 * settings, ⌥J jot overlay, the ⌘⇧K/C/R/S/V/G labels in lib/shortcuts.ts,
 * Tiptap StarterKit/TaskList keymaps (Mod-B/I/E/Z/Y, Mod-Shift-S/7/8/9,
 * Mod-Alt-0…6/C, Mod-Enter). No binding below collides with any of them
 * or with another. */
export type EditorShortcut = 'focus' | 'readAloud' | 'inlineAi';

export type KeyLike = Pick<KeyboardEvent, 'key' | 'metaKey' | 'ctrlKey' | 'shiftKey' | 'altKey'>;

const SPEC: Record<EditorShortcut, { key: string; shift: boolean; glyph: string }> = {
  focus: { key: '.', shift: false, glyph: '.' },
  readAloud: { key: 'l', shift: true, glyph: 'L' },
  inlineAi: { key: 'j', shift: false, glyph: 'J' },
};

/** Mod = ⌘ on macOS, Ctrl elsewhere; the other modifier must be up so
 * Ctrl+. on a Mac (or Win+. on Windows) never triggers it. */
export function matchesShortcut(e: KeyLike, which: EditorShortcut, mac: boolean): boolean {
  const s = SPEC[which];
  if (e.key.toLowerCase() !== s.key || e.shiftKey !== s.shift || e.altKey) return false;
  return mac ? e.metaKey && !e.ctrlKey : e.ctrlKey && !e.metaKey;
}

export function shortcutLabel(which: EditorShortcut, mac = isMac): string {
  const s = SPEC[which];
  return [mac ? '⌘' : 'Ctrl', ...(s.shift ? ['⇧'] : []), s.glyph].join(' ');
}
