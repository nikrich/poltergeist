import { describe, it, expect } from 'vitest';
import { delimiterFor, escapeTablePipes, normalizeAlign } from '../lib/editor/table';
import { findNodePos, makeEditor, markdownOf, textPos } from './helpers/editor';

const BASIC = '| name | value |\n| --- | --- |\n| alpha | 1 |\n| beta | 2 |';

describe('table helpers', () => {
  it('normalizeAlign accepts css/html values only', () => {
    expect(normalizeAlign('right')).toBe('right');
    expect(normalizeAlign('CENTER')).toBe('center');
    expect(normalizeAlign('justify')).toBeNull();
    expect(normalizeAlign('')).toBeNull();
  });
  it('delimiterFor prints GFM alignment', () => {
    expect([null, 'left', 'center', 'right'].map((a) => delimiterFor(a as never))).toEqual([
      '---',
      ':---',
      ':---:',
      '---:',
    ]);
  });
  it('escapeTablePipes escapes bare pipes only', () => {
    expect(escapeTablePipes('a | b')).toBe('a \\| b');
    expect(escapeTablePipes('a \\| b')).toBe('a \\| b');
    expect(escapeTablePipes('||')).toBe('\\|\\|');
  });
});

describe('table serialisation', () => {
  it('parses alignment from the delimiter row into cell attrs', () => {
    const editor = makeEditor('| a | b |\n| :---: | ---: |\n| 1 | 2 |');
    const json = JSON.stringify(editor.getJSON());
    expect(json).toContain('"align":"center"');
    expect(json).toContain('"align":"right"');
  });

  it('setColumnAlign aligns the whole column', () => {
    const editor = makeEditor(BASIC);
    editor.commands.setTextSelection(textPos(editor, 'alpha'));
    editor.commands.setColumnAlign('right');
    expect(markdownOf(editor)).toBe('| name | value |\n| ---: | --- |\n| alpha | 1 |\n| beta | 2 |');
    editor.commands.setColumnAlign(null);
    expect(markdownOf(editor)).toBe(BASIC);
  });

  it('headerless table: toggling the header row off writes an empty GFM header and round-trips', () => {
    const editor = makeEditor(BASIC);
    editor.commands.setTextSelection(textPos(editor, 'name'));
    editor.commands.toggleHeaderRow();
    const md = markdownOf(editor);
    expect(md).toBe('|  |  |\n| --- | --- |\n| name | value |\n| alpha | 1 |\n| beta | 2 |');
    const again = makeEditor(md);
    expect(markdownOf(again)).toBe(md);
    expect(JSON.stringify(again.getJSON())).not.toContain('tableHeader');
  });

  it('never writes the [table] placeholder for a multi-paragraph cell', () => {
    const editor = makeEditor('');
    editor.commands.setContent(
      {
        type: 'doc',
        content: [
          {
            type: 'table',
            content: [
              { type: 'tableRow', content: [
                { type: 'tableHeader', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'h' }] }] },
              ] },
              { type: 'tableRow', content: [
                { type: 'tableCell', content: [
                  { type: 'paragraph', content: [{ type: 'text', text: 'one' }] },
                  { type: 'paragraph', content: [{ type: 'text', text: 'two' }] },
                ] },
              ] },
            ],
          },
        ],
      },
      false,
    );
    const md = markdownOf(editor);
    expect(md).not.toContain('[table]');
    expect(md).toBe('| h |\n| --- |\n| one two |');
  });

  it('a header-only table with empty headers is not stripped', () => {
    const editor = makeEditor('|  |  |\n| --- | --- |');
    expect(JSON.stringify(editor.getJSON())).toContain('tableHeader');
  });
});

/** Every row of a GFM table must split into the same number of cells on unescaped pipes. */
function columnCounts(md: string): number[] {
  return md.split('\n').map((line) => line.replace(/\\\|/g, '').split('|').length - 2);
}

describe('table pipe safety', () => {
  it('a status lozenge whose label contains a pipe keeps the column count', () => {
    const editor = makeEditor('| a | b |\n| --- | --- |\n| `status:x/green` | 2 |');
    const pos = findNodePos(editor, (n) => n.type.name === 'status');
    editor.commands.updateStatusAt(pos, { label: 'on | off' });
    const md = markdownOf(editor);
    expect(md).toBe('| a | b |\n| --- | --- |\n| `status:on \\| off/green` | 2 |');
    expect(columnCounts(md)).toEqual([2, 2, 2]);
    const again = makeEditor(md);
    expect(markdownOf(again)).toBe(md);
    const status = again.state.doc.nodeAt(findNodePos(again, (n) => n.type.name === 'status'));
    expect(status?.attrs).toMatchObject({ label: 'on | off', color: 'green' });
  });

  it('inline code containing a pipe stays inside its cell', () => {
    const md = '| a | b |\n| --- | --- |\n| `x \\| y` | 2 |';
    const editor = makeEditor(md);
    expect(JSON.stringify(editor.getJSON())).toContain('"text":"x | y"');
    expect(markdownOf(editor)).toBe(md);
    expect(columnCounts(markdownOf(editor))).toEqual([2, 2, 2]);
  });

  it('a block image inside a cell is written as markdown, not dropped', () => {
    const editor = makeEditor('');
    editor.commands.setContent(
      {
        type: 'doc',
        content: [
          {
            type: 'table',
            content: [
              { type: 'tableRow', content: [
                { type: 'tableHeader', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'pic' }] }] },
                { type: 'tableHeader', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'n' }] }] },
              ] },
              { type: 'tableRow', content: [
                { type: 'tableCell', content: [
                  { type: 'paragraph', content: [{ type: 'text', text: 'see' }] },
                  { type: 'image', attrs: { src: '90-meta/assets/x.jpg', alt: 'a', width: 240 } },
                ] },
                { type: 'tableCell', content: [{ type: 'paragraph', content: [{ type: 'text', text: '1' }] }] },
              ] },
            ],
          },
        ],
      },
      false,
    );
    const md = markdownOf(editor);
    expect(md).toBe('| pic | n |\n| --- | --- |\n| see ![a\\|240](90-meta/assets/x.jpg) | 1 |');
    expect(columnCounts(md)).toEqual([2, 2, 2]);
  });

  it('a wikilink alias in a cell keeps its escaped pipe', () => {
    const md = '| a | b |\n| --- | --- |\n| [[note\\|alias]] | 2 |';
    const editor = makeEditor(md);
    expect(markdownOf(editor)).toBe(md);
    expect(columnCounts(markdownOf(editor))).toEqual([2, 2, 2]);
  });

  it('a hard break inside a cell is written as a space, never [hardBreak]', () => {
    const editor = makeEditor('');
    editor.commands.setContent(
      {
        type: 'doc',
        content: [
          {
            type: 'table',
            content: [
              { type: 'tableRow', content: [
                { type: 'tableHeader', content: [{ type: 'paragraph', content: [{ type: 'text', text: 'h' }] }] },
              ] },
              { type: 'tableRow', content: [
                { type: 'tableCell', content: [
                  { type: 'paragraph', content: [
                    { type: 'text', text: 'a' },
                    { type: 'hardBreak' },
                    { type: 'text', text: 'b' },
                  ] },
                ] },
              ] },
            ],
          },
        ],
      },
      false,
    );
    const md = markdownOf(editor);
    expect(md).not.toContain('[hardBreak]');
    expect(md).toBe('| h |\n| --- |\n| a b |');
  });
});
