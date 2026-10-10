import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import type { Editor } from '@tiptap/core';
import { RichMarkdownEditor } from '../components/RichMarkdownEditor';
import { getMarkdown } from '../lib/editor/markdown';
import { useSettings } from '../stores/settings';
import { textPos } from './helpers/editor';

afterEach(() => useSettings.setState({ pageWidth: 'fixed' }));

describe('RichMarkdownEditor page canvas (A7)', () => {
  it('renders the page header above the document inside the canvas', () => {
    render(
      <RichMarkdownEditor markdown="body" onSave={() => {}} jotId="t" pageHeader={<div data-testid="hdr">hdr</div>} />,
    );
    const canvas = screen.getByTestId('page-canvas');
    const hdr = screen.getByTestId('hdr');
    const pm = canvas.querySelector('.ProseMirror');
    expect(canvas).toContainElement(hdr);
    expect(pm).not.toBeNull();
    expect(hdr.compareDocumentPosition(pm!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('follows the page width setting; focus mode always uses the fixed measure', () => {
    useSettings.setState({ pageWidth: 'full' });
    const { rerender } = render(<RichMarkdownEditor markdown="body" onSave={() => {}} jotId="t" />);
    expect(screen.getByTestId('page-canvas')).toHaveAttribute('data-width', 'full');
    rerender(<RichMarkdownEditor markdown="body" onSave={() => {}} jotId="t" focus />);
    expect(screen.getByTestId('page-canvas')).toHaveAttribute('data-width', 'fixed');
  });

  it('keeps the header in source mode', () => {
    render(
      <RichMarkdownEditor markdown="body" onSave={() => {}} jotId="t" pageHeader={<div data-testid="hdr">hdr</div>} />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'src' }));
    expect(screen.getByTestId('hdr')).toBeInTheDocument();
    expect(screen.getByTestId('page-canvas')).toContainElement(screen.getByTestId('hdr'));
    expect(screen.queryByRole('toolbar', { name: 'formatting' })).toBeNull();
  });

  it('hides the toolbar when read-only', () => {
    render(<RichMarkdownEditor markdown="body" onSave={() => {}} jotId="t" readOnly />);
    expect(screen.queryByRole('toolbar', { name: 'formatting' })).toBeNull();
  });

  it('hides the table controls in focus mode (FocusBar is the only chrome)', () => {
    const md = 'intro\n\n| name | value |\n| --- | --- |\n| alpha | 1 |';
    let editor: Editor | undefined;
    const { rerender } = render(
      <RichMarkdownEditor markdown={md} onSave={() => {}} jotId="t" onEditorReady={(e) => { editor = e; }} />,
    );
    act(() => {
      editor!.commands.setTextSelection(textPos(editor!, 'alpha'));
    });
    expect(screen.getByRole('toolbar', { name: 'table controls' })).toBeInTheDocument();
    rerender(
      <RichMarkdownEditor markdown={md} onSave={() => {}} jotId="t" focus onEditorReady={(e) => { editor = e; }} />,
    );
    expect(screen.queryByRole('toolbar', { name: 'table controls' })).toBeNull();
  });

  it('inserts a picked image file into the page', async () => {
    let editor: Editor | undefined;
    render(
      <RichMarkdownEditor
        markdown="body"
        onSave={() => {}}
        jotId="j1"
        onEditorReady={(e) => {
          editor = e;
        }}
      />,
    );
    const file = new File([new Uint8Array([1, 2, 3])], 'shot.png', { type: 'image/png' });
    fireEvent.change(screen.getByTestId('image-picker'), { target: { files: [file] } });
    await waitFor(() =>
      expect(getMarkdown(editor!)).toContain('90-meta/assets/jots/2026/06/stub-x.jpg'),
    );
  });
});
