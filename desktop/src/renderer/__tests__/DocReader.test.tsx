import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const renderPage = vi.fn(async () => {});
const loadPdfMock = vi.fn(async (_url: string) => ({ numPages: 24, renderPage }));
vi.mock('../components/docs/pdf', () => ({
  loadPdf: (url: string) => loadPdfMock(url),
  renderThumb: vi.fn(async () => {}),
  cancelRender: vi.fn(),
}));

import { PdfViewer } from '../components/docs/PdfViewer';
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
    setup(doc({ kind: 'docx', original: 'a.docx', index_status: 'failed' }), 'x');
    expect(screen.getByText('index failed')).toBeTruthy();
  });

  it('shows indexing… while pending', () => {
    setup(doc({ kind: 'docx', original: 'a.docx', index_status: 'pending' }), 'x');
    expect(screen.getByText('indexing…')).toBeTruthy();
    expect(screen.queryByText('indexed')).toBeNull();
  });

  it('ignores Escape from text fields and prevented events', () => {
    const p = setup(doc({ kind: 'docx', original: 'a.docx' }), 'x');
    const ta = document.createElement('textarea');
    document.body.appendChild(ta);
    ta.focus();
    fireEvent.keyDown(ta, { key: 'Escape' });
    expect(p.onClose).not.toHaveBeenCalled();
    ta.remove();
    const ev = new KeyboardEvent('keydown', { key: 'Escape', cancelable: true });
    ev.preventDefault();
    act(() => { window.dispatchEvent(ev); });
    expect(p.onClose).not.toHaveBeenCalled();
  });
});

describe('PdfViewer url change', () => {
  it('clears a previous error when the url changes', async () => {
    loadPdfMock.mockRejectedValueOnce(new Error('boom'));
    const { rerender } = render(<PdfViewer url="gbdoc://doc/bad.pdf" />);
    await screen.findByText(/couldn't render this PDF/);
    rerender(<PdfViewer url="gbdoc://doc/good.pdf" />);
    await screen.findByText('/ 24');
    expect(screen.queryByText(/couldn't render this PDF/)).toBeNull();
  });
});
