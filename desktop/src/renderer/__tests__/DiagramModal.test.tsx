import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, act } from '@testing-library/react';
import type { Editor } from '@tiptap/core';

const { renderMermaid } = vi.hoisted(() => ({ renderMermaid: vi.fn() }));
vi.mock('../lib/editor/mermaid-render', () => ({ renderMermaid }));

import { DiagramModal, clampScale } from '../components/DiagramModal';
import { RichMarkdownEditor } from '../components/RichMarkdownEditor';
import { emitGb } from '../lib/editor/events';

describe('DiagramModal', () => {
  beforeEach(() => {
    renderMermaid.mockReset();
    renderMermaid.mockResolvedValue({ ok: true, svg: '<svg data-testid="big"></svg>' });
  });

  it('renders the diagram full screen', async () => {
    render(<DiagramModal source="flowchart TD\nA-->B" onClose={() => {}} />);
    expect(await screen.findByTestId('big')).toBeInTheDocument();
    expect(screen.getByRole('dialog', { name: 'diagram' })).toBeInTheDocument();
  });

  it('zoom buttons scale; reset restores', async () => {
    render(<DiagramModal source="x" onClose={() => {}} />);
    const canvas = await screen.findByTestId('diagram-canvas');
    fireEvent.click(screen.getByLabelText('zoom in'));
    expect(canvas.style.transform).toContain('scale(1.25)');
    fireEvent.click(screen.getByLabelText('zoom out'));
    expect(canvas.style.transform).toContain('scale(1)');
    fireEvent.click(screen.getByLabelText('zoom in'));
    fireEvent.click(screen.getByLabelText('reset view'));
    expect(canvas.style.transform).toBe('translate(0px, 0px) scale(1)');
  });

  it('drag pans the canvas', async () => {
    render(<DiagramModal source="x" onClose={() => {}} />);
    const canvas = await screen.findByTestId('diagram-canvas');
    const stage = canvas.parentElement!;
    fireEvent.mouseDown(stage, { clientX: 10, clientY: 10 });
    fireEvent.mouseMove(stage, { clientX: 40, clientY: 30 });
    fireEvent.mouseUp(stage);
    expect(canvas.style.transform).toContain('translate(30px, 20px)');
  });

  it('Escape and the close button call onClose', async () => {
    const onClose = vi.fn();
    render(<DiagramModal source="x" onClose={onClose} />);
    fireEvent.keyDown(window, { key: 'Escape' });
    fireEvent.click(screen.getByLabelText('close diagram'));
    expect(onClose).toHaveBeenCalledTimes(2);
    await screen.findByTestId('big'); // let the async render settle inside act
  });

  it('Escape is stopped before outer window listeners (e.g. the note overlay) see it', async () => {
    const onClose = vi.fn();
    const outer = vi.fn();
    window.addEventListener('keydown', outer);
    try {
      render(<DiagramModal source="x" onClose={onClose} />);
      fireEvent.keyDown(screen.getByRole('dialog', { name: 'diagram' }), { key: 'Escape' });
      expect(onClose).toHaveBeenCalledTimes(1);
      expect(outer).not.toHaveBeenCalled();
      await screen.findByTestId('big');
    } finally {
      window.removeEventListener('keydown', outer);
    }
  });

  it('shows the error and source when rendering fails', async () => {
    renderMermaid.mockResolvedValue({ ok: false, error: 'Parse error' });
    render(<DiagramModal source="bad src" onClose={() => {}} />);
    expect(await screen.findByText(/Parse error/)).toBeInTheDocument();
    expect(screen.getByText('bad src')).toBeInTheDocument();
  });

  it('clampScale bounds and rounds', () => {
    expect(clampScale(0.01)).toBe(0.2);
    expect(clampScale(100)).toBe(8);
    expect(clampScale(1.23456)).toBe(1.23);
  });
});

describe('RichMarkdownEditor ↔ DiagramModal', () => {
  it('opens the modal on gb:diagram:open and closes on Escape', async () => {
    renderMermaid.mockResolvedValue({ ok: true, svg: '<svg data-testid="big"></svg>' });
    let editor: Editor | undefined;
    render(<RichMarkdownEditor markdown="text" onSave={() => {}} jotId="t" onEditorReady={(e) => { editor = e; }} />);
    act(() => emitGb(editor!, 'gb:diagram:open', { source: 'flowchart TD\nA-->B' }));
    expect(await screen.findByRole('dialog', { name: 'diagram' })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'diagram' })).toBeNull();
  });
});
