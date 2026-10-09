import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../components/docs/pdf', () => ({
  renderThumb: vi.fn(async () => {}),
  cancelRender: vi.fn(),
  loadPdf: vi.fn(async () => ({ numPages: 1, renderPage: vi.fn(async () => {}), pageSize: vi.fn(async () => ({ width: 100, height: 140 })) })),
}));
vi.mock('../lib/api/client', () => ({
  ApiError: class extends Error { status?: number },
  get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(),
}));

import * as client from '../lib/api/client';
import { DocsScreen } from '../screens/docs';
import { useDocs } from '../stores/docs';
import { DRAG_MIME, encodeDrag } from '../components/docs/tree-model';
import { doc, libraryFixture } from './fixtures/library';

function renderScreen(tree = libraryFixture()) {
  vi.mocked(client.get).mockImplementation(((path: string) => {
    if (path === '/v1/library/tree') return Promise.resolve(tree);
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
    useDocs.setState({ selection: null, uploads: [], quickOpen: false, viewModes: {}, treeCollapsed: false, inspectorCollapsed: false });
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

  it('dismisses an errored upload ghost', async () => {
    renderScreen();
    const target = await screen.findByTestId('folder-work/payments/specs');
    const big = new File(['x'], 'big.zip');
    Object.defineProperty(big, 'size', { value: 25_000_000 });
    fireEvent.drop(target, { dataTransfer: { files: [big], getData: () => '', types: ['Files'] } });
    // Ghosts render inside the folder view of the upload's target folder.
    act(() => useDocs.getState().select({ type: 'folder', ref: { context: 'work', project: 'payments', path: 'specs' } }));
    fireEvent.click(await screen.findByLabelText('dismiss big.zip'));
    expect(useDocs.getState().uploads).toEqual([]);
  });

  it('uploads at most 2 files at a time', async () => {
    renderScreen();
    const releases: Array<() => void> = [];
    vi.mocked(client.post).mockImplementation((() =>
      new Promise((res) => releases.push(() => res({ ...doc({}), duplicate: false })))) as never);
    const target = await screen.findByTestId('folder-work/payments/specs');
    const files = ['a', 'b', 'c'].map((n) => new File([n], `${n}.md`, { type: 'text/markdown' }));
    fireEvent.drop(target, { dataTransfer: { files, getData: () => '', types: ['Files'] } });
    await waitFor(() => expect(client.post).toHaveBeenCalledTimes(2));
    expect(useDocs.getState().uploads).toHaveLength(3);
    releases[0]?.();
    await waitFor(() => expect(client.post).toHaveBeenCalledTimes(3));
    releases[1]?.();
    releases[2]?.();
    await waitFor(() => expect(useDocs.getState().uploads).toHaveLength(0));
  });

  it('picks the first free "new folder" name', async () => {
    const tree = libraryFixture();
    tree.scopes.find((sc) => sc.project === 'payments')!.folders.push({ name: 'new folder', path: 'new folder', folders: [], docs: [] });
    renderScreen(tree);
    fireEvent.click(await screen.findByText('folder'));
    await waitFor(() => expect(client.post).toHaveBeenCalledWith('/v1/library/folders', { context: 'work', project: 'payments', path: 'new folder 2' }));
  });

  it('sends context, project and folder when a doc is drag-moved', async () => {
    renderScreen();
    const target = await screen.findByTestId('folder-work/payments/diagrams');
    const payload = encodeDrag({ type: 'doc', docId: 'aaaaaaaaaaaa' });
    fireEvent.drop(target, { dataTransfer: { files: [], getData: (m: string) => (m === DRAG_MIME ? payload : ''), types: [DRAG_MIME] } });
    await waitFor(() => expect(client.patch).toHaveBeenCalledWith('/v1/library/docs/aaaaaaaaaaaa', { context: 'work', project: 'payments', folder: 'diagrams' }));
  });

  it('falls back to the default view when the selected folder no longer exists', async () => {
    useDocs.setState({ selection: { type: 'folder', ref: { context: 'work', project: 'payments', path: 'gone' } } });
    renderScreen();
    expect(await screen.findByTestId('folder-view')).toBeTruthy();
    expect(screen.queryByText('your docs library is empty')).toBeNull();
    await waitFor(() => expect(useDocs.getState().selection).toBeNull());
  });

  it('defaults to the first scope when the vault has no projects', async () => {
    const tree = libraryFixture();
    tree.scopes = tree.scopes.filter((sc) => !sc.project);
    renderScreen(tree);
    expect(await screen.findByTestId('folder-view')).toBeTruthy();
    expect(screen.queryByText('your docs library is empty')).toBeNull();
    expect((screen.getAllByRole('button', { name: /upload/ })[0] as HTMLButtonElement).disabled).toBe(false);
  });

  it('shows the empty state only when there are no scopes at all', async () => {
    renderScreen({ scopes: [], attention: [] });
    expect(await screen.findByText('your docs library is empty')).toBeTruthy();
    expect((screen.getAllByRole('button', { name: /upload/ })[0] as HTMLButtonElement).disabled).toBe(true);
  });

  describe('collapsible panes', () => {
    it('collapses and expands the tree via buttons and persists', async () => {
      renderScreen();
      await screen.findByText('Payments');
      fireEvent.click(screen.getByLabelText('collapse docs tree'));
      expect(useDocs.getState().treeCollapsed).toBe(true);
      expect(JSON.parse(localStorage.getItem('gb.docs.panes')!).treeCollapsed).toBe(true);
      expect(screen.queryByLabelText('collapse docs tree')?.closest('aside')?.className).toContain('hidden');
      expect(screen.getByLabelText('upload')).toBeTruthy();
      fireEvent.click(screen.getByLabelText('expand docs tree'));
      expect(useDocs.getState().treeCollapsed).toBe(false);
      expect(screen.queryByLabelText('expand docs tree')).toBeNull();
    });

    it('collapses the inspector to a rail only when a doc is selected', async () => {
      renderScreen();
      await screen.findByText('Payments');
      expect(screen.queryByLabelText('collapse inspector')).toBeNull();
      expect(screen.queryByLabelText('expand inspector')).toBeNull();
      useDocs.setState({ inspectorCollapsed: true });
      expect(screen.queryByLabelText('expand inspector')).toBeNull(); // no doc: no rail
      fireEvent.click(await screen.findByText('Payments API v2'));
      fireEvent.click(await screen.findByLabelText('expand inspector'));
      fireEvent.click(await screen.findByLabelText('collapse inspector'));
      expect(useDocs.getState().inspectorCollapsed).toBe(true);
      await screen.findByText(/\/ 1/);
    });

    it('toggles with mod+\\ and mod+alt+\\, ignoring typing targets', async () => {
      renderScreen();
      await screen.findByText('Payments');
      fireEvent.keyDown(window, { key: '\\', metaKey: true });
      expect(useDocs.getState().treeCollapsed).toBe(true);
      fireEvent.keyDown(window, { key: '\\', ctrlKey: true });
      expect(useDocs.getState().treeCollapsed).toBe(false);
      fireEvent.keyDown(window, { key: '«', code: 'Backslash', metaKey: true, altKey: true });
      expect(useDocs.getState().inspectorCollapsed).toBe(true);
      expect(useDocs.getState().treeCollapsed).toBe(false);
      const input = document.createElement('input');
      document.body.appendChild(input);
      fireEvent.keyDown(input, { key: '\\', metaKey: true });
      expect(useDocs.getState().treeCollapsed).toBe(false);
      input.remove();
    });
  });
});
