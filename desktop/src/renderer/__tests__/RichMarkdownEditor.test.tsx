import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, fireEvent, waitFor } from '@testing-library/react';
import type { Editor } from '@tiptap/core';
import { RichMarkdownEditor } from '../components/RichMarkdownEditor';
import { useToasts } from '../stores/toast';

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

describe('RichMarkdownEditor copy-formatted', () => {
  beforeEach(() => {
    // waitFor cannot poll under vitest fake timers (testing-library's
    // detection requires a `jest` global), and these tests await microtask
    // results — run them on real timers.
    vi.useRealTimers();
    useToasts.setState({ toasts: [] });
  });

  afterEach(() => {
    vi.useFakeTimers();
  });

  it('copies the whole note when there is no selection', async () => {
    const writeRich = vi.fn().mockResolvedValue({ ok: true });
    window.gb = { ...window.gb, clipboard: { writeRich } };
    render(
      <RichMarkdownEditor markdown={'# title\n\nsome **bold** text'} onSave={() => {}} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /copy formatted/ }));
    await waitFor(() => expect(writeRich).toHaveBeenCalledTimes(1));
    const payload = writeRich.mock.calls[0]![0] as { html: string; text: string };
    expect(payload.html).toContain('<h1>title</h1>');
    expect(payload.html).toContain('<strong>bold</strong>');
    expect(payload.text).toBe('# title\n\nsome **bold** text');
  });

  it('copies only the selection when one exists', async () => {
    const writeRich = vi.fn().mockResolvedValue({ ok: true });
    window.gb = { ...window.gb, clipboard: { writeRich } };
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown={'# title\n\nsecond paragraph'}
        onSave={() => {}}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    act(() => {
      // Select the full second paragraph. Doc layout: heading node occupies
      // positions [0, headingNodeSize); the paragraph's inline content starts
      // one position inside the paragraph node.
      const doc = editor!.state.doc;
      const para = doc.child(1);
      const start = doc.firstChild!.nodeSize + 1;
      editor!.commands.setTextSelection({ from: start, to: start + para.content.size });
    });
    fireEvent.click(screen.getByRole('button', { name: /copy formatted/ }));
    await waitFor(() => expect(writeRich).toHaveBeenCalledTimes(1));
    const payload = writeRich.mock.calls[0]![0] as { html: string; text: string };
    expect(payload.html).toContain('second paragraph');
    expect(payload.html).not.toContain('title');
    expect(payload.text.trim()).toBe('second paragraph');
  });

  it('copies via meta+shift+C inside the editor', async () => {
    const writeRich = vi.fn().mockResolvedValue({ ok: true });
    window.gb = { ...window.gb, clipboard: { writeRich } };
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown="shortcut me"
        onSave={() => {}}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    fireEvent.keyDown(editor!.view.dom, { key: 'c', metaKey: true, shiftKey: true });
    await waitFor(() => expect(writeRich).toHaveBeenCalledTimes(1));
    expect((writeRich.mock.calls[0]![0] as { text: string }).text).toBe('shortcut me');
  });

  it('shows a success toast after copying', async () => {
    const writeRich = vi.fn().mockResolvedValue({ ok: true });
    window.gb = { ...window.gb, clipboard: { writeRich } };
    render(<RichMarkdownEditor markdown="x" onSave={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: /copy formatted/ }));
    await waitFor(() =>
      expect(
        useToasts.getState().toasts.some((t) => t.message.includes('copied')),
      ).toBe(true),
    );
  });

  it('shows an error toast when the clipboard write fails', async () => {
    const writeRich = vi.fn().mockResolvedValue({ ok: false, error: 'nope' });
    window.gb = { ...window.gb, clipboard: { writeRich } };
    render(<RichMarkdownEditor markdown="x" onSave={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: /copy formatted/ }));
    await waitFor(() =>
      expect(
        useToasts
          .getState()
          .toasts.some((t) => t.kind === 'error' && t.message.includes('copy failed')),
      ).toBe(true),
    );
  });

  it('hides the copy button in source mode', () => {
    render(<RichMarkdownEditor markdown="x" onSave={() => {}} />);
    fireEvent.click(screen.getByRole('button', { name: 'src' }));
    expect(screen.queryByRole('button', { name: /copy formatted/ })).toBeNull();
  });
});
