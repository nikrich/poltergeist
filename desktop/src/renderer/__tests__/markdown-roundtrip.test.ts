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
  'obsidian wikilinks': 'see [[20-contexts/work/_profile]] and [[a/b|Title]]',
  'person link': 'met [[30-cross-context/people/alex|@Alex]] today',
  hashtags: '#roadmap at line start and a #mid-tag inline',
  'bare wikilink in a table cell': '| who | link |\n| --- | --- |\n| a | [[20-contexts/work/b]] |',
  'inline image': '![whiteboard](90-meta/assets/jots/2026/06/abc-1.jpg)',
  'image among paragraphs':
    'before the shot\n\n![photo](90-meta/assets/jots/2026/06/x-2.jpg)\n\nafter the shot',
  'mixed document':
    '# meeting notes\n\n' +
    'context for **the helix wizard** and `route_event`:\n\n' +
    '- [ ] follow up with [the docs](https://example.com)\n- [x] shipped\n\n' +
    '```ts\nconst x = 1;\n```',
  'callout with title': '> [!info] Heads up\n> Body text here.',
  'callout without title': '> [!tip]\n> Use the slash menu.',
  'callout with several paragraphs': '> [!warning] Careful\n> First para.\n>\n> Second para.',
  'callout title only': '> [!success] Shipped',
  'callout with a list body': '> [!error] Failures\n> - one\n> - two',
  'callout raw title keeps markdown characters': '> [!note] Use *raw* title\n> body',
  'foldable callout starts collapsed': '> [!note]- Details\n> Hidden body.',
  'foldable callout starts open': '> [!note]+ Details\n> Shown body.',
  'callout between paragraphs': 'before\n\n> [!info] Mid\n> body\n\nafter',
  'callout starting with divider': '> [!info] T\n>\n> ---\n>\n> after',
  'callout starting with ordered list from 2': '> [!note] Steps\n>\n> 2. second\n> 3. third',
  'callout starting with a line of equals': '> [!tip] T\n>\n> ===\n>\n> after',
  'callout starting with an empty list item': '> [!warning] T\n>\n> -\n> - next',
  'status lozenge': 'Build is `status:In progress/yellow` today',
  'status without colour': 'State: `status:Blocked`',
  'status-like code with unknown colour': 'see `status:a/orange` here',
  'status label with backtick': 'odd ``status:a`b/red`` label',
  'empty status label stays inline code': 'not a lozenge: `status:`',
  'status inside bold': '**`status:Done/green`**',
  'table of contents': '```toc\n```',
  'toc among headings': '# Title\n\n```toc\n```\n\n## Section\n\nbody',
  'live query block':
    '```query\ntype: action_item\nmentions: "[[30-cross-context/people/alex]]"\nstatus: open\nsort: created desc\n```',
  'toc fence with plugin options stays code': '```toc\nstyle: number\n```',
  'toc inside a callout': '> [!info] T\n> ```toc\n> ```\n\nafter',
  'toc inside a list item': '- item\n\n  ```toc\n  ```\n\n- next',
  'mermaid diagram': '```mermaid\nflowchart TD\n  A[Start] --> B{Ok?}\n  B -->|yes| C\n```',
  'mermaid inside callout': '> [!note] Flow\n> ```mermaid\n> flowchart TD\n>   A --> B\n> ```\n\nafter',
  'image with width': '![whiteboard|480](90-meta/assets/jots/2026/06/abc-1.jpg)',
  'image with width and no alt': '![|320](90-meta/assets/jots/2026/06/abc-2.jpg)',
  'image alt with a non-width pipe': '![a|b](90-meta/assets/jots/2026/06/abc-3.jpg)',
  'image with width inside callout': '> [!info] T\n> ![a|240](90-meta/assets/x.jpg)',
  'table with column alignment': '| left | centre | right |\n| :--- | :---: | ---: |\n| a | b | c |',
  'headerless table (empty header row)': '|  |  |\n| --- | --- |\n| a | b |\n| c | d |',
  'table cell with escaped pipe': '| a \\| b | c |\n| --- | --- |\n| 1 | 2 |',
  'table cell with inline marks': '| **bold** | `code` |\n| --- | --- |\n| [x](https://e.com) | *it* |',
  'table inside callout': '> [!info] T\n> | a | b |\n> | --- | --- |\n> | 1 | 2 |',
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
