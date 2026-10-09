import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../components/docs/pdf', () => ({
  renderThumb: vi.fn(async () => {}),
  cancelRender: vi.fn(),
  loadPdf: vi.fn(async () => ({ numPages: 1, renderPage: vi.fn(async () => {}) })),
}));
vi.mock('../lib/api/client', () => ({
  ApiError: class extends Error { status?: number },
  get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(),
}));

import * as client from '../lib/api/client';
import { DocsScreen } from '../screens/docs';
import { useDocs } from '../stores/docs';
import { doc, libraryFixture } from './fixtures/library';

function renderScreen() {
  vi.mocked(client.get).mockImplementation(((path: string) => {
    if (path === '/v1/library/tree') return Promise.resolve(libraryFixture());
    if (path.startsWith('/v1/library/docs/')) return Promise.resolve({ ...doc({}), body: 'body' });
    if (path.startsWith('/v1/library/search')) return Promise.resolve([doc({})]);
    return Promise.resolve([]);
  }) as never);
  vi.mocked(client.post).mockResolvedValue({ ...doc({ doc_id: 'ffffffffffff' }), duplicate: false } as never);
  vi.mocked(client.patch).mockResolvedValue(doc({}) as never);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><DocsScreen /></QueryClientProvider>);
}

describe('DocsScreen', () => {
  beforeEach(() => {
    // Node 25 ships a bare global localStorage that shadows jsdom's; use a stub.
    const mem = new Map<string, string>();
    vi.stubGlobal('localStorage', {
      getItem: (k: string) => mem.get(k) ?? null,
      setItem: (k: string, v: string) => void mem.set(k, v),
      removeItem: (k: string) => void mem.delete(k),
      clear: () => mem.clear(),
    });
    vi.clearAllMocks();
    useDocs.setState({ selection: null, uploads: [], quickOpen: false, viewModes: {} });
  });

  it('opens a doc from the tree into the reader + inspector', async () => {
    renderScreen();
    fireEvent.click(await screen.findByText('Payments API v2'));
    expect(await screen.findByText('document')).toBeTruthy();
    expect(screen.getByText('indexed')).toBeTruthy();
    // PDF viewer pager settles (mocked loadPdf -> 1 page); avoids act() warnings.
    await screen.findByText(/\/ 1/);
  });

  it('uploads dropped files as base64 into the target folder', async () => {
    renderScreen();
    const target = await screen.findByTestId('folder-work/payments/specs');
    const f = new File(['hello'], 'a.md', { type: 'text/markdown' });
    fireEvent.drop(target, { dataTransfer: { files: [f], getData: () => '', types: ['Files'] } });
    await waitFor(() => expect(client.post).toHaveBeenCalledWith('/v1/library/docs', {
      context: 'work', project: 'payments', folder: 'specs', name: 'a.md', mime: 'text/markdown', content_b64: btoa('hello'),
    }));
  });

  it('rejects files over the client cap without calling the API', async () => {
    renderScreen();
    const target = await screen.findByTestId('folder-work/payments/specs');
    const big = new File(['x'], 'big.zip');
    Object.defineProperty(big, 'size', { value: 25_000_000 });
    fireEvent.drop(target, { dataTransfer: { files: [big], getData: () => '', types: ['Files'] } });
    await waitFor(() => expect(useDocs.getState().uploads[0]?.status).toBe('error'));
    expect(client.post).not.toHaveBeenCalled();
  });

  it('opens quick open on Cmd+P and jumps to the picked doc', async () => {
    renderScreen();
    await screen.findByText('Payments');
    fireEvent.keyDown(window, { key: 'p', metaKey: true });
    fireEvent.change(await screen.findByPlaceholderText('find a doc…'), { target: { value: 'pay' } });
    // Results load async; Enter before they arrive would pick nothing.
    await waitFor(() => expect(screen.getAllByText('Payments API v2').length).toBeGreaterThan(1));
    fireEvent.keyDown(screen.getByPlaceholderText('find a doc…'), { key: 'Enter' });
    await waitFor(() => expect(useDocs.getState().selection).toEqual({ type: 'doc', docId: 'aaaaaaaaaaaa' }));
    await screen.findByText(/\/ 1/);
  });
});
