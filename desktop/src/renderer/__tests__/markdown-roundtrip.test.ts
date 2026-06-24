import { describe, it, expect } from 'vitest';
import { Editor } from '@tiptap/core';
import { buildEditorExtensions } from '../lib/editor/extensions';
import { getMarkdown } from '../lib/editor/markdown';

/**
 * Feature gate (spec §Testing): representative markdown must survive
 * editor in→out byte-stable, modulo trailing whitespace.
 *
 * Fixtures are written in the editor's canonical CommonMark/GFM form. Two
 * known, accepted canonicalisations (CommonMark-equivalent, byte-different):
 *  - soft line breaks inside a paragraph collapse to spaces — multi-line
 *    blockquotes therefore use `>` paragraph separators;
 *  - tight lists stay tight, loose lists stay loose (TaskListTight in the
 *    extension stack keeps task lists tight; without it they'd serialise
 *    with blank lines between items).
 */
function roundTrip(md: string): string {
  const editor = new Editor({ extensions: buildEditorExtensions(), content: md });
  try {
    return getMarkdown(editor);
  } finally {
    editor.destroy();
  }
}

function normalize(md: string): string {
  return md
    .split('\n')
    .map((line) => line.replace(/\s+$/, ''))
    .join('\n')
    .replace(/\n+$/, '');
}

const FIXTURES: Record<string, string> = {
  headings: '# h1\n\n## h2\n\n### h3\n\nbody text',
  emphasis: '**bold** and *italic* and `inline code`',
  'nested bullet lists': '- top\n  - nested\n    - deeper\n- second top',
  'ordered list': '1. first\n2. second\n3. third',
  'task list with checkbox state': '- [ ] open item\n- [x] done item',
  'nested task list': '- [ ] parent\n  - [x] child',
  table: '| name | value |\n| --- | --- |\n| alpha | 1 |\n| beta | 2 |',
  'fenced code with language': '```python\ndef hello():\n    return "world"\n```',
  link: 'see [the docs](https://example.com/docs) for more',
  blockquote: '> quoted line one\n>\n> quoted line two',
  'extract callout':
    '> **Extracted from photo**\n>\n> Events flow Kinesis to handler.\n>\n> DLQ on failure.',
  'obsidian wikilinks': 'see [[20-contexts/sanlam/_profile]] and [[a/b|Title]]',
  'inline image': '![whiteboard](90-meta/assets/jots/2026/06/abc-1.jpg)',
  'image among paragraphs':
    'before the shot\n\n![photo](90-meta/assets/jots/2026/06/x-2.jpg)\n\nafter the shot',
  'mixed document':
    '# meeting notes\n\n' +
    'context for **the ascp wizard** and `route_event`:\n\n' +
    '- [ ] follow up with [the docs](https://example.com)\n- [x] shipped\n\n' +
    '```ts\nconst x = 1;\n```',
};

describe('markdown round-trip (serialize(deserialize(md)))', () => {
  for (const [name, fixture] of Object.entries(FIXTURES)) {
    it(`round-trips ${name}`, () => {
      expect(normalize(roundTrip(fixture))).toBe(normalize(fixture));
    });
  }
});

describe('extract-callout — tight backend form', () => {
  /**
   * The backend (Task 12) appends callouts as tight consecutive blockquote
   * lines with no blank-line separators between them:
   *
   *   > **Extracted from photo**
   *   > body line one
   *   > body line two
   *
   * After an editor round-trip the lines may reflow (soft line breaks collapse
   * to spaces inside a single paragraph), but:
   *  - the output must still be a blockquote (starts with `>`)
   *  - the sentinel must survive (`**Extracted from photo**`)
   *  - no body content may be silently dropped
   */
  it('tight callout survives round-trip with sentinel and body text intact', () => {
    const tight = '> **Extracted from photo**\n> body line one\n> body line two';
    const out = roundTrip(tight);

    // Must still be a blockquote
    expect(out.trimStart()).toMatch(/^>/);

    // Sentinel must survive
    expect(out).toContain('**Extracted from photo**');

    // Body content must not be lost (may be reflowed onto same paragraph)
    expect(out).toContain('body line one');
    expect(out).toContain('body line two');
  });
});
