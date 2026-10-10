import { describe, it, expect, vi } from 'vitest';
import { Editor } from '@tiptap/core';
import { filterSlashItems, SLASH_ITEMS } from '../lib/editor/slash';
import { buildEditorExtensions } from '../lib/editor/extensions';
import { onGb } from '../lib/editor/events';
import { makeEditor, markdownOf } from './helpers/editor';

describe('filterSlashItems', () => {
  it('returns all items for empty query', () => {
    expect(filterSlashItems('')).toHaveLength(SLASH_ITEMS.length);
  });
  it('filters by title prefix, case-insensitive', () => {
    const r = filterSlashItems('head');
    expect(r.every((i) => i.title.toLowerCase().includes('head'))).toBe(true);
    expect(r.length).toBeGreaterThan(0);
  });
  it('matches the photo command on "photo"', () => {
    expect(filterSlashItems('photo').map((i) => i.key)).toContain('photo');
  });
});

describe('template slash command', () => {
  it('matches on "templ"', () => {
    expect(filterSlashItems('templ').map((i) => i.key)).toEqual(['template']);
  });

  it('clears the slash range and emits gb:slash:template', () => {
    // Plain markdown content: tiptap-markdown (html: false) would read '<p>…</p>' as literal text.
    const editor = new Editor({ extensions: buildEditorExtensions(), content: '/templ' });
    const spy = vi.fn();
    editor.on('gb:slash:template' as Parameters<typeof editor.on>[0], spy);
    SLASH_ITEMS.find((i) => i.key === 'template')!.run(editor, { from: 1, to: 7 });
    expect(spy).toHaveBeenCalledTimes(1);
    expect(editor.getText()).toBe('');
    editor.destroy();
  });
});

function runSlash(key: string) {
  const editor = makeEditor('/');
  const item = SLASH_ITEMS.find((i) => i.key === key);
  if (!item) throw new Error(`no slash item ${key}`);
  item.run(editor, { from: 1, to: 2 });
  return editor;
}

describe('A1 slash items', () => {
  it('lists the new block items and keeps Quote', () => {
    const keys = SLASH_ITEMS.map((i) => i.key);
    for (const k of ['info', 'note', 'tip', 'warning', 'expand', 'status', 'toc', 'diagram', 'quote']) {
      expect(keys).toContain(k);
    }
    expect(filterSlashItems('panel').map((i) => i.key)).toEqual(['info', 'note', 'tip', 'warning']);
    expect(filterSlashItems('contents').map((i) => i.key)).toEqual(['toc']);
  });

  it.each([
    ['info', '> [!info]'],
    ['note', '> [!note]'],
    ['tip', '> [!tip]'],
    ['warning', '> [!warning]'],
    ['expand', '> [!note]+ Details'],
    ['toc', '```toc\n```'],
    ['diagram', '```mermaid\nflowchart TD\n  A[Start] --> B[End]\n```'],
  ])('%s inserts its markdown form', (key, expected) => {
    expect(markdownOf(runSlash(key))).toBe(expected);
  });

  it('status inserts a grey To do lozenge and opens the editor for it', () => {
    const editor = makeEditor('/');
    const spy = vi.fn();
    onGb(editor, 'gb:status:edit', spy);
    SLASH_ITEMS.find((i) => i.key === 'status')!.run(editor, { from: 1, to: 2 });
    expect(markdownOf(editor)).toBe('`status:To do/grey`');
    expect(spy).toHaveBeenCalledWith({ pos: 1 });
  });
});
