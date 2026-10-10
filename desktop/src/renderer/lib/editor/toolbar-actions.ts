import type { Editor } from '@tiptap/core';
import { isMac } from '../platform';

/** A TipTap keymap entry: Mod (+Shift)(+Alt) + key. Mod = ⌘ / Ctrl. */
export interface ShortcutSpec {
  key: string;
  shift?: boolean;
  alt?: boolean;
}

/** Same style as A4's shortcutLabel: '⌘ ⇧ S', 'Ctrl Alt 2'. */
export function shortcutText(s: ShortcutSpec, mac = isMac): string {
  const parts = [mac ? '⌘' : 'Ctrl'];
  if (s.shift) parts.push('⇧');
  if (s.alt) parts.push(mac ? '⌥' : 'Alt');
  parts.push(s.key.toUpperCase());
  return parts.join(' ');
}

export function withShortcut(label: string, s?: ShortcutSpec, mac = isMac): string {
  return s ? `${label} (${shortcutText(s, mac)})` : label;
}

export interface ToolbarAction {
  /** aria-label (lowercase, stable for tests). */
  id: string;
  /** Tooltip text. */
  label: string;
  icon: string;
  /** The keymap StarterKit / TaskList already binds — never a new binding. */
  shortcut?: ShortcutSpec;
  run: (editor: Editor) => void;
  isActive: (editor: Editor) => boolean;
}

export const MARK_ACTIONS: ToolbarAction[] = [
  { id: 'bold', label: 'Bold', icon: 'bold', shortcut: { key: 'b' }, run: (e) => e.chain().focus().toggleBold().run(), isActive: (e) => e.isActive('bold') },
  { id: 'italic', label: 'Italic', icon: 'italic', shortcut: { key: 'i' }, run: (e) => e.chain().focus().toggleItalic().run(), isActive: (e) => e.isActive('italic') },
  { id: 'strikethrough', label: 'Strikethrough', icon: 'strikethrough', shortcut: { key: 's', shift: true }, run: (e) => e.chain().focus().toggleStrike().run(), isActive: (e) => e.isActive('strike') },
  { id: 'code', label: 'Inline code', icon: 'code', shortcut: { key: 'e' }, run: (e) => e.chain().focus().toggleCode().run(), isActive: (e) => e.isActive('code') },
];

export const LIST_ACTIONS: ToolbarAction[] = [
  { id: 'bullet list', label: 'Bullet list', icon: 'list', shortcut: { key: '8', shift: true }, run: (e) => e.chain().focus().toggleBulletList().run(), isActive: (e) => e.isActive('bulletList') },
  { id: 'numbered list', label: 'Numbered list', icon: 'list-ordered', shortcut: { key: '7', shift: true }, run: (e) => e.chain().focus().toggleOrderedList().run(), isActive: (e) => e.isActive('orderedList') },
  { id: 'task list', label: 'Task list', icon: 'list-checks', shortcut: { key: '9', shift: true }, run: (e) => e.chain().focus().toggleTaskList().run(), isActive: (e) => e.isActive('taskList') },
];

export interface TextStyle {
  id: 'paragraph' | 'h1' | 'h2' | 'h3';
  label: string;
  shortcut: ShortcutSpec;
  run: (editor: Editor) => void;
  isActive: (editor: Editor) => boolean;
}

export const TEXT_STYLES: TextStyle[] = [
  { id: 'paragraph', label: 'Normal text', shortcut: { key: '0', alt: true }, run: (e) => e.chain().focus().setParagraph().run(), isActive: (e) => e.isActive('paragraph') },
  { id: 'h1', label: 'Heading 1', shortcut: { key: '1', alt: true }, run: (e) => e.chain().focus().setHeading({ level: 1 }).run(), isActive: (e) => e.isActive('heading', { level: 1 }) },
  { id: 'h2', label: 'Heading 2', shortcut: { key: '2', alt: true }, run: (e) => e.chain().focus().setHeading({ level: 2 }).run(), isActive: (e) => e.isActive('heading', { level: 2 }) },
  { id: 'h3', label: 'Heading 3', shortcut: { key: '3', alt: true }, run: (e) => e.chain().focus().setHeading({ level: 3 }).run(), isActive: (e) => e.isActive('heading', { level: 3 }) },
];

/** The text-style dropdown's label for the block under the cursor. */
export function currentTextStyle(editor: Editor): string {
  const hit = TEXT_STYLES.find((s) => s.isActive(editor));
  if (hit) return hit.label;
  for (const level of [4, 5, 6] as const) {
    if (editor.isActive('heading', { level })) return `Heading ${level}`;
  }
  return 'Normal text';
}

const SAFE_SCHEME = /^(?:https?:|mailto:)/i;
const ANY_SCHEME = /^[a-z][a-z0-9+.-]*:/i;
/** 'localhost:5173' looks like a scheme but is a host and port. */
const HOST_PORT = /^[\w.-]+:\d+(?:[/?#]|$)/;

/** http(s) and mailto only; a bare host gets https://. Never javascript:, file:, data:. */
export function normalizeLinkHref(
  raw: string,
): { ok: true; href: string } | { ok: false; error: string } {
  const v = raw.trim();
  if (v === '') return { ok: false, error: 'Enter a link' };
  if (/\s/.test(v)) return { ok: false, error: 'Links cannot contain spaces' };
  if (SAFE_SCHEME.test(v)) return { ok: true, href: v };
  if (ANY_SCHEME.test(v) && !HOST_PORT.test(v)) {
    return { ok: false, error: 'Use an http, https or mailto link' };
  }
  return { ok: true, href: `https://${v}` };
}

/** href null removes the link around the cursor/selection. With nothing
 * selected and no link under the cursor, the address itself is inserted. */
export function applyLink(editor: Editor, href: string | null): void {
  if (href === null) {
    editor.chain().focus().extendMarkRange('link').unsetLink().run();
    return;
  }
  if (editor.state.selection.empty && !editor.isActive('link')) {
    editor
      .chain()
      .focus()
      .insertContent({ type: 'text', text: href, marks: [{ type: 'link', attrs: { href } }] })
      .run();
    return;
  }
  editor.chain().focus().extendMarkRange('link').setLink({ href }).run();
}
