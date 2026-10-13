import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { renderMermaid } = vi.hoisted(() => ({ renderMermaid: vi.fn() }));
vi.mock('../lib/editor/mermaid-render', () => ({ renderMermaid }));

import { ArchitectureView } from '../components/design/ArchitectureView';
import { sampleBoard } from './fixtures/design';

const SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 400" style="max-width: 800px;"><g></g></svg>';

let widthSpy: ReturnType<typeof vi.spyOn>;
let heightSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  renderMermaid.mockResolvedValue({ ok: true, svg: SVG });
  // jsdom has no layout: give the scroll viewport a size so "fit" has something to fit.
  widthSpy = vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(432);
  heightSpy = vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(0);
});

afterEach(() => {
  widthSpy.mockRestore();
  heightSpy.mockRestore();
});

async function renderView() {
  render(<ArchitectureView model={sampleBoard} />);
  await screen.findByRole('button', { name: /zoom in/i });
  return screen.getByLabelText('Architecture diagram').querySelector('svg')!;
}

const level = () => screen.getByRole('button', { name: /actual size/i }).textContent;

describe('ArchitectureView zoom', () => {
  it('opens fitted to the viewport width', async () => {
    const svg = await renderView();
    // (432 - 32px padding) / 800 = 50%
    expect(level()).toBe('50%');
    expect(svg.style.width).toBe('400px');
    expect(svg.style.maxWidth).toBe('none');
  });

  it('zooms in and out with the buttons, and back to 100%', async () => {
    const svg = await renderView();
    fireEvent.click(screen.getByRole('button', { name: /zoom in/i }));
    expect(level()).toBe('63%');
    fireEvent.click(screen.getByRole('button', { name: /zoom out/i }));
    fireEvent.click(screen.getByRole('button', { name: /zoom out/i }));
    expect(level()).toBe('40%');
    fireEvent.click(screen.getByRole('button', { name: /actual size/i }));
    expect(level()).toBe('100%');
    expect(svg.style.width).toBe('800px');
    fireEvent.click(screen.getByRole('button', { name: /fit/i }));
    expect(level()).toBe('50%');
  });

  it('zooms with ⌘/Ctrl + scroll (and trackpad pinch), not a plain scroll', async () => {
    await renderView();
    const viewport = screen.getByTestId('architecture-viewport');
    fireEvent.wheel(viewport, { deltaY: 100 });
    expect(level()).toBe('50%');
    fireEvent.wheel(viewport, { deltaY: -100, ctrlKey: true });
    expect(level()).not.toBe('50%');
    const zoomedIn = parseInt(level()!, 10);
    expect(zoomedIn).toBeGreaterThan(50);
    fireEvent.wheel(viewport, { deltaY: 100, metaKey: true });
    expect(parseInt(level()!, 10)).toBeLessThan(zoomedIn);
  });

  it('clamps zoom between 25% and 400%', async () => {
    await renderView();
    const zoomIn = screen.getByRole('button', { name: /zoom in/i });
    for (let i = 0; i < 20; i++) fireEvent.click(zoomIn);
    expect(level()).toBe('400%');
    const zoomOut = screen.getByRole('button', { name: /zoom out/i });
    for (let i = 0; i < 20; i++) fireEvent.click(zoomOut);
    expect(level()).toBe('25%');
  });

  it('shows no zoom controls when the diagram fails to draw', async () => {
    renderMermaid.mockResolvedValue({ ok: false, error: 'parse error' });
    render(<ArchitectureView model={sampleBoard} />);
    await screen.findByText(/couldn.t draw the architecture view/i);
    expect(screen.queryByRole('button', { name: /zoom in/i })).toBeNull();
  });

  it('keeps the zoom level when the board updates', async () => {
    const { rerender } = render(<ArchitectureView model={sampleBoard} />);
    await screen.findByRole('button', { name: /zoom in/i });
    fireEvent.click(screen.getByRole('button', { name: /actual size/i }));
    await act(async () => {
      rerender(<ArchitectureView model={{ ...sampleBoard, items: sampleBoard.items.slice(0, 2) }} />);
    });
    expect(level()).toBe('100%');
  });
});
