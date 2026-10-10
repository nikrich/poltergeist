import { describe, expect, it } from 'vitest';
import type { Editor } from '@tiptap/core';
import {
  BEFORE_CAP,
  buildInlineRequest,
  captureInlineContext,
  cleanModelOutput,
  joinWithSpaceFor,
  LANGUAGES,
  newStreamId,
  QUICK_ACTIONS,
  suggestionRange,
  type InlineContext,
} from '../lib/editor/inline-assist';
import { makeEditor, normalizeMd, textPos } from './helpers/editor';

// Source: STREAM_ID_RE in main/docs-stream.ts (the renderer tsconfig project
// can't import from src/main).
const STREAM_ID_RE = /^[A-Za-z0-9][A-Za-z0-9:_-]{0,79}$/;

// helpers/editor destroys every editor makeEditor created after each test.
let editor: Editor;

const SEL: InlineContext = { from: 7, to: 11, empty: false, selection: 'beta', before: 'alpha beta', charBefore: 'a' };
const CURSOR: InlineContext = { from: 11, to: 11, empty: true, selection: '', before: 'alpha beta', charBefore: 'a' };

describe('captureInlineContext', () => {
  it('captures the selection markdown, the text before it and the char before', () => {
    editor = makeEditor('alpha **beta** gamma');
    const from = textPos(editor, 'beta');
    editor.commands.setTextSelection({ from, to: from + 4 });
    const ctx = captureInlineContext(editor);
    expect(ctx.empty).toBe(false);
    expect(ctx.from).toBe(from);
    expect(ctx.to).toBe(from + 4);
    expect(normalizeMd(ctx.selection)).toBe('**beta**');
    expect(normalizeMd(ctx.before)).toBe('alpha **beta**');
    expect(ctx.charBefore).toBe('a');
  });

  it('caps the text before the cursor at 8k characters', () => {
    editor = makeEditor('x'.repeat(9000) + ' end');
    editor.commands.setTextSelection(editor.state.doc.content.size - 1);
    const ctx = captureInlineContext(editor);
    expect(ctx.before.length).toBeLessThanOrEqual(BEFORE_CAP);
    expect(ctx.before.length).toBeGreaterThan(BEFORE_CAP - 3);
    expect(ctx.before.trimEnd().endsWith(' end')).toBe(true);
    expect(ctx.selection).toBe('');
  });

  it('charBefore is empty at the very start of the document', () => {
    editor = makeEditor('hello');
    editor.commands.setTextSelection(1);
    const ctx = captureInlineContext(editor);
    expect(ctx.empty).toBe(true);
    expect(ctx.charBefore).toBe('');
  });
});

describe('buildInlineRequest', () => {
  const target = { path: '20-contexts/work/plan.md' };

  it('continue inserts at the cursor with the text before it, even over a selection', () => {
    expect(buildInlineRequest(target, { mode: 'continue' }, SEL, 'inline-1')).toEqual({
      path: '20-contexts/work/plan.md', stream_id: 'inline-1', mode: 'continue',
      placement: 'cursor', before: 'alpha beta',
    });
  });

  it('selection actions replace the selection', () => {
    expect(buildInlineRequest({ jot_id: 'j1' }, { mode: 'polish', instruction: '  shorter  ' }, SEL, 's')).toEqual({
      jot_id: 'j1', stream_id: 's', mode: 'polish', instruction: 'shorter',
      placement: 'selection', selection: 'beta',
    });
  });

  it('a blank instruction is dropped', () => {
    expect(buildInlineRequest({ jot_id: 'j1' }, { mode: 'polish', instruction: '   ' }, SEL, 's')).not.toHaveProperty(
      'instruction',
    );
  });

  it('translate carries the language and the selection', () => {
    expect(buildInlineRequest(target, { mode: 'translate', targetLanguage: 'Afrikaans' }, SEL, 's')).toMatchObject({
      mode: 'translate', target_language: 'Afrikaans', placement: 'selection', selection: 'beta',
    });
  });

  it('a draft without a selection inserts at the cursor', () => {
    expect(buildInlineRequest(target, { mode: 'draft', instruction: 'risks' }, CURSOR, 's')).toEqual({
      path: '20-contexts/work/plan.md', stream_id: 's', mode: 'draft', instruction: 'risks',
      placement: 'cursor', before: 'alpha beta',
    });
  });
});

describe('suggestionRange and joinWithSpaceFor', () => {
  it('continue and cursor inserts are empty ranges at the end of the selection', () => {
    expect(suggestionRange({ mode: 'continue' }, SEL)).toEqual({ from: 11, to: 11 });
    expect(suggestionRange({ mode: 'draft' }, CURSOR)).toEqual({ from: 11, to: 11 });
    expect(suggestionRange({ mode: 'polish' }, SEL)).toEqual({ from: 7, to: 11 });
  });

  it('joins with a space only when inserting straight after a non-space', () => {
    expect(joinWithSpaceFor({ mode: 'continue' }, SEL)).toBe(true);
    expect(joinWithSpaceFor({ mode: 'continue' }, { ...CURSOR, charBefore: ' ' })).toBe(false);
    expect(joinWithSpaceFor({ mode: 'continue' }, { ...CURSOR, charBefore: '' })).toBe(false);
    expect(joinWithSpaceFor({ mode: 'polish' }, SEL)).toBe(false);
  });
});

describe('cleanModelOutput', () => {
  it('unwraps a whole-answer markdown fence, finished or still streaming', () => {
    expect(cleanModelOutput('```markdown\nhello\n```')).toBe('hello');
    expect(cleanModelOutput('```md\nhel')).toBe('hel');
    expect(cleanModelOutput('```markdown\r\nhello\r\n```\r\n')).toBe('hello');
  });

  it('keeps real code fences and trims blank edges', () => {
    expect(cleanModelOutput('```mermaid\nflowchart TD\n  A --> B\n```')).toBe('```mermaid\nflowchart TD\n  A --> B\n```');
    expect(cleanModelOutput('```\ncode\n```')).toBe('```\ncode\n```');
    expect(cleanModelOutput('\n\n  hi there  \n\n')).toBe('  hi there');
    expect(cleanModelOutput('   \n')).toBe('');
    expect(cleanModelOutput('')).toBe('');
  });

  it('an empty fence of any kind is no answer, not an empty code block', () => {
    expect(cleanModelOutput('```markdown\n```')).toBe('');
    expect(cleanModelOutput('```md\n\n```\n')).toBe('');
    expect(cleanModelOutput('```\n```')).toBe('');
    expect(cleanModelOutput('  ```\n  \n```  ')).toBe('');
    expect(cleanModelOutput('```python\n```')).toBe('');
    expect(cleanModelOutput('```markdown')).toBe('');
  });

  it('a fenced echo of the selection cleans to the selection itself', () => {
    expect(cleanModelOutput('```markdown\n**beta**\n```')).toBe('**beta**');
    expect(cleanModelOutput('\n**beta**\n')).toBe('**beta**');
  });
});

describe('quick actions and languages', () => {
  it('lists the spec quick actions in lower case; only continue works without a selection', () => {
    expect(QUICK_ACTIONS.map((a) => a.mode)).toEqual(['continue', 'polish', 'expand', 'summarize']);
    expect(QUICK_ACTIONS.every((a) => a.label === a.label.toLowerCase())).toBe(true);
    expect(QUICK_ACTIONS.filter((a) => !a.needsSelection).map((a) => a.mode)).toEqual(['continue']);
  });

  it('offers English and Afrikaans', () => {
    expect(LANGUAGES.map((l) => l.name)).toEqual(['English', 'Afrikaans']);
  });
});

describe('newStreamId', () => {
  it('is unique and passes the sidecar pattern', () => {
    const a = newStreamId();
    const b = newStreamId();
    expect(a).not.toBe(b);
    expect(a).toMatch(STREAM_ID_RE);
    expect(a.startsWith('inline-')).toBe(true);
  });
});
