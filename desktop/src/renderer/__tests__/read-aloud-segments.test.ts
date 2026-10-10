import { describe, expect, it } from 'vitest';
import { Editor } from '@tiptap/core';
import type { Node as PMNode } from '@tiptap/pm/model';
import { buildEditorExtensions } from '../lib/editor/extensions';
import {
  collectSegments,
  speakable,
  startIndexFor,
} from '../lib/read-aloud/segments';
import { detectLanguage } from '../lib/read-aloud/language';

function docOf(markdown: string): PMNode {
  const editor = new Editor({ extensions: buildEditorExtensions(), content: markdown });
  const doc = editor.state.doc;
  editor.destroy();
  return doc;
}

function posOf(doc: PMNode, needle: string): number {
  let found = -1;
  doc.descendants((node, pos) => {
    if (found !== -1) return false;
    if (node.isText) {
      const i = node.text!.indexOf(needle);
      if (i !== -1) found = pos + i;
    }
    return true;
  });
  if (found === -1) throw new Error(`not found: ${needle}`);
  return found;
}

const texts = (doc: PMNode, range?: { from: number; to: number }) =>
  collectSegments(doc, range).map((s) => s.text);

describe('collectSegments', () => {
  it('reads rendered text sentence by sentence, never markdown syntax', () => {
    expect(texts(docOf('# Title\n\nSome **bold** text. Second sentence!'))).toEqual([
      'Title',
      'Some bold text.',
      'Second sentence!',
    ]);
  });

  it('skips fenced code blocks, including mermaid', () => {
    const doc = docOf('Before.\n\n```js\nconst x = 1;\n```\n\n```mermaid\nflowchart TD\n```\n\nAfter.');
    expect(texts(doc)).toEqual(['Before.', 'After.']);
  });

  it('reads list items and table cells', () => {
    const doc = docOf('- first item\n- second item\n\n| a | b |\n| --- | --- |\n| one | two |');
    expect(texts(doc)).toEqual(['first item', 'second item', 'a', 'b', 'one', 'two']);
  });

  it('skips punctuation-only paragraphs', () => {
    expect(texts(docOf('Hello.\n\n— …'))).toEqual(['Hello.']);
  });

  it('maps each sentence to its exact doc range', () => {
    const doc = docOf('One. Two.');
    const segs = collectSegments(doc);
    expect(segs).toHaveLength(2);
    expect(doc.textBetween(segs[0]!.from, segs[0]!.to)).toBe('One.');
    expect(doc.textBetween(segs[1]!.from, segs[1]!.to)).toBe('Two.');
  });

  it('keeps positions aligned across a hard break', () => {
    const doc = docOf('Line one  \nline two.');
    const segs = collectSegments(doc);
    expect(segs.map((s) => s.text)).toEqual(['Line one line two.']);
    expect(segs[0]!.to - segs[0]!.from).toBe('Line one line two.'.length);
    expect(doc.textBetween(segs[0]!.to - 4, segs[0]!.to)).toBe('two.');
  });

  it('a selection reads only the selected part', () => {
    const doc = docOf('Alpha one. Beta two. Gamma three.');
    const from = posOf(doc, 'Beta');
    expect(texts(doc, { from, to: posOf(doc, 'two.') + 4 })).toEqual(['Beta two.']);
    expect(texts(doc, { from: posOf(doc, 'two'), to: posOf(doc, 'two.') + 4 })).toEqual(['two.']);
  });

  it('a selection spanning paragraphs clips both ends', () => {
    const doc = docOf('First para ends here.\n\nSecond para starts now.');
    const range = { from: posOf(doc, 'ends'), to: posOf(doc, 'para starts') + 4 };
    expect(texts(doc, range)).toEqual(['ends here.', 'Second para']);
  });
});

describe('speakable', () => {
  it('turns wikilinks into their alias or note name', () => {
    expect(speakable('See [[20-contexts/work/notes/plan|the plan]] now')).toBe('See the plan now');
    expect(speakable('Ask [[30-cross-context/people/alex|@Alex]]')).toBe('Ask Alex');
    expect(speakable('Open [[20-contexts/work/notes/roadmap.md]]')).toBe('Open roadmap');
  });

  it('reads tags as words and urls as "link"', () => {
    expect(speakable('Filed under #project/alpha and #todo.')).toBe(
      'Filed under project alpha and todo.',
    );
    expect(speakable('Docs at https://example.com/a?b=c today')).toBe('Docs at link today');
  });

  it('leaves a C# style hash inside a word alone', () => {
    expect(speakable('We use C# here')).toBe('We use C# here');
  });
});

describe('startIndexFor', () => {
  const doc = docOf('Alpha one. Beta two. Gamma three.');
  const segs = collectSegments(doc);

  it('starts at the sentence containing the cursor', () => {
    expect(startIndexFor(segs, posOf(doc, 'two'))).toBe(1);
    expect(startIndexFor(segs, posOf(doc, 'Alpha'))).toBe(0);
  });

  it('starts from the top when the cursor is past the last sentence', () => {
    expect(startIndexFor(segs, doc.content.size)).toBe(0);
  });
});

describe('detectLanguage', () => {
  it('recognises Afrikaans', () => {
    expect(detectLanguage('Ek het die vergadering bygewoon en ons sal more weer praat.')).toBe('af');
  });

  it('recognises English', () => {
    expect(detectLanguage('The team agreed that the release is ready for the review.')).toBe('en');
  });

  it('returns null for short or mixed text', () => {
    expect(detectLanguage('ok')).toBeNull();
    expect(detectLanguage('die the en and ek with')).toBeNull();
  });
});
