import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, fireEvent } from '@testing-library/react';
import type { Editor } from '@tiptap/core';
import { RichMarkdownEditor } from '../components/RichMarkdownEditor';

vi.useFakeTimers();

function lastMarkdown(onSave: ReturnType<typeof vi.fn>): string {
  return onSave.mock.calls[onSave.mock.calls.length - 1]![0] as string;
}

describe('RichMarkdownEditor', () => {
  beforeEach(() => {
    vi.clearAllTimers();
  });

  afterEach(() => {
    vi.clearAllTimers();
  });

  it('renders markdown as rich nodes', () => {
    const { container } = render(
      <RichMarkdownEditor markdown={'# title\n\nbody text'} onSave={() => {}} />,
    );
    const h1 = container.querySelector('h1');
    expect(h1).not.toBeNull();
    expect(h1!.textContent).toBe('title');
    expect(screen.getByText('body text')).toBeInTheDocument();
  });

  it('applies the heading input rule while typing ("# " + space)', () => {
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown=""
        onSave={() => {}}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    expect(editor).toBeDefined();
    act(() => {
      const view = editor!.view;
      view.dispatch(view.state.tr.insertText('#', 1, 1));
      // Direct transactions bypass ProseMirror input rules; feed the plugin's
      // handleTextInput exactly like a real keystroke would.
      // prosemirror-view ≥ 1.37 added a required 5th `deflt` arg to
      // handleTextInput; supply a no-op so the type checker is satisfied.
      const handled = view.someProp('handleTextInput', (f) =>
        f(view, 2, 2, ' ', () => view.state.tr),
      );
      expect(handled).toBe(true);
    });
    expect(editor!.state.doc.firstChild!.type.name).toBe('heading');
    expect(editor!.state.doc.firstChild!.attrs.level).toBe(1);
  });

  it('debounces autosave to 1s after the last change', () => {
    const onSave = vi.fn();
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown="initial"
        onSave={onSave}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    act(() => {
      editor!.commands.insertContentAt(editor!.state.doc.content.size, ' added');
    });
    expect(onSave).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(999);
    });
    expect(onSave).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(2);
    });
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(lastMarkdown(onSave)).toContain('added');
  });

  it('does not save when content is unchanged', () => {
    const onSave = vi.fn();
    render(<RichMarkdownEditor markdown="same" onSave={onSave} debounceMs={100} />);
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(onSave).not.toHaveBeenCalled();
  });

  it('cancels a pending save when the markdown prop switches (no cross-write)', () => {
    const onSave = vi.fn();
    let editor: Editor | undefined;
    const { rerender } = render(
      <RichMarkdownEditor
        markdown="A"
        onSave={onSave}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    // Edit note A — a debounced save is now pending with A's edited content.
    act(() => {
      editor!.commands.insertContentAt(editor!.state.doc.content.size, ' edited');
    });
    // Switch to note B before the debounce fires (component stays mounted).
    rerender(
      <RichMarkdownEditor markdown="B" onSave={onSave} onEditorReady={() => {}} />,
    );
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(onSave).not.toHaveBeenCalled();
  });

  it('does not fire a pending save after unmount', () => {
    const onSave = vi.fn();
    let editor: Editor | undefined;
    const { unmount } = render(
      <RichMarkdownEditor
        markdown="A"
        onSave={onSave}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    act(() => {
      editor!.commands.insertContentAt(editor!.state.doc.content.size, ' x');
    });
    unmount();
    act(() => {
      vi.advanceTimersByTime(2000);
    });
    expect(onSave).not.toHaveBeenCalled();
  });

  it('swaps to the CodeMirror source editor via the footer toggle', () => {
    const { container } = render(
      <RichMarkdownEditor markdown={'# title'} onSave={() => {}} />,
    );
    expect(container.querySelector('.cm-editor')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'src' }));
    expect(container.querySelector('.cm-editor')).not.toBeNull();
    // Source mode shows raw markdown, not a rendered heading.
    // CodeMirror syntax-highlights by wrapping tokens in separate <span>s,
    // so the text "# title" is split across nodes — check the combined
    // textContent of the editable region instead of a single text node.
    expect(container.querySelector('.cm-content')?.textContent).toContain('# title');
    // and back:
    fireEvent.click(screen.getByRole('button', { name: 'rich' }));
    expect(container.querySelector('.cm-editor')).toBeNull();
    expect(container.querySelector('h1')).not.toBeNull();
  });
});
