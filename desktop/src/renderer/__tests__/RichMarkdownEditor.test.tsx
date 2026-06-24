import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, act, fireEvent, waitFor } from '@testing-library/react';
import type { Editor } from '@tiptap/core';
import type { EditorView } from '@tiptap/pm/view';
import { RichMarkdownEditor } from '../components/RichMarkdownEditor';
import type { EditorHandle } from '../components/RichMarkdownEditor';
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
      <RichMarkdownEditor markdown={'# title\n\nbody text'} onSave={() => {}} jotId="test" />,
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
        jotId="test"
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
        jotId="test"
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
    render(<RichMarkdownEditor markdown="same" onSave={onSave} debounceMs={100} jotId="test" />);
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
        jotId="test"
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
      <RichMarkdownEditor markdown="B" onSave={onSave} jotId="test" onEditorReady={() => {}} />,
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
        jotId="test"
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
      <RichMarkdownEditor markdown={'# title'} onSave={() => {}} jotId="test" />,
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

describe('RichMarkdownEditor wikilink click-to-navigate', () => {
  // These tests run under fake timers (inherited from the outer vi.useFakeTimers()).

  it('fires onWikilinkClick with the target path when clicking inside [[path]]', () => {
    const onWikilinkClick = vi.fn();
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown="See [[20-contexts/personal/_profile]] for details."
        onSave={() => {}}
        jotId="test"
        onWikilinkClick={onWikilinkClick}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    expect(editor).toBeDefined();
    act(() => {
      // Find a position inside the wikilink text "[[20-contexts/personal/_profile]]"
      // The doc has one paragraph; scan text to find the offset of "[["
      const doc = editor!.state.doc;
      let wikilinkPos = -1;
      doc.descendants((node, pos) => {
        if (node.isText && node.text && node.text.includes('[[')) {
          const offset = node.text.indexOf('[[');
          wikilinkPos = pos + offset + 5; // click well inside the brackets
          return false;
        }
      });
      expect(wikilinkPos).toBeGreaterThan(0);
      const handled = editor!.view.someProp('handleClick', (f: (view: EditorView, pos: number, event: MouseEvent) => boolean | void) =>
        f(editor!.view, wikilinkPos, new MouseEvent('click')),
      );
      expect(handled).toBe(true);
    });
    expect(onWikilinkClick).toHaveBeenCalledWith('20-contexts/personal/_profile');
  });

  it('extracts path before "|" for piped wikilinks [[a/b|Title]]', () => {
    const onWikilinkClick = vi.fn();
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown="Link: [[a/b|Title Here]] end."
        onSave={() => {}}
        jotId="test"
        onWikilinkClick={onWikilinkClick}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    act(() => {
      const doc = editor!.state.doc;
      let wikilinkPos = -1;
      doc.descendants((node, pos) => {
        if (node.isText && node.text && node.text.includes('[[')) {
          const offset = node.text.indexOf('[[');
          wikilinkPos = pos + offset + 5;
          return false;
        }
      });
      expect(wikilinkPos).toBeGreaterThan(0);
      editor!.view.someProp('handleClick', (f: (view: EditorView, pos: number, event: MouseEvent) => boolean | void) =>
        f(editor!.view, wikilinkPos, new MouseEvent('click')),
      );
    });
    expect(onWikilinkClick).toHaveBeenCalledWith('a/b');
  });

  it('clicking the second of two wikilinks yields the second target', () => {
    const onWikilinkClick = vi.fn();
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown="See [[first/note]] and [[second/note]] here."
        onSave={() => {}}
        jotId="test"
        onWikilinkClick={onWikilinkClick}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    expect(editor).toBeDefined();
    act(() => {
      const doc = editor!.state.doc;
      let wikilinkPos = -1;
      doc.descendants((node, pos) => {
        if (node.isText && node.text && node.text.includes('[[second')) {
          const offset = node.text.indexOf('[[second');
          wikilinkPos = pos + offset + 5; // inside the second wikilink
          return false;
        }
      });
      expect(wikilinkPos).toBeGreaterThan(0);
      const handled = editor!.view.someProp('handleClick', (f: (view: EditorView, pos: number, event: MouseEvent) => boolean | void) =>
        f(editor!.view, wikilinkPos, new MouseEvent('click')),
      );
      expect(handled).toBe(true);
    });
    expect(onWikilinkClick).toHaveBeenCalledWith('second/note');
    expect(onWikilinkClick).not.toHaveBeenCalledWith('first/note');
  });

  it('does NOT fire onWikilinkClick when clicking plain text', () => {
    const onWikilinkClick = vi.fn();
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown="Just plain text here."
        onSave={() => {}}
        jotId="test"
        onWikilinkClick={onWikilinkClick}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    act(() => {
      // Click at position 2 (inside "Just")
      // ProseMirror's someProp returns undefined when no handler returns truthy —
      // returning false from handleClick means "not consumed", someProp returns undefined.
      const handled = editor!.view.someProp('handleClick', (f: (view: EditorView, pos: number, event: MouseEvent) => boolean | void) =>
        f(editor!.view, 2, new MouseEvent('click')),
      );
      expect(handled).toBeFalsy();
    });
    expect(onWikilinkClick).not.toHaveBeenCalled();
  });

  it('does NOT fire onWikilinkClick when no callback is provided', () => {
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown="See [[some/note]] done."
        onSave={() => {}}
        jotId="test"
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    act(() => {
      const doc = editor!.state.doc;
      let wikilinkPos = -1;
      doc.descendants((node, pos) => {
        if (node.isText && node.text && node.text.includes('[[')) {
          const offset = node.text.indexOf('[[');
          wikilinkPos = pos + offset + 5;
          return false;
        }
      });
      // Should not throw even without callback
      const handled = editor!.view.someProp('handleClick', (f: (view: EditorView, pos: number, event: MouseEvent) => boolean | void) =>
        f(editor!.view, wikilinkPos, new MouseEvent('click')),
      );
      // Without callback, click must not be consumed (someProp returns undefined/falsy)
      expect(handled).toBeFalsy();
    });
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
      <RichMarkdownEditor markdown={'# title\n\nsome **bold** text'} onSave={() => {}} jotId="test" />,
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
        jotId="test"
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
        jotId="test"
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
    render(<RichMarkdownEditor markdown="x" onSave={() => {}} jotId="test" />);
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
    render(<RichMarkdownEditor markdown="x" onSave={() => {}} jotId="test" />);
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
    render(<RichMarkdownEditor markdown="x" onSave={() => {}} jotId="test" />);
    fireEvent.click(screen.getByRole('button', { name: 'src' }));
    expect(screen.queryByRole('button', { name: /copy formatted/ })).toBeNull();
  });
});

// ── EditorHandle imperative ref ─────────────────────────────────────────────
// These tests run under fake timers (inherited from vi.useFakeTimers() at top).

describe('RichMarkdownEditor EditorHandle', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllTimers();
  });

  afterEach(() => {
    vi.clearAllTimers();
  });

  it('populates handleRef on mount and nulls it on unmount', () => {
    const handleRef = { current: null as EditorHandle | null };
    const { unmount } = render(
      <RichMarkdownEditor markdown="hello" onSave={() => {}} jotId="test" handleRef={handleRef} />,
    );
    expect(handleRef.current).not.toBeNull();
    unmount();
    expect(handleRef.current).toBeNull();
  });

  it('getMarkdown returns the current document markdown', () => {
    const handleRef = { current: null as EditorHandle | null };
    render(
      <RichMarkdownEditor
        markdown="# heading\n\nbody text"
        onSave={() => {}}
        jotId="test"
        handleRef={handleRef}
      />,
    );
    // getMarkdown returns current.current (the prop value at mount), which
    // tiptap-markdown may normalise slightly on round-trip — check key tokens.
    const md = handleRef.current?.getMarkdown() ?? '';
    expect(md).toContain('# heading');
    expect(md).toContain('body text');
  });

  it('getHTML returns non-empty HTML in rich mode', () => {
    const handleRef = { current: null as EditorHandle | null };
    render(
      <RichMarkdownEditor markdown="# title" onSave={() => {}} jotId="test" handleRef={handleRef} />,
    );
    const html = handleRef.current?.getHTML();
    expect(html).toBeTruthy();
    expect(html).toContain('<h1>');
  });

  it('getSelectionMarkdown returns empty string when selection is collapsed', () => {
    const handleRef = { current: null as EditorHandle | null };
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown="some content"
        onSave={() => {}}
        jotId="test"
        handleRef={handleRef}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    // Collapsed (point) selection — no text selected.
    act(() => {
      editor!.commands.setTextSelection(2);
    });
    expect(handleRef.current?.getSelectionMarkdown()).toBe('');
  });

  it('replaceWith(md, doc) triggers onSave with new markdown after debounce', () => {
    const onSave = vi.fn();
    const handleRef = { current: null as EditorHandle | null };
    render(
      <RichMarkdownEditor
        markdown="original"
        onSave={onSave}
        debounceMs={500}
        jotId="test"
        handleRef={handleRef}
      />,
    );
    act(() => {
      handleRef.current?.replaceWith('# replaced\n\nnew content', 'doc');
    });
    // Not yet — debounce has not fired.
    expect(onSave).not.toHaveBeenCalled();
    act(() => {
      vi.advanceTimersByTime(600);
    });
    expect(onSave).toHaveBeenCalledTimes(1);
    // The saved markdown should reflect the new content (not the original).
    expect(lastMarkdown(onSave)).toContain('replaced');
  });

  it('replaceWith(md, selection) parses markdown into rich content (not literal text)', () => {
    // Pins the tiptap-markdown@0.8.10 contract: the Markdown extension
    // overrides insertContentAt to parse strings through its markdown parser,
    // so replaceWith('**bold** …', 'selection') must round-trip as markdown —
    // the saved doc keeps the ** syntax instead of escaped literal \*\* text.
    const onSave = vi.fn();
    const handleRef = { current: null as EditorHandle | null };
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown={'# keep\n\nreplace me'}
        onSave={onSave}
        debounceMs={500}
        jotId="test"
        handleRef={handleRef}
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    act(() => {
      // Select the full second paragraph (same layout math as the copy test).
      const doc = editor!.state.doc;
      const para = doc.child(1);
      const start = doc.firstChild!.nodeSize + 1;
      editor!.commands.setTextSelection({ from: start, to: start + para.content.size });
    });
    act(() => {
      handleRef.current?.replaceWith('**bold** text', 'selection');
    });
    act(() => {
      vi.advanceTimersByTime(600);
    });
    expect(onSave).toHaveBeenCalledTimes(1);
    const saved = lastMarkdown(onSave);
    expect(saved).toContain('# keep');
    expect(saved).toContain('**bold** text');
    expect(saved).not.toContain('replace me');
    expect(saved).not.toContain('\\*\\*');
  });
});
