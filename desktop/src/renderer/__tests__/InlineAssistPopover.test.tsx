import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type React from 'react';
import type { Editor } from '@tiptap/core';
import { InlineAssistPopover } from '../components/InlineAssistPopover';
import { attachAiSuggestion, getAiSuggestion, INS_CLASS, type SuggestionKey } from '../lib/editor/ai-suggestion';
import { captureInlineContext } from '../lib/editor/inline-assist';
import type { DocsAssistEvent, DocsAssistRequest } from '../../shared/api-types';
import { makeEditor, markdownOf, textPos } from './helpers/editor';

type Payload = { key?: string; jotId: string; event: DocsAssistEvent };
let listener: ((p: Payload) => void) | null;
let assist: ReturnType<typeof vi.fn>;
let assistStop: ReturnType<typeof vi.fn>;
let editor: Editor;
const keyRef = { current: null } as React.MutableRefObject<((k: SuggestionKey) => boolean) | null>;

beforeEach(() => {
  listener = null;
  assist = vi.fn().mockResolvedValue({ ok: true });
  assistStop = vi.fn().mockResolvedValue({ ok: true });
  window.gb = {
    ...window.gb,
    docs: { ...window.gb.docs, assist, assistStop },
    on: ((channel: string, l: (p: Payload) => void) => {
      if (channel === 'docs:event') listener = l;
      return () => {
        if (listener === l) listener = null;
      };
    }) as typeof window.gb.on,
  };
  editor = makeEditor('alpha beta gamma');
  attachAiSuggestion(editor, { onKey: (k) => keyRef.current?.(k) ?? false });
});

afterEach(() => editor.destroy());

function lastRequest(): DocsAssistRequest {
  return assist.mock.calls[assist.mock.calls.length - 1]![0] as DocsAssistRequest;
}

function fire(event: DocsAssistEvent, key = lastRequest().stream_id!) {
  act(() => listener?.({ key, jotId: key, event }));
}

function selectText(text: string) {
  const from = textPos(editor, text);
  editor.commands.setTextSelection({ from, to: from + text.length });
}

function open(props: Partial<React.ComponentProps<typeof InlineAssistPopover>> = {}) {
  const onAccept = vi.fn();
  const onClose = vi.fn();
  const utils = render(
    <InlineAssistPopover
      editor={editor}
      target={{ path: '20-contexts/work/plan.md' }}
      context={captureInlineContext(editor)}
      keyRef={keyRef}
      onAccept={onAccept}
      onClose={onClose}
      {...props}
    />,
  );
  return { ...utils, onAccept, onClose };
}

const click = (name: string | RegExp) => fireEvent.click(screen.getByRole('button', { name }));
const insertion = () => editor.view.dom.querySelector(`.${INS_CLASS}`)?.textContent;

describe('InlineAssistPopover', () => {
  it('needs a selection for polish, expand, summarize and translate', () => {
    open();
    for (const name of ['polish', 'expand', 'summarize', 'translate']) {
      expect(screen.getByRole('button', { name })).toBeDisabled();
    }
    expect(screen.getByRole('button', { name: 'continue' })).toBeEnabled();
    expect(screen.getByRole('button', { name: 'draft from vault' })).toBeEnabled();
  });

  it('continue streams into the document as an insertion without changing it', async () => {
    editor.commands.setTextSelection(editor.state.doc.content.size - 1);
    const { onAccept } = open();
    click('continue');
    const req = lastRequest();
    expect(req).toMatchObject({ path: '20-contexts/work/plan.md', mode: 'continue', placement: 'cursor' });
    expect(req.before?.trim()).toBe('alpha beta gamma');
    expect(req.stream_id).toMatch(/^inline-/);
    expect(req.selection).toBeUndefined();
    fire({ type: 'delta', text: 'and ' });
    fire({ type: 'delta', text: 'delta.' });
    expect(insertion()).toBe(' and delta.');
    expect(markdownOf(editor)).toBe('alpha beta gamma');
    fire({ type: 'done', text: 'and delta.' });
    click(/accept/);
    expect(onAccept).toHaveBeenCalledTimes(1);
    expect(getAiSuggestion(editor)?.status).toBe('ready');
  });

  it('shows the latest tool hint while streaming', () => {
    open();
    fireEvent.change(screen.getByRole('textbox', { name: 'instruction' }), { target: { value: 'risks' } });
    click('draft from vault');
    fire({ type: 'tool', name: 'vault_context', summary: 'reading related notes' });
    expect(screen.getByText('reading related notes')).toBeInTheDocument();
  });

  it('Esc while streaming stops the turn, clears the decorations and closes', () => {
    selectText('beta');
    const { onClose } = open();
    click('polish');
    const ev = fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' });
    expect(ev).toBe(false); // default prevented
    expect(assistStop).toHaveBeenCalledWith(lastRequest().stream_id);
    expect(getAiSuggestion(editor)).toBeNull();
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('stop discards but keeps the popover open', () => {
    selectText('beta');
    const { onClose } = open();
    click('polish');
    click('stop');
    expect(assistStop).toHaveBeenCalledTimes(1);
    expect(getAiSuggestion(editor)).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'polish' })).toBeEnabled();
  });

  it('an error shows a chip with retry that re-sends under a new stream id', () => {
    selectText('beta');
    open();
    click('expand');
    const first = lastRequest().stream_id;
    fire({ type: 'error', message: 'provider unavailable' });
    expect(screen.getByRole('alert')).toHaveTextContent('provider unavailable');
    expect(getAiSuggestion(editor)).toBeNull();
    expect(markdownOf(editor)).toBe('alpha beta gamma');
    click('retry');
    expect(assist).toHaveBeenCalledTimes(2);
    expect(lastRequest().stream_id).not.toBe(first);
    expect(lastRequest().mode).toBe('expand');
  });

  it('a refused request (sidecar down) is an error, not a hang', async () => {
    assist.mockResolvedValueOnce({ ok: false, error: 'Sidecar not ready' });
    selectText('beta');
    open();
    click('polish');
    expect(await screen.findByRole('alert')).toHaveTextContent('Sidecar not ready');
    expect(getAiSuggestion(editor)).toBeNull();
  });

  it('a rejected IPC call is an error, not a hang', async () => {
    assist.mockRejectedValueOnce(new Error('ipc channel closed'));
    selectText('beta');
    open();
    click('polish');
    expect(await screen.findByRole('alert')).toHaveTextContent('ipc channel closed');
    expect(getAiSuggestion(editor)).toBeNull();
  });

  it('an empty answer is an error, not an empty accept', () => {
    selectText('beta');
    open();
    click('polish');
    fire({ type: 'done', text: '```markdown\n\n```' });
    expect(screen.getByRole('alert')).toHaveTextContent('the assistant returned nothing');
    expect(screen.queryByRole('button', { name: /accept/ })).toBeNull();
  });

  it('a stop arriving as an interrupted error returns to idle quietly', () => {
    selectText('beta');
    open();
    click('polish');
    fire({ type: 'error', message: 'interrupted', interrupted: true });
    expect(screen.queryByRole('alert')).toBeNull();
    expect(getAiSuggestion(editor)).toBeNull();
  });

  it('translates the selection into Afrikaans', () => {
    selectText('beta');
    open();
    click('translate');
    click('afrikaans');
    expect(lastRequest()).toMatchObject({ mode: 'translate', target_language: 'Afrikaans', placement: 'selection' });
    expect(lastRequest().selection?.trim()).toBe('beta');
  });

  it('translate other… takes a typed language', () => {
    selectText('beta');
    open();
    click('translate');
    click('other…');
    fireEvent.change(screen.getByRole('textbox', { name: 'language' }), { target: { value: ' isiZulu ' } });
    click('go');
    expect(lastRequest()).toMatchObject({ mode: 'translate', target_language: 'isiZulu' });
  });

  it('draft from vault needs an instruction', () => {
    open();
    click('draft from vault');
    expect(assist).not.toHaveBeenCalled();
    expect(screen.getByText('say what to draft first')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox', { name: 'instruction' }), { target: { value: 'risks section' } });
    click('draft from vault');
    expect(lastRequest()).toMatchObject({ mode: 'draft', instruction: 'risks section', placement: 'cursor' });
  });

  it('Enter in the instruction box drafts at the cursor', () => {
    open();
    const box = screen.getByRole('textbox', { name: 'instruction' });
    fireEvent.change(box, { target: { value: 'a closing line' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    expect(lastRequest()).toMatchObject({ mode: 'draft', instruction: 'a closing line' });
  });

  it('ignores events from another stream', () => {
    selectText('beta');
    open();
    click('polish');
    act(() => listener?.({ key: 'inline-other', jotId: 'inline-other', event: { type: 'delta', text: 'NOPE' } }));
    expect(insertion()).not.toContain('NOPE');
  });

  it('unmounting while streaming stops the turn and removes the decorations', () => {
    selectText('beta');
    const { unmount } = open();
    click('polish');
    unmount();
    expect(assistStop).toHaveBeenCalledTimes(1);
    expect(getAiSuggestion(editor)).toBeNull();
  });

  it('runs the initial action straight away (docs-panel hand-off)', () => {
    selectText('beta');
    open({ initial: { mode: 'summarize', instruction: 'two lines' } });
    expect(lastRequest()).toMatchObject({ mode: 'summarize', instruction: 'two lines', selection: 'beta' });
  });

  it('editor-focused keys reach the popover through keyRef', () => {
    selectText('beta');
    const { onAccept, onClose } = open();
    click('polish');
    fire({ type: 'done', text: 'BETA' });
    act(() => {
      keyRef.current?.('accept');
    });
    expect(onAccept).toHaveBeenCalledTimes(1);
    act(() => {
      keyRef.current?.('reject');
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
