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
