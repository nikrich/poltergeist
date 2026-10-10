import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen } from '@testing-library/react';
import type { Editor } from '@tiptap/core';
import { RichMarkdownEditor } from '../components/RichMarkdownEditor';
import { useSettings } from '../stores/settings';
import { useToasts } from '../stores/toast';
import {
  end,
  fail,
  fakeVoice,
  installFakeSpeech,
  uninstallFakeSpeech,
  type FakeSynth,
} from './helpers/fake-speech';

let synth: FakeSynth;

beforeEach(() => {
  synth = installFakeSpeech();
  useSettings.setState({ readAloudVoice: '', readAloudRate: 1 });
  useToasts.setState({ toasts: [] });
});

afterEach(() => uninstallFakeSpeech());

function renderEditor(markdown: string) {
  const onSave = vi.fn();
  let editor: Editor | undefined;
  const utils = render(
    <RichMarkdownEditor
      markdown={markdown}
      onSave={onSave}
      jotId="t"
      debounceMs={10}
      onEditorReady={(e) => {
        editor = e;
      }}
    />,
  );
  return { ...utils, onSave, editor: () => editor! };
}

const readButton = () => screen.getByRole('button', { name: /^read aloud/ });

function highlighted(container: HTMLElement): string {
  return Array.from(container.querySelectorAll('.gb-read-aloud-current'))
    .map((n) => n.textContent)
    .join('');
}

function posOf(editor: Editor, needle: string): number {
  let found = -1;
  editor.state.doc.descendants((node, pos) => {
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

describe('ReadAloudControls', () => {
  it('hides the read button when speech synthesis is unavailable', () => {
    uninstallFakeSpeech();
    renderEditor('Hello there.');
    expect(screen.queryByRole('button', { name: /^read aloud/ })).toBeNull();
  });

  it('reads the note sentence by sentence and highlights the current one', () => {
    const { container } = renderEditor('# Plan\n\nFirst point. Second point.');
    fireEvent.click(readButton());
    expect(synth.texts()).toEqual(['Plan']);
    expect(highlighted(container)).toBe('Plan');
    act(() => end(synth.last));
    expect(highlighted(container)).toBe('First point.');
    act(() => end(synth.last));
    act(() => end(synth.last));
    expect(synth.texts()).toEqual(['Plan', 'First point.', 'Second point.']);
    expect(highlighted(container)).toBe('');
    expect(readButton()).toBeInTheDocument();
  });

  it('pause cancels, resume restarts the same sentence, stop clears', () => {
    const { container } = renderEditor('One. Two.');
    fireEvent.click(readButton());
    const first = synth.last;
    fireEvent.click(screen.getByRole('button', { name: 'pause reading' }));
    expect(synth.cancel).toHaveBeenCalled();
    act(() => fail(first, 'interrupted'));
    act(() => end(first));
    expect(synth.texts()).toEqual(['One.']);
    expect(highlighted(container)).toBe('One.');
    fireEvent.click(screen.getByRole('button', { name: 'resume reading' }));
    expect(synth.texts()).toEqual(['One.', 'One.']);
    fireEvent.click(screen.getByRole('button', { name: 'stop reading' }));
    expect(highlighted(container)).toBe('');
    expect(readButton()).toBeInTheDocument();
  });

  it('reads only the selection when there is one', () => {
    const h = renderEditor('Alpha one. Beta two. Gamma three.');
    const ed = h.editor();
    act(() => {
      ed.commands.setTextSelection({ from: posOf(ed, 'Beta'), to: posOf(ed, 'two.') + 4 });
    });
    fireEvent.click(readButton());
    act(() => end(synth.last));
    expect(synth.texts()).toEqual(['Beta two.']);
  });

  it('reads from the cursor to the end of the note', () => {
    const h = renderEditor('Alpha one. Beta two. Gamma three.');
    const ed = h.editor();
    act(() => {
      ed.commands.setTextSelection(posOf(ed, 'two'));
    });
    fireEvent.click(readButton());
    act(() => end(synth.last));
    expect(synth.texts()).toEqual(['Beta two.', 'Gamma three.']);
  });

  it('auto voice picks an Afrikaans voice for an Afrikaans note', () => {
    synth.voices = [fakeVoice('Samantha', 'en-US', { default: true }), fakeVoice('Afrikaans', 'af-ZA')];
    renderEditor('Ek het die vergadering bygewoon en ons sal more weer praat.');
    fireEvent.click(readButton());
    expect(synth.last?.voice?.lang).toBe('af-ZA');
  });

  it('an explicit voice and rate from settings win', () => {
    synth.voices = [fakeVoice('Samantha', 'en-US', { default: true }), fakeVoice('Daniel', 'en-GB')];
    useSettings.setState({ readAloudVoice: 'Daniel-uri', readAloudRate: 1.5 });
    renderEditor('Hello there.');
    fireEvent.click(readButton());
    expect(synth.last?.voice?.name).toBe('Daniel');
    expect(synth.last?.rate).toBe(1.5);
  });

  it('an engine failure stops reading with a toast', () => {
    renderEditor('One. Two.');
    fireEvent.click(readButton());
    act(() => fail(synth.last, 'synthesis-failed'));
    expect(
      useToasts.getState().toasts.some((t) => t.message.includes('synthesis-failed')),
    ).toBe(true);
    expect(readButton()).toBeInTheDocument();
  });

  it('a note with only code says there is nothing to read', () => {
    renderEditor('```js\nconst x = 1;\n```');
    fireEvent.click(readButton());
    expect(synth.spoken).toHaveLength(0);
    expect(
      useToasts.getState().toasts.some((t) => t.message === 'nothing to read here'),
    ).toBe(true);
  });

  it('unmounting (note switch) stops speech and ignores the late end event', () => {
    const h = renderEditor('One. Two.');
    fireEvent.click(readButton());
    const u = synth.last;
    h.unmount();
    expect(synth.cancel).toHaveBeenCalled();
    end(u);
    expect(synth.spoken).toHaveLength(1);
  });

  it('⌘⇧L in the editor toggles reading', () => {
    const h = renderEditor('One. Two.');
    const dom = h.editor().view.dom;
    fireEvent.keyDown(dom, { key: 'L', metaKey: true, shiftKey: true });
    expect(synth.texts()).toEqual(['One.']);
    fireEvent.keyDown(dom, { key: 'L', metaKey: true, shiftKey: true });
    expect(screen.getByRole('button', { name: 'resume reading' })).toBeInTheDocument();
  });

  it('the highlight never triggers an autosave and follows edits', async () => {
    const h = renderEditor('One. Two.');
    const ed = h.editor();
    fireEvent.click(readButton());
    act(() => end(synth.last));
    await act(async () => {
      await new Promise((r) => setTimeout(r, 40));
    });
    expect(h.onSave).not.toHaveBeenCalled();
    act(() => {
      ed.view.dispatch(ed.state.tr.insertText('New. ', 1));
    });
    expect(highlighted(h.container)).toBe('Two.');
  });

  it('switching to source mode stops reading and hides the controls', () => {
    renderEditor('One. Two.');
    fireEvent.click(readButton());
    fireEvent.click(screen.getByRole('button', { name: 'src' }));
    expect(synth.cancel).toHaveBeenCalled();
    expect(screen.queryByRole('group', { name: 'read aloud controls' })).toBeNull();
  });
});
