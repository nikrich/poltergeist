import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { LinkGraph } from '../components/LinkGraph';
import { useGraphView } from '../stores/graph-view';
import { useNoteView } from '../stores/note-view';
import { toast } from '../stores/toast';
import type { EgoGraph, SuggestItem, VaultGraph } from '../../shared/api-types';

const ALPHA = '20-contexts/work/alpha.md';
const ALEX = '30-cross-context/people/alex.md';
const EGO: EgoGraph = {
  focus: ALPHA, depth: 2, truncated: false, indexing: false,
  nodes: [
    { path: ALPHA, title: 'Alpha', context: 'work', kind: 'decision', degree: 2, ghost: false, hop: 0 },
    { path: ALEX, title: 'Alex', context: '', kind: 'person', degree: 1, ghost: false, hop: 1 },
    { path: 'someday idea.md', title: 'Someday Idea', context: '', kind: 'note', degree: 1, ghost: true, hop: 1 },
  ],
  edges: [
    { source: ALPHA, target: ALEX, kind: 'wikilink', weight: 0.5 },
    { source: ALPHA, target: 'someday idea.md', kind: 'wikilink', weight: 0.5 },
  ],
};
const VAULT: VaultGraph = {
  nodes: [
    { path: ALPHA, title: 'Alpha', context: 'work', tags: [], x: 0, y: 0, degree: 1, updated: null, kind: 'decision' },
    { path: '20-contexts/work/beta.md', title: 'Beta', context: 'work', tags: [], x: 50, y: 0, degree: 1, updated: null, kind: 'note' },
  ],
  edges: [{ source: ALPHA, target: '20-contexts/work/beta.md', weight: 0.5, kind: 'wikilink' }],
  regions: [],
};
const MATCH: SuggestItem = {
  kind: 'page', label: 'Alpha plan', path: ALPHA, context: 'work', detail: '20-contexts/work/alpha', count: null,
};

const request = vi.fn();
const originalGetContext = HTMLCanvasElement.prototype.getContext;

function serve(ego: (path: string) => { ok: boolean; data?: unknown; error?: string; status?: number } = () => ({ ok: true, data: EGO })) {
  request.mockImplementation(async (_method: string, path: string) => {
    if (path.startsWith('/v1/vault/graph?focus=')) return ego(path);
    if (path === '/v1/vault/graph') return { ok: true, data: VAULT };
    if (path.startsWith('/v1/vault/suggest')) return { ok: true, data: { items: [MATCH], indexing: false } };
    return { ok: false, error: `unexpected ${path}`, status: 500 };
  });
}

beforeEach(() => {
  request.mockReset();
  useGraphView.getState().reset();
  useNoteView.getState().close();
  window.gb = { ...window.gb, api: { request } } as typeof window.gb;
  HTMLCanvasElement.prototype.getContext = vi.fn(() => null) as unknown as typeof HTMLCanvasElement.prototype.getContext;
});

afterEach(() => {
  vi.restoreAllMocks();
  HTMLCanvasElement.prototype.getContext = originalGetContext;
});

function renderGraph() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><LinkGraph /></QueryClientProvider>);
}

const egoUrl = (path: string, depth = 2) => `/v1/vault/graph?focus=${encodeURIComponent(path)}&depth=${depth}`;

describe('LinkGraph', () => {
  it('asks for a page when nothing is focused, then centres on the picked page', async () => {
    serve();
    renderGraph();
    expect(screen.getByText(/pick a page to centre the graph on/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox', { name: 'centre on page' }), { target: { value: 'alp' } });
    fireEvent.click(await screen.findByRole('button', { name: /Alpha plan/ }));
    await waitFor(() => expect(request).toHaveBeenCalledWith('GET', egoUrl(ALPHA)));
    expect(await screen.findByRole('button', { name: 'Alex' })).toBeInTheDocument();
  });

  it('clicking a node recentres, and back returns', async () => {
    serve();
    useGraphView.getState().recenter(ALPHA);
    renderGraph();
    fireEvent.click(await screen.findByRole('button', { name: 'Alex' }));
    expect(useGraphView.getState()).toMatchObject({ focus: ALEX, back: [ALPHA] });
    await waitFor(() => expect(request).toHaveBeenCalledWith('GET', egoUrl(ALEX)));
    fireEvent.click(screen.getByRole('button', { name: 'back' }));
    expect(useGraphView.getState().focus).toBe(ALPHA);
  });

  it('opens real notes in the viewer and says ghosts are not written yet', async () => {
    serve();
    const info = vi.spyOn(toast, 'info');
    useGraphView.getState().recenter(ALPHA);
    renderGraph();
    fireEvent.click(await screen.findByRole('button', { name: 'open Alex' }));
    expect(useNoteView.getState().path).toBe(ALEX);
    useNoteView.getState().close();
    fireEvent.click(screen.getByRole('button', { name: 'open Someday Idea' }));
    expect(info).toHaveBeenCalledWith('“Someday Idea” isn\'t written yet');
    expect(useNoteView.getState().path).toBeNull();
  });

  it('the depth slider refetches at the new depth', async () => {
    serve();
    useGraphView.getState().recenter(ALPHA);
    renderGraph();
    await screen.findByRole('button', { name: 'Alex' });
    fireEvent.change(screen.getByRole('slider', { name: 'depth' }), { target: { value: '3' } });
    await waitFor(() => expect(request).toHaveBeenCalledWith('GET', egoUrl(ALPHA, 3)));
  });

  it('says when the neighbourhood was truncated', async () => {
    serve(() => ({ ok: true, data: { ...EGO, truncated: true } }));
    useGraphView.getState().recenter(ALPHA);
    renderGraph();
    expect(await screen.findByText(/showing the nearest 300 pages/)).toBeInTheDocument();
  });

  it('shows indexing while the link index is cold', async () => {
    serve(() => ({ ok: true, data: { ...EGO, nodes: [], edges: [], indexing: true } }));
    useGraphView.getState().recenter(ALPHA);
    renderGraph();
    expect(await screen.findByText('indexing vault…')).toBeInTheDocument();
  });

  it('a page that no longer exists shows an error and back still works', async () => {
    serve((path) =>
      path.includes('gone.md') ? { ok: false, error: 'note not found', status: 404 } : { ok: true, data: EGO },
    );
    useGraphView.getState().recenter(ALPHA);
    useGraphView.getState().recenter('20-contexts/work/gone.md');
    renderGraph();
    expect(await screen.findByText(/not in the vault any more/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'back' }));
    expect(await screen.findByRole('button', { name: 'Alex' })).toBeInTheDocument();
  });

  it('whole-vault mode loads the vault graph and disables depth', async () => {
    serve();
    useGraphView.getState().recenter(ALPHA);
    renderGraph();
    fireEvent.click(screen.getByRole('button', { name: 'whole vault' }));
    await waitFor(() => expect(request).toHaveBeenCalledWith('GET', '/v1/vault/graph'));
    expect(await screen.findByText(/whole vault · 2 notes/)).toBeInTheDocument();
    expect(screen.getByRole('slider', { name: 'depth' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'whole vault' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('the legend hides and shows kinds', async () => {
    serve();
    useGraphView.getState().recenter(ALPHA);
    renderGraph();
    await screen.findByRole('button', { name: 'Alex' });
    fireEvent.click(screen.getByRole('button', { name: 'people' }));
    expect(screen.getByRole('button', { name: 'people' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.queryByRole('button', { name: 'Alex' })).toBeNull();
  });
});
