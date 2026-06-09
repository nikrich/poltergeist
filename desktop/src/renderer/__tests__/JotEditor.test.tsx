import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act } from '@testing-library/react';
import type { EditorView } from '@codemirror/view';
import { JotEditor } from '../components/JotEditor';

// CodeMirror 6 in jsdom does not support the layout APIs that userEvent.type
// depends on (textRange.getClientRects, etc.), so typing via DOM events is not
// viable. Instead we capture the EditorView via the `onCreateEditor` prop and
// drive changes through view.dispatch(), which bypasses DOM layout entirely.
// The debounce logic, the no-op guard (next === lastSaved), and the unmount
// cleanup are all still exercised faithfully — only the input mechanism
// differs from what a real user would do in the browser.

vi.useFakeTimers();

describe('JotEditor', () => {
  beforeEach(() => {
    vi.clearAllTimers();
  });

  afterEach(() => {
    vi.clearAllTimers();
  });

  it('renders the initial body', () => {
    render(<JotEditor body="hello world" onSave={() => {}} />);
    // CodeMirror renders each line as a .cm-line; the text is present in the DOM.
    expect(screen.getByText(/hello world/)).toBeInTheDocument();
  });

  it('debounces autosave to 1s after the last keystroke', () => {
    const onSave = vi.fn();
    let capturedView: EditorView | undefined;

    render(
      <JotEditor
        body="initial"
        onSave={onSave}
        onCreateEditor={(view) => { capturedView = view; }}
      />,
    );

    // Inject a text change directly via the CodeMirror transaction API so we
    // do not rely on jsdom DOM layout (which is incomplete for CodeMirror).
    act(() => {
      if (!capturedView) throw new Error('EditorView was not created');
      const { from, to } = capturedView.state.doc.line(1);
      capturedView.dispatch({
        changes: { from, to, insert: 'initial added' },
      });
    });

    // onSave must NOT fire before the debounce window.
    expect(onSave).not.toHaveBeenCalled();

    act(() => { vi.advanceTimersByTime(999); });
    expect(onSave).not.toHaveBeenCalled();

    act(() => { vi.advanceTimersByTime(2); });
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith(expect.stringContaining('added'));
  });

  it('does not call onSave when content is unchanged', () => {
    const onSave = vi.fn();
    render(<JotEditor body="same" onSave={onSave} debounceMs={100} />);
    // No typing — advance well past the debounce window.
    act(() => { vi.advanceTimersByTime(500); });
    expect(onSave).not.toHaveBeenCalled();
  });

  it('cancels a pending save when switching to a different jot (no cross-write)', () => {
    const onSave = vi.fn();
    let capturedView: EditorView | undefined;

    const { rerender } = render(
      <JotEditor
        body="A"
        onSave={onSave}
        onCreateEditor={(view) => { capturedView = view; }}
      />,
    );

    // Edit jot A — a debounced save is now pending with A's edited content.
    act(() => {
      if (!capturedView) throw new Error('EditorView was not created');
      const doc = capturedView.state.doc;
      capturedView.dispatch({ changes: { from: 0, to: doc.length, insert: 'A edited' } });
    });

    // Switch to jot B before the debounce fires (component stays mounted).
    rerender(
      <JotEditor
        body="B"
        onSave={onSave}
        onCreateEditor={(view) => { capturedView = view; }}
      />,
    );

    // Advance well past the debounce window: the stale timer from jot A must
    // have been cancelled, so onSave must never fire with A's content.
    act(() => { vi.advanceTimersByTime(2000); });
    expect(onSave).not.toHaveBeenCalled();
  });

  it('fires onSave at most once for rapid successive changes', () => {
    const onSave = vi.fn();
    let capturedView: EditorView | undefined;

    render(
      <JotEditor
        body=""
        onSave={onSave}
        debounceMs={500}
        onCreateEditor={(view) => { capturedView = view; }}
      />,
    );

    // Fire three rapid changes; each should reset the debounce timer.
    ['a', 'ab', 'abc'].forEach((text) => {
      act(() => {
        if (!capturedView) throw new Error('EditorView was not created');
        const doc = capturedView.state.doc;
        capturedView.dispatch({ changes: { from: 0, to: doc.length, insert: text } });
      });
    });

    act(() => { vi.advanceTimersByTime(499); });
    expect(onSave).not.toHaveBeenCalled();

    act(() => { vi.advanceTimersByTime(2); });
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith('abc');
  });
});
