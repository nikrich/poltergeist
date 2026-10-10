import { describe, it, expect, vi } from 'vitest';
import { Editor } from '@tiptap/core';
import { filterSlashItems, SLASH_ITEMS } from '../lib/editor/slash';
import { buildEditorExtensions } from '../lib/editor/extensions';

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
