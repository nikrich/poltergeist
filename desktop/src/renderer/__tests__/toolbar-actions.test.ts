import { describe, expect, it } from 'vitest';
import {
  LIST_ACTIONS,
  MARK_ACTIONS,
  TEXT_STYLES,
  applyLink,
  currentTextStyle,
  normalizeLinkHref,
  shortcutText,
  withShortcut,
  type ShortcutSpec,
} from '../lib/editor/toolbar-actions';
import { makeEditor, markdownOf, textPos } from './helpers/editor';

/** TipTap key name for a spec, as its keymaps declare it. */
const keyName = (s: ShortcutSpec): string =>
  ['Mod', ...(s.shift ? ['Shift'] : []), ...(s.alt ? ['Alt'] : []), s.key].join('-');

describe('shortcut labels', () => {
  it('use ⌘ on macOS and Ctrl elsewhere', () => {
    expect(shortcutText({ key: 'b' }, true)).toBe('⌘ B');
    expect(shortcutText({ key: 'b' }, false)).toBe('Ctrl B');
    expect(shortcutText({ key: 's', shift: true }, true)).toBe('⌘ ⇧ S');
    expect(shortcutText({ key: '2', alt: true }, true)).toBe('⌘ ⌥ 2');
    expect(shortcutText({ key: '2', alt: true }, false)).toBe('Ctrl Alt 2');
    expect(withShortcut('Bold', { key: 'b' }, false)).toBe('Bold (Ctrl B)');
    expect(withShortcut('Link', undefined, true)).toBe('Link');
  });
});

describe('every tooltip shortcut is one the editor really binds', () => {
  it.each([...MARK_ACTIONS, ...LIST_ACTIONS].map((a) => [a.id, a] as const))('%s', (_id, a) => {
    const editor = makeEditor('word');
    editor.commands.selectAll();
    editor.commands.keyboardShortcut(keyName(a.shortcut!));
    expect(a.isActive(editor)).toBe(true);
    editor.destroy();
  });

  it.each(TEXT_STYLES.map((s) => [s.id, s] as const))('%s', (id, s) => {
    const editor = makeEditor(id === 'paragraph' ? '# word' : 'word');
    editor.commands.keyboardShortcut(keyName(s.shortcut));
    expect(s.isActive(editor)).toBe(true);
    editor.destroy();
  });
});

describe('toolbar actions run their command', () => {
  it.each([
    ['bold', '**word**'],
    ['italic', '*word*'],
    ['strikethrough', '~~word~~'],
    ['code', '`word`'],
    ['bullet list', '- word'],
    ['numbered list', '1. word'],
    ['task list', '- [ ] word'],
  ])('%s', (id, md) => {
    const editor = makeEditor('word');
    editor.commands.selectAll();
    [...MARK_ACTIONS, ...LIST_ACTIONS].find((a) => a.id === id)!.run(editor);
    expect(markdownOf(editor)).toBe(md);
  });

  it('text styles set the block type', () => {
    const editor = makeEditor('word');
    TEXT_STYLES.find((s) => s.id === 'h2')!.run(editor);
    expect(markdownOf(editor)).toBe('## word');
    TEXT_STYLES.find((s) => s.id === 'paragraph')!.run(editor);
    expect(markdownOf(editor)).toBe('word');
  });
});

describe('text styles', () => {
  it('names the block under the cursor', () => {
    const cases: Array<[string, string]> = [
      ['# t', 'Heading 1'],
      ['### t', 'Heading 3'],
      ['#### t', 'Heading 4'],
      ['t', 'Normal text'],
    ];
    for (const [md, label] of cases) {
      const editor = makeEditor(md);
      expect(currentTextStyle(editor)).toBe(label);
      editor.destroy();
    }
  });
});

describe('normalizeLinkHref', () => {
  it.each([
    ['https://a.example/x', 'https://a.example/x'],
    ['HTTP://A.EXAMPLE', 'HTTP://A.EXAMPLE'],
    ['mailto:team@a.example', 'mailto:team@a.example'],
    ['example.com/path', 'https://example.com/path'],
    ['localhost:5173', 'https://localhost:5173'],
    ['  https://a.example  ', 'https://a.example'],
  ])('accepts %j', (raw, href) => {
    expect(normalizeLinkHref(raw)).toEqual({ ok: true, href });
  });

  it.each([
    ['javascript:alert(1)', 'Use an http, https or mailto link'],
    ['JavaScript:alert(1)', 'Use an http, https or mailto link'],
    ['data:text/html,x', 'Use an http, https or mailto link'],
    ['file:///etc/hosts', 'Use an http, https or mailto link'],
    ['', 'Enter a link'],
    ['   ', 'Enter a link'],
    ['a b', 'Links cannot contain spaces'],
  ])('refuses %j', (raw, error) => {
    expect(normalizeLinkHref(raw)).toEqual({ ok: false, error });
  });
});

describe('applyLink', () => {
  it('links the selection', () => {
    const editor = makeEditor('see docs');
    const from = textPos(editor, 'docs');
    editor.commands.setTextSelection({ from, to: from + 4 });
    applyLink(editor, 'https://a.example');
    expect(markdownOf(editor)).toBe('see [docs](https://a.example)');
  });

  it('inserts the address as a link with an empty selection', () => {
    const editor = makeEditor('see');
    editor.commands.focus('end');
    applyLink(editor, 'https://a.example');
    // Text equal to its href serialises as a GFM autolink.
    expect(markdownOf(editor)).toBe('see<https://a.example>');
    expect(editor.isActive('link', { href: 'https://a.example' })).toBe(true);
  });

  it('retargets the whole link under the cursor and removes it with null', () => {
    const editor = makeEditor('see [docs](https://old.example)');
    editor.commands.setTextSelection(textPos(editor, 'docs') + 2);
    applyLink(editor, 'https://new.example');
    expect(markdownOf(editor)).toBe('see [docs](https://new.example)');
    editor.commands.setTextSelection(textPos(editor, 'docs') + 2);
    applyLink(editor, null);
    expect(markdownOf(editor)).toBe('see docs');
  });
});
