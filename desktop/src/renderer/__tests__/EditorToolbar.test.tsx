import { createEvent, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Editor } from '@tiptap/core';
import { EditorToolbar } from '../components/EditorToolbar';
import { useAnchoredPanel } from '../components/editor-toolbar/ToolbarMenu';
import { SLASH_ITEMS } from '../lib/editor/slash';
import { useSettings } from '../stores/settings';
import { makeEditor, markdownOf } from './helpers/editor';

let editor: Editor;

afterEach(() => {
  editor?.destroy();
  useSettings.setState({ pageWidth: 'fixed' });
});

function setup(content = 'word', props: Partial<React.ComponentProps<typeof EditorToolbar>> = {}) {
  editor = makeEditor(content);
  render(<EditorToolbar editor={editor} {...props} />);
  return editor;
}

const openInsert = () => fireEvent.click(screen.getByRole('button', { name: 'insert' }));

describe('EditorToolbar (A7)', () => {
  it('toggles marks on the selection and shows the shortcut in the tooltip', () => {
    setup();
    editor.commands.selectAll();
    fireEvent.click(screen.getByRole('button', { name: 'bold' }));
    fireEvent.click(screen.getByRole('button', { name: 'strikethrough' }));
    expect(editor.isActive('bold')).toBe(true);
    expect(editor.isActive('strike')).toBe(true);
    const bold = screen.getByRole('button', { name: 'bold' });
    expect(bold).toHaveAttribute('title', 'Bold (⌘ B)');
    expect(bold).toHaveAttribute('aria-pressed', 'true');
  });

  it('numbered list', () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: 'numbered list' }));
    expect(markdownOf(editor)).toBe('1. word');
  });

  it('text style menu sets headings and back to normal text', () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: 'text style' }));
    fireEvent.click(screen.getByRole('menuitemradio', { name: /^Heading 2/ }));
    expect(editor.isActive('heading', { level: 2 })).toBe(true);
    expect(screen.getByRole('button', { name: 'text style' })).toHaveTextContent('Heading 2');
    fireEvent.click(screen.getByRole('button', { name: 'text style' }));
    expect(screen.getByRole('menuitemradio', { name: /^Heading 2/ })).toHaveAttribute('aria-checked', 'true');
    fireEvent.click(screen.getByRole('menuitemradio', { name: /^Normal text/ }));
    expect(markdownOf(editor)).toBe('word');
  });

  it('insert lists every block in order; Template only with C1, Ask AI only with a handler', () => {
    setup('word', { onImageFile: () => {} });
    openInsert();
    const names = screen.getAllByRole('menuitem').map((m) => m.textContent);
    const base = [
      'Info panel', 'Note panel', 'Success panel', 'Warning panel', 'Error panel', 'Tip panel',
      'Expand', 'Status', 'Table of contents', 'Mermaid diagram', 'Image', 'Photo (webcam)',
      'Table', 'Divider', 'Code block', 'Quote',
    ];
    const hasTemplate = SLASH_ITEMS.some((i) => i.key === 'template');
    expect(names).toEqual(hasTemplate ? [...base, 'Template'] : base);
  });

  it('Ask AI calls the assist handler', () => {
    const onAssist = vi.fn();
    setup('word', { onAssist });
    openInsert();
    fireEvent.click(screen.getByRole('menuitem', { name: 'Ask AI' }));
    expect(onAssist).toHaveBeenCalledOnce();
  });

  it('inserting an error panel runs the A1 callout command', () => {
    setup('');
    openInsert();
    fireEvent.click(screen.getByRole('menuitem', { name: 'Error panel' }));
    expect(markdownOf(editor)).toBe('> [!error]');
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('Image opens the file picker and hands the picked file over', () => {
    const onImageFile = vi.fn();
    setup('word', { onImageFile });
    const picker = screen.getByTestId('image-picker') as HTMLInputElement;
    const click = vi.spyOn(picker, 'click').mockImplementation(() => {});
    openInsert();
    fireEvent.click(screen.getByRole('menuitem', { name: 'Image' }));
    expect(click).toHaveBeenCalledOnce();
    const file = new File(['x'], 'a.png', { type: 'image/png' });
    fireEvent.change(picker, { target: { files: [file] } });
    expect(onImageFile).toHaveBeenCalledWith(file);
  });

  it('no Image row without an image handler', () => {
    setup();
    openInsert();
    expect(screen.queryByRole('menuitem', { name: 'Image' })).toBeNull();
  });

  it('Esc closes a menu and is consumed so the note viewer stays open', () => {
    setup();
    openInsert();
    const item = screen.getAllByRole('menuitem')[0]!;
    const esc = createEvent.keyDown(item, { key: 'Escape' });
    fireEvent(item, esc);
    expect(esc.defaultPrevented).toBe(true);
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('arrow keys move through the menu and wrap', () => {
    setup();
    openInsert();
    const items = screen.getAllByRole('menuitem');
    expect(items[0]).toHaveFocus();
    fireEvent.keyDown(items[0]!, { key: 'ArrowDown' });
    expect(items[1]).toHaveFocus();
    fireEvent.keyDown(items[1]!, { key: 'ArrowUp' });
    fireEvent.keyDown(items[0]!, { key: 'ArrowUp' });
    expect(items.at(-1)).toHaveFocus();
  });

  it('link: applies a normalised address to the selection', () => {
    setup();
    editor.commands.selectAll();
    fireEvent.click(screen.getByRole('button', { name: 'link' }));
    fireEvent.change(screen.getByLabelText('link address'), { target: { value: 'example.com' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(editor.getAttributes('link').href).toBe('https://example.com');
    expect(screen.queryByRole('dialog', { name: 'edit link' })).toBeNull();
  });

  it('link: refuses script addresses', () => {
    setup();
    editor.commands.selectAll();
    fireEvent.click(screen.getByRole('button', { name: 'link' }));
    fireEvent.change(screen.getByLabelText('link address'), { target: { value: 'javascript:alert(1)' } });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Use an http, https or mailto link');
    expect(editor.isActive('link')).toBe(false);
  });

  it('link: prefills the current address and removes the link', () => {
    setup('[word](https://a.example)');
    editor.commands.selectAll();
    fireEvent.click(screen.getByRole('button', { name: 'link' }));
    expect(screen.getByLabelText('link address')).toHaveValue('https://a.example');
    fireEvent.click(screen.getByRole('button', { name: 'Remove link' }));
    expect(markdownOf(editor)).toBe('word');
  });

  it('link: Esc closes the form and is consumed', () => {
    setup();
    fireEvent.click(screen.getByRole('button', { name: 'link' }));
    const input = screen.getByLabelText('link address');
    const esc = createEvent.keyDown(input, { key: 'Escape' });
    fireEvent(input, esc);
    expect(esc.defaultPrevented).toBe(true);
    expect(screen.queryByRole('dialog', { name: 'edit link' })).toBeNull();
  });

  it('table inserts the A1 table', () => {
    setup('');
    fireEvent.click(screen.getByRole('button', { name: 'table' }));
    expect(editor.isActive('table')).toBe(true);
  });

  it('page width toggle flips the global setting', async () => {
    setup();
    const btn = screen.getByRole('button', { name: 'full width' });
    expect(btn).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(btn);
    await waitFor(() => expect(useSettings.getState().pageWidth).toBe('full'));
    expect(screen.getByRole('button', { name: 'full width' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows the inline ai button only with onAssist', () => {
    const editor = makeEditor();
    const onAssist = vi.fn();
    const { rerender } = render(<EditorToolbar editor={editor} onPhoto={() => {}} />);
    expect(screen.queryByRole('button', { name: 'inline ai' })).toBeNull();
    rerender(<EditorToolbar editor={editor} onPhoto={() => {}} onAssist={onAssist} />);
    fireEvent.click(screen.getByRole('button', { name: 'inline ai' }));
    expect(onAssist).toHaveBeenCalledOnce();
    editor.destroy();
  });

  // jsdom focuses hidden elements; Chromium does not. An opened panel must
  // never be visibility:hidden, or focus stays in the editor (Review Focus #1).
  it('opened menus and the link form are never hidden, so they can take focus', () => {
    setup();
    openInsert();
    expect(screen.getByRole('menu').style.visibility).not.toBe('hidden');
    expect(screen.getAllByRole('menuitem')[0]).toHaveFocus();
    fireEvent.keyDown(screen.getAllByRole('menuitem')[0]!, { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: 'text style' }));
    expect(screen.getByRole('menu').style.visibility).not.toBe('hidden');
    fireEvent.keyDown(screen.getAllByRole('menuitemradio')[0]!, { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: 'link' }));
    expect(screen.getByRole('dialog', { name: 'edit link' }).style.visibility).not.toBe('hidden');
    expect(screen.getByLabelText('link address')).toHaveFocus();
  });

  it('an open panel is visible even before it is placed (its first frame)', () => {
    // No anchor → never placed: this is the style of the first open commit,
    // when the open-time focus runs.
    const { result } = renderHook(() => useAnchoredPanel(true, 200));
    expect(result.current.style.visibility).not.toBe('hidden');
    expect(result.current.style.position).toBe('fixed');
  });
});
