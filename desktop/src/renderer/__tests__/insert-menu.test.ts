import { describe, expect, it, vi } from 'vitest';
import { insertEntries, runInsert } from '../lib/editor/insert-menu';
import { SLASH_ITEMS, type SlashItem } from '../lib/editor/slash';
import { onGb } from '../lib/editor/events';
import { makeEditor, markdownOf, textPos } from './helpers/editor';

const BASE = [
  'info', 'note', 'success', 'warning', 'error', 'tip', 'expand', 'status', 'toc', 'diagram',
  'image', 'photo', 'table', 'divider', 'code', 'quote',
];
const hasTemplate = SLASH_ITEMS.some((i) => i.key === 'template');

describe('insertEntries', () => {
  it('lists the A1 blocks, the new panels and media in Confluence order', () => {
    const keys = insertEntries({ canPickImage: true, canAssist: false }).map((e) => e.key);
    expect(keys).toEqual(hasTemplate ? [...BASE, 'template'] : BASE);
  });

  it('offers Template only when the template slash item exists (C1)', () => {
    const withTemplate: SlashItem[] = [...SLASH_ITEMS.filter((i) => i.key !== 'template'), { key: 'template', title: 'Template', run: () => {} }];
    expect(insertEntries({ slashItems: withTemplate, canPickImage: true, canAssist: false }).at(-1)).toMatchObject({ key: 'template', label: 'Template', kind: 'slash' });
    const without = SLASH_ITEMS.filter((i) => i.key !== 'template');
    expect(insertEntries({ slashItems: without, canPickImage: true, canAssist: false }).map((e) => e.key)).not.toContain('template');
  });

  it('skips a block whose slash item is missing, and Image without a picker', () => {
    const noDiagram = SLASH_ITEMS.filter((i) => i.key !== 'diagram');
    const keys = insertEntries({ slashItems: noDiagram, canPickImage: false, canAssist: false }).map((e) => e.key);
    expect(keys).not.toContain('diagram');
    expect(keys).not.toContain('image');
  });

  it('leads with Ask AI (visible without scrolling) only when an assist handler exists', () => {
    const entries = insertEntries({ canPickImage: true, canAssist: true });
    expect(entries[0]).toEqual({ key: 'assist', label: 'Ask AI', icon: 'sparkles', kind: 'assist' });
    expect(entries.filter((e) => e.kind === 'assist')).toHaveLength(1);
    expect(insertEntries({ canPickImage: true, canAssist: false }).map((e) => e.key)).not.toContain('assist');
  });

  it('inside a table cell, drops the block-only rows the slash menu also hides', () => {
    const keys = insertEntries({ canPickImage: true, canAssist: true, inTable: true }).map((e) => e.key);
    expect(keys).toEqual(['assist', 'status', 'image', 'photo', 'code', 'quote']);
  });
});

describe('runInsert', () => {
  it.each([
    ['success', '> [!success]'],
    ['error', '> [!error]'],
    ['info', '> [!info]'],
    ['toc', '```toc\n```'],
  ])('%s runs the A1 command at the cursor', (key, md) => {
    const editor = makeEditor('');
    expect(runInsert(editor, key)).toBe(true);
    expect(markdownOf(editor)).toBe(md);
    editor.destroy();
  });

  it('status opens the lozenge editor at the cursor', () => {
    const editor = makeEditor('');
    const spy = vi.fn();
    onGb(editor, 'gb:status:edit', spy);
    runInsert(editor, 'status');
    expect(markdownOf(editor)).toBe('`status:To do/grey`');
    expect(spy).toHaveBeenCalledWith({ pos: 1 });
    editor.destroy();
  });

  it('refuses unknown keys and read-only editors', () => {
    const editor = makeEditor('word', false);
    expect(runInsert(editor, 'nope')).toBe(false);
    expect(runInsert(editor, 'info')).toBe(false);
    expect(markdownOf(editor)).toBe('word');
    editor.destroy();
  });

  it('refuses block-only items inside a table cell but runs inline ones', () => {
    const table = '| a | b |\n| --- | --- |\n| alpha | 1 |';
    const editor = makeEditor(table);
    editor.commands.setTextSelection(textPos(editor, 'alpha'));
    for (const key of ['info', 'success', 'error', 'toc', 'diagram', 'table', 'divider', 'expand', 'template']) {
      expect(runInsert(editor, key)).toBe(false);
    }
    expect(markdownOf(editor)).toBe(table);
    expect(runInsert(editor, 'status')).toBe(true);
    expect(markdownOf(editor)).toContain('`status:To do/grey`alpha');
  });
});
