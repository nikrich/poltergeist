import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Editor } from '@tiptap/core';

// C2 query blocks run their query on mount; never let them reach the sidecar.
const { runVaultQuery, setNoteStatus } = vi.hoisted(() => ({
  runVaultQuery: vi.fn(() => new Promise(() => {})),
  setNoteStatus: vi.fn(),
}));
vi.mock('../lib/editor/query-api', () => ({ runVaultQuery, setNoteStatus }));

import {
  DEL_BLOCK_CLASS,
  DEL_CLASS,
  INS_CLASS,
  acceptAiSuggestion,
  attachAiSuggestion,
  clearAiSuggestion,
  getAiSuggestion,
  setAiSuggestionText,
  startAiSuggestion,
} from '../lib/editor/ai-suggestion';
import { makeEditor, markdownOf, textPos } from './helpers/editor';

const QUERY = '```query\ntype: action_item\nstatus: open\n```';
const WITH_QUERY = `alpha beta\n\n${QUERY}\n\nomega`;

let editor: Editor;
const onKey = vi.fn(() => true);

function setup(md: string): Editor {
  editor = makeEditor(md);
  attachAiSuggestion(editor, { onKey });
  return editor;
}

afterEach(() => {
  editor?.destroy();
  onKey.mockClear();
});

function range(text: string) {
  const from = textPos(editor, text);
  return { from, to: from + text.length };
}

function suggest(r: { from: number; to: number }, text: string, joinWithSpace = false) {
  startAiSuggestion(editor, r, { joinWithSpace });
  setAiSuggestionText(editor, text, 'ready');
}

function key(k: string, extra: KeyboardEventInit = {}): KeyboardEvent {
  const ev = new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...extra });
  editor.view.dom.dispatchEvent(ev);
  return ev;
}

describe('ai-suggestion plugin', () => {
  it('shows the deletion and the streamed insertion without touching the document', () => {
    setup('alpha beta gamma');
    const onUpdate = vi.fn();
    editor.on('update', onUpdate);
    startAiSuggestion(editor, range('beta'));
    setAiSuggestionText(editor, 'BETA **bold**', 'streaming');
    expect(markdownOf(editor)).toBe('alpha beta gamma');
    expect(onUpdate).not.toHaveBeenCalled();
    expect(editor.view.dom.querySelector(`.${DEL_CLASS}`)?.textContent).toBe('beta');
    const ins = editor.view.dom.querySelector(`.${INS_CLASS}`);
    expect(ins?.textContent).toBe('BETA bold');
    expect(ins?.querySelector('strong')?.textContent).toBe('bold');
  });

  it('shows a placeholder before the first token', () => {
    setup('alpha');
    startAiSuggestion(editor, { from: 6, to: 6 });
    expect(editor.view.dom.querySelector('[data-testid="ai-insertion"]')?.textContent).toBe('…');
  });

  it('accept replaces the range in one transaction that a single undo reverts', () => {
    setup('alpha beta gamma');
    const changes = vi.fn();
    editor.on('transaction', ({ transaction }) => {
      if (transaction.docChanged) changes();
    });
    suggest(range('beta'), 'BETA');
    expect(acceptAiSuggestion(editor)).toBe(true);
    expect(markdownOf(editor)).toBe('alpha BETA gamma');
    expect(changes).toHaveBeenCalledTimes(1);
    expect(getAiSuggestion(editor)).toBeNull();
    editor.commands.undo();
    expect(markdownOf(editor)).toBe('alpha beta gamma');
  });

  it('typing right after accept is its own undo step', () => {
    setup('alpha beta gamma');
    const r = range('beta');
    suggest(r, 'BETA');
    acceptAiSuggestion(editor);
    editor.view.dispatch(editor.state.tr.insertText('!', r.from + 4));
    expect(markdownOf(editor)).toBe('alpha BETA! gamma');
    editor.commands.undo();
    expect(markdownOf(editor)).toBe('alpha BETA gamma');
    editor.commands.undo();
    expect(markdownOf(editor)).toBe('alpha beta gamma');
  });

  it('blocks other document changes while a suggestion is shown', () => {
    setup('alpha beta');
    startAiSuggestion(editor, range('beta'));
    editor.view.dispatch(editor.state.tr.insertText('X', 1));
    expect(markdownOf(editor)).toBe('alpha beta');
    clearAiSuggestion(editor);
    editor.view.dispatch(editor.state.tr.insertText('X', 1));
    expect(markdownOf(editor)).toBe('Xalpha beta');
  });

  it('refuses to accept while still streaming', () => {
    setup('alpha beta');
    startAiSuggestion(editor, range('beta'));
    setAiSuggestionText(editor, 'BETA', 'streaming');
    expect(acceptAiSuggestion(editor)).toBe(false);
    expect(getAiSuggestion(editor)?.status).toBe('streaming');
    expect(markdownOf(editor)).toBe('alpha beta');
  });

  it('accept with an identical or empty result changes nothing and reports false', () => {
    setup('alpha beta');
    suggest(range('beta'), 'beta');
    expect(acceptAiSuggestion(editor)).toBe(false);
    expect(getAiSuggestion(editor)).toBeNull();
    suggest(range('beta'), '   ');
    expect(acceptAiSuggestion(editor)).toBe(false);
    expect(markdownOf(editor)).toBe('alpha beta');
  });

  it('replaces text inside a callout body and keeps the callout', () => {
    setup('> [!info] Heads up\n> old text here');
    suggest(range('old'), 'new **bold**');
    acceptAiSuggestion(editor);
    expect(markdownOf(editor)).toBe('> [!info] Heads up\n> new **bold** text here');
  });

  it('flattens a multi-paragraph answer inside a table cell so the table survives', () => {
    setup('| a | b |\n| --- | --- |\n| one | two |');
    suggest(range('one'), 'first\n\n- second');
    acceptAiSuggestion(editor);
    expect(markdownOf(editor)).toBe('| a | b |\n| --- | --- |\n| first second | two |');
  });

  it('keeps the cell a single paragraph with its marks, as it will be saved', () => {
    setup('| a | b |\n| --- | --- |\n| one | two |');
    suggest(range('one'), '**first**\n\n- second');
    acceptAiSuggestion(editor);
    const cell = editor.state.doc.resolve(textPos(editor, 'first')).node(-1);
    expect(cell.childCount).toBe(1);
    expect(cell.firstChild?.textContent).toBe('first second');
    expect(markdownOf(editor)).toBe('| a | b |\n| --- | --- |\n| **first** second | two |');
  });

  it('previews a multi-block answer in a table cell exactly as accept will write it', () => {
    setup('| a | b |\n| --- | --- |\n| one | two |');
    suggest(range('one'), '**first**\n\n- second');
    const ins = editor.view.dom.querySelector(`.${INS_CLASS}`);
    expect(ins?.textContent).toBe('first second');
    expect(ins?.querySelector('strong')?.textContent).toBe('first');
    expect(ins?.querySelector('p, ul, li, h1, h2')).toBeNull();
  });

  it('an answer that parses to nothing deletes nothing and reports false', () => {
    setup('alpha beta');
    suggest(range('beta'), '[a]: http://x');
    expect(acceptAiSuggestion(editor)).toBe(false);
    expect(getAiSuggestion(editor)).toBeNull();
    expect(markdownOf(editor)).toBe('alpha beta');
  });

  it('continues after a status lozenge without touching it, adding a joining space', () => {
    setup('Build is `status:In progress/yellow` today');
    const end = editor.state.doc.content.size - 1;
    suggest({ from: end, to: end }, 'and tomorrow.', true);
    expect(editor.view.dom.querySelector(`.${INS_CLASS}`)?.textContent).toBe(' and tomorrow.');
    acceptAiSuggestion(editor);
    expect(markdownOf(editor)).toBe('Build is `status:In progress/yellow` today and tomorrow.');
  });

  it('adds no joining space before punctuation', () => {
    setup('alpha');
    suggest({ from: 6, to: 6 }, ', then beta', true);
    acceptAiSuggestion(editor);
    expect(markdownOf(editor)).toBe('alpha, then beta');
  });

  it('drops a multi-block answer into an empty paragraph without leaving a blank line', () => {
    setup('intro');
    editor.view.dispatch(
      editor.state.tr.insert(editor.state.doc.content.size, editor.schema.nodes.paragraph!.create()),
    );
    const pos = editor.state.doc.content.size - 1;
    suggest({ from: pos, to: pos }, '## Risks\n\n- vendor delay');
    acceptAiSuggestion(editor);
    expect(markdownOf(editor)).toBe('intro\n\n## Risks\n\n- vendor delay');
  });

  it('marks whole blocks inside the deleted range', () => {
    setup('a\n\n> [!info] T\n> body\n\nb');
    // From inside the first paragraph to inside the last one (the callout sits between).
    suggest({ from: 1, to: editor.state.doc.content.size - 1 }, 'merged');
    expect(editor.view.dom.querySelectorAll(`.${DEL_BLOCK_CLASS}`).length).toBeGreaterThan(0);
    acceptAiSuggestion(editor);
    expect(markdownOf(editor)).toBe('merged');
  });

  it('accepting next to a C2 query block leaves its fence byte-identical', () => {
    setup(WITH_QUERY);
    suggest(range('beta'), 'BETA **bold**');
    expect(markdownOf(editor)).toBe(WITH_QUERY);
    expect(acceptAiSuggestion(editor)).toBe(true);
    expect(markdownOf(editor)).toBe(`alpha BETA **bold**\n\n${QUERY}\n\nomega`);
  });

  it('a range covering a query block removes it as one whole block', () => {
    setup(WITH_QUERY);
    suggest({ from: 1, to: editor.state.doc.content.size - 1 }, 'merged');
    expect(editor.view.dom.querySelectorAll(`.${DEL_BLOCK_CLASS}`).length).toBeGreaterThan(0);
    acceptAiSuggestion(editor);
    expect(markdownOf(editor)).toBe('merged');
  });

  it('a range ending inside a query source takes the whole block, never splicing it', () => {
    setup(WITH_QUERY);
    const from = textPos(editor, 'beta');
    suggest({ from, to: textPos(editor, 'action_item') }, 'merged');
    expect(editor.view.dom.querySelector(`.gb-query.${DEL_BLOCK_CLASS}, .${DEL_BLOCK_CLASS} .gb-query`)).not.toBeNull();
    acceptAiSuggestion(editor);
    expect(markdownOf(editor)).toBe('alpha merged\n\nomega');
  });

  it('a range starting inside a query source takes the whole block, never splicing it', () => {
    setup(WITH_QUERY);
    suggest({ from: textPos(editor, 'open'), to: textPos(editor, 'omega') + 'omega'.length }, 'merged');
    acceptAiSuggestion(editor);
    expect(markdownOf(editor)).toBe('alpha beta\n\nmerged');
  });

  it('a range inside one query source edits the source and keeps the fence', () => {
    setup(WITH_QUERY);
    suggest(range('open'), 'done');
    acceptAiSuggestion(editor);
    expect(markdownOf(editor)).toBe(WITH_QUERY.replace('status: open', 'status: done'));
  });

  it('Tab inside a list accepts instead of indenting; Esc rejects', () => {
    setup('- one\n- two');
    const r = range('two');
    editor.commands.setTextSelection(r.from);
    startAiSuggestion(editor, r);
    setAiSuggestionText(editor, 'TWO', 'streaming');
    const early = key('Tab');
    expect(early.defaultPrevented).toBe(true);
    expect(onKey).not.toHaveBeenCalled();
    setAiSuggestionText(editor, 'TWO', 'ready');
    key('Tab');
    expect(onKey).toHaveBeenLastCalledWith('accept');
    key('Enter', { metaKey: true });
    key('Enter', { ctrlKey: true });
    expect(onKey).toHaveBeenCalledTimes(3);
    const esc = key('Escape');
    expect(onKey).toHaveBeenLastCalledWith('reject');
    expect(esc.defaultPrevented).toBe(true);
    expect(markdownOf(editor)).toBe('- one\n- two');
  });

  it('leaves keys alone when no suggestion is shown', () => {
    setup('alpha');
    const esc = key('Escape');
    expect(onKey).not.toHaveBeenCalled();
    expect(esc.defaultPrevented).toBe(false);
  });

  it('detach removes the plugin and its decorations', () => {
    editor = makeEditor('alpha beta');
    const detach = attachAiSuggestion(editor, { onKey });
    startAiSuggestion(editor, range('beta'));
    detach();
    expect(getAiSuggestion(editor)).toBeNull();
    expect(editor.view.dom.querySelector(`.${DEL_CLASS}`)).toBeNull();
  });
});
