import { afterEach, describe, expect, it } from 'vitest';
import type { Editor } from '@tiptap/core';
import { rangeMarkdown } from '../lib/editor/markdown';
import { makeEditor, normalizeMd, textPos } from './helpers/editor';

let editor: Editor;
afterEach(() => editor?.destroy());

describe('rangeMarkdown', () => {
  it('serialises a range inside a paragraph with its marks', () => {
    editor = makeEditor('# Title\n\nalpha **bold** beta');
    const from = textPos(editor, 'alpha');
    const to = textPos(editor, 'beta') + 'beta'.length;
    expect(normalizeMd(rangeMarkdown(editor, from, to))).toBe('alpha **bold** beta');
  });

  it('serialises everything before a position', () => {
    editor = makeEditor('# Title\n\nalpha beta');
    const to = textPos(editor, 'beta');
    expect(normalizeMd(rangeMarkdown(editor, 0, to))).toBe('# Title\n\nalpha');
  });

  it('keeps wikilinks unescaped and returns empty for an empty range', () => {
    editor = makeEditor('see [[20-contexts/work/plan|Plan]] now');
    const from = textPos(editor, 'see');
    expect(normalizeMd(rangeMarkdown(editor, from, editor.state.doc.content.size))).toBe(
      'see [[20-contexts/work/plan|Plan]] now',
    );
    expect(rangeMarkdown(editor, from, from)).toBe('');
  });
});
