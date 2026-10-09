import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const renderPage = vi.fn(async () => {});
vi.mock('../components/docs/pdf', () => ({
  loadPdf: vi.fn(async () => ({ numPages: 24, renderPage })),
  renderThumb: vi.fn(async () => {}),
  cancelRender: vi.fn(),
}));

import { DocReader } from '../components/docs/DocReader';
import { doc } from './fixtures/library';

function setup(d = doc({}), body?: string) {
  const p = { doc: d, body, crumb: 'work / Payments / specs', onClose: vi.fn(), onOpenExternal: vi.fn(), onReveal: vi.fn(), onDelete: vi.fn() };
  render(<DocReader {...p} />);
  return p;
}

describe('DocReader', () => {
  it('renders pdfs page by page with a pager', async () => {
    setup();
    await waitFor(() => expect(screen.getByText('/ 24')).toBeTruthy());
    expect(renderPage).toHaveBeenLastCalledWith(expect.any(HTMLCanvasElement), 1, 1);
    fireEvent.click(screen.getByLabelText('next page'));
    await waitFor(() => expect(renderPage).toHaveBeenLastCalledWith(expect.any(HTMLCanvasElement), 2, 1));
  });

  it('renders images from gbdoc://', () => {
    setup(doc({ kind: 'image', original: 'a.png', original_path: '20-contexts/work/docs/a.png' }));
    expect(screen.getByRole('img').getAttribute('src')).toBe('gbdoc://doc/20-contexts/work/docs/a.png');
  });

  it('renders text-ish kinds from the extracted body', () => {
    setup(doc({ kind: 'docx', original: 'a.docx' }), 'Hello **world**');
    expect(screen.getByText('world').tagName).toBe('STRONG');
  });

  it('offers open-in for opaque files and closes on Escape', () => {
    const p = setup(doc({ kind: 'opaque', original: 'a.zip' }));
    fireEvent.click(screen.getAllByText(/open in/)[0]!);
    expect(p.onOpenExternal).toHaveBeenCalled();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(p.onClose).toHaveBeenCalled();
  });

  it('shows the indexing state pill', () => {
    setup(doc({ index_status: 'failed' }));
    expect(screen.getByText('index failed')).toBeTruthy();
  });
});
