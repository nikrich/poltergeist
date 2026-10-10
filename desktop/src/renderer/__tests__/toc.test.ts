import { describe, it, expect } from 'vitest';
import { act, fireEvent } from '@testing-library/react';
import { collectHeadings } from '../lib/editor/toc';
import { makeEditor, markdownOf, textPos } from './helpers/editor';

const DOC = '```toc\n```\n\n# One\n\nbody\n\n## Two\n\n## \n\n### Three';

describe('collectHeadings', () => {
  it('lists non-empty headings with level and position', () => {
    const editor = makeEditor(DOC);
    const entries = collectHeadings(editor.state.doc);
    expect(entries.map((e) => [e.level, e.text])).toEqual([
      [1, 'One'],
      [2, 'Two'],
      [3, 'Three'],
    ]);
    expect(editor.state.doc.nodeAt(entries[1]!.pos)?.textContent).toBe('Two');
  });
});

describe('toc node', () => {
  it('parses only an EMPTY toc fence; a fence with options stays a code block', () => {
    expect(makeEditor('```toc\n```').getJSON().content?.[0]?.type).toBe('toc');
    expect(makeEditor('```toc\nstyle: number\n```').getJSON().content?.[0]?.type).toBe('codeBlock');
  });

  it('insertToc writes the empty fence', () => {
    const editor = makeEditor('');
    editor.commands.insertToc();
    expect(markdownOf(editor)).toBe('```toc\n```');
  });

  it('renders the live heading list and updates on edits', () => {
    const editor = makeEditor(DOC);
    const nav = editor.view.dom.querySelector('nav.gb-toc')!;
    const labels = () => Array.from(nav.querySelectorAll('button')).map((b) => b.textContent);
    expect(labels()).toEqual(['One', 'Two', 'Three']);
    act(() => {
      editor
        .chain()
        .insertContentAt(editor.state.doc.content.size, {
          type: 'heading',
          attrs: { level: 2 },
          content: [{ type: 'text', text: 'Four' }],
        })
        .run();
    });
    expect(labels()).toEqual(['One', 'Two', 'Three', 'Four']);
  });

  it('clicking an entry moves the selection into that heading', () => {
    const editor = makeEditor(DOC);
    const button = Array.from(editor.view.dom.querySelectorAll('nav.gb-toc button')).find(
      (b) => b.textContent === 'Two',
    )!;
    fireEvent.click(button);
    expect(editor.state.selection.from).toBe(textPos(editor, 'Two'));
  });

  it('shows a placeholder when there are no headings', () => {
    const editor = makeEditor('```toc\n```\n\nno headings');
    expect(editor.view.dom.querySelector('nav.gb-toc')?.textContent).toContain('no headings yet');
  });
});
