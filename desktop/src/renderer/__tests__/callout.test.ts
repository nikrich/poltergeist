import { describe, it, expect } from 'vitest';
import {
  parseCalloutHeader,
  calloutHeader,
  sanitizeCalloutTitle,
} from '../lib/editor/callout-format';
import { makeEditor, markdownOf } from './helpers/editor';

describe('parseCalloutHeader', () => {
  it('parses kind, fold marker and title', () => {
    expect(parseCalloutHeader('[!info] Heads up')).toEqual({ kind: 'info', foldable: 'none', title: 'Heads up' });
    expect(parseCalloutHeader('[!note]- Details')).toEqual({ kind: 'note', foldable: 'closed', title: 'Details' });
    expect(parseCalloutHeader('[!tip]+')).toEqual({ kind: 'tip', foldable: 'open', title: null });
    expect(parseCalloutHeader('[!success]')).toEqual({ kind: 'success', foldable: 'none', title: null });
  });

  it('keeps the title raw (markdown characters are not interpreted)', () => {
    expect(parseCalloutHeader('[!info] Use *raw* `title`')?.title).toBe('Use *raw* `title`');
  });

  it('rejects unknown, upper-case and unspaced markers', () => {
    expect(parseCalloutHeader('[!quote] x')).toBeNull();
    expect(parseCalloutHeader('[!INFO] x')).toBeNull();
    expect(parseCalloutHeader('[!info]x')).toBeNull();
    expect(parseCalloutHeader('**Extracted from photo**')).toBeNull();
  });
});

describe('calloutHeader', () => {
  it('prints the canonical header', () => {
    expect(calloutHeader({ kind: 'info', title: 'Heads up', foldable: 'none' })).toBe('[!info] Heads up');
    expect(calloutHeader({ kind: 'note', title: 'Details', foldable: 'closed' })).toBe('[!note]- Details');
    expect(calloutHeader({ kind: 'tip', title: null, foldable: 'open' })).toBe('[!tip]+');
  });
});

describe('sanitizeCalloutTitle', () => {
  it('collapses whitespace and maps blank to null', () => {
    expect(sanitizeCalloutTitle('  a \n b  ')).toBe('a b');
    expect(sanitizeCalloutTitle('   ')).toBeNull();
  });
});

describe('callout node parsing', () => {
  it('turns a marked blockquote into a callout node with attrs and body', () => {
    const editor = makeEditor('> [!warning] Careful\n> First para.\n>\n> Second para.');
    const first = editor.getJSON().content?.[0];
    expect(first).toMatchObject({ type: 'callout', attrs: { kind: 'warning', title: 'Careful', foldable: 'none' } });
    expect(first?.content?.map((c) => c.type)).toEqual(['paragraph', 'paragraph']);
    expect(JSON.stringify(first)).not.toContain('[!warning]');
  });

  it('keeps unknown and upper-case markers as plain blockquotes', () => {
    for (const md of ['> [!quote] Not ours\n> body', '> [!INFO] shout\n> body', '> **Extracted from photo**\n>\n> body']) {
      expect(makeEditor(md).getJSON().content?.[0]?.type).toBe('blockquote');
    }
  });

  it('gives a title-only callout an empty body paragraph', () => {
    const first = makeEditor('> [!success] Shipped').getJSON().content?.[0];
    expect(first).toMatchObject({ type: 'callout', attrs: { kind: 'success', title: 'Shipped' } });
    expect(first?.content).toEqual([{ type: 'paragraph' }]);
  });

  it('does not stack the core rule when the same parser runs twice', () => {
    const md = '> [!info] T\n> [!tip] literal body';
    const editor = makeEditor(md);
    editor.commands.setContent(md, false); // second parse through the same markdown-it instance
    const first = editor.getJSON().content?.[0];
    expect(first).toMatchObject({ type: 'callout', attrs: { kind: 'info', title: 'T' } });
    expect(JSON.stringify(first?.content)).toContain('[!tip] literal body');
  });

  it('normalises a blank > line after the header to the tight form, then stays stable', () => {
    const editor = makeEditor('> [!info] T\n>\n> para');
    expect(markdownOf(editor)).toBe('> [!info] T\n> para');
    editor.commands.setContent(markdownOf(editor), false);
    expect(markdownOf(editor)).toBe('> [!info] T\n> para');
  });
});

describe('callout header separation', () => {
  it('keeps a callout whose first body block is a divider a callout after save + reopen', () => {
    const editor = makeEditor('');
    editor.commands.setContent(
      {
        type: 'doc',
        content: [
          {
            type: 'callout',
            attrs: { kind: 'info', title: 'T', foldable: 'none' },
            content: [{ type: 'horizontalRule' }, { type: 'paragraph', content: [{ type: 'text', text: 'x' }] }],
          },
        ],
      },
      false,
    );
    const md = markdownOf(editor);
    expect(md).toBe('> [!info] T\n>\n> ---\n>\n> x');
    const first = makeEditor(md).getJSON().content?.[0];
    expect(first).toMatchObject({ type: 'callout', attrs: { kind: 'info', title: 'T' } });
    expect(first?.content?.map((c) => c.type)).toEqual(['horizontalRule', 'paragraph']);
  });
});

describe('callout commands', () => {
  it('setCallout wraps the current paragraph; unsetCallout lifts it back', () => {
    const editor = makeEditor('hello');
    editor.commands.setTextSelection(2);
    expect(editor.commands.setCallout({ kind: 'tip' })).toBe(true);
    expect(markdownOf(editor)).toBe('> [!tip]\n> hello');
    editor.commands.unsetCallout();
    expect(markdownOf(editor)).toBe('hello');
  });
});
