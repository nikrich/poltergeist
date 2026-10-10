import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { OntologyScreen } from '../screens/ontology';
import { useNoteView } from '../stores/note-view';
import { useOntologyView } from '../stores/ontology-view';
import { useToasts } from '../stores/toast';

const request = vi.fn();

const PROJECT = { uuid: 'p1', id: 'work/orbit', name: 'Orbit', context: 'work', seeds: ['Orbit'], bound: 1, pending_items: 2 };
const ITEMS = [
  { id: 1, type: 'binding', created: '2026-10-10', candidate: null,
    artefacts: [{ aid: 'a1', path: '20-contexts/work/a1.md', title: 'Kickoff' }] },
  { id: 2, type: 'candidate', created: '2026-10-10', artefacts: [],
    candidate: { id: 7, kind: 'Rule', name: 'lapse day', statement: 'Today lapse is day 31.', value: '31',
      confidence: 0.8, evidence: [{ aid: 'a1', path: '20-contexts/work/a1.md', title: 'Kickoff', quote: 'day 31', locator: '' }] } },
];

const SCOPE_ITEM = { id: 3, type: 'scope', created: '2026-10-10', candidate: null, artefacts: [],
  scope: { topic_uid: 't1', name: 'claims triage', lean: 'not_about',
    notes: [{ aid: 'n1', path: '20-contexts/work/n1.md', title: 'N1', reason: 'r' },
            { aid: 'n2', path: '20-contexts/work/n2.md', title: 'N2', reason: 'r' }] } };
const TOPICS = [
  { uid: 'c', name: 'Orbit', status: 'in', notes: 3 },
  { uid: 'b', name: 'billing', status: 'out', notes: 2 },
];

const GRAPH = {
  focus: 'n1', depth: 2, truncated: false,
  nodes: [
    { path: 'n1', title: 'Orbit', context: 'work', kind: 'project', degree: 1, ghost: false, hop: 0, note_path: null },
    { path: 'n2', title: 'lapse day', context: 'work', kind: 'rule', degree: 1, ghost: false, hop: 1, note_path: null },
  ],
  edges: [{ source: 'n1', target: 'n2', weight: 1, kind: 'HAS_RULE' }],
};

const NODE = {
  uid: 'n2', kind: 'rule', name: 'lapse day', statement: 'Lapse happens on day 31.', value: '31',
  provenance: 'extracted', ratified_at: '2026-10-10T08:00:00Z', note_path: null,
  generated_note_path: '20-contexts/work/projects/orbit/ontology/rule/n2-lapse-day.md',
  evidence: [{ aid: 'a1', note_path: '20-contexts/work/a1.md', title: 'Kickoff', quote: 'day 31', locator: '' }],
  relations: [{ direction: 'out', type: 'DEPENDS_ON', uid: 'n3', name: 'grace period', kind: 'decision' }],
};
const NODE3 = { ...NODE, uid: 'n3', kind: 'decision', name: 'grace period', statement: 'Grace is 30 days.',
  evidence: [], relations: [], generated_note_path: null };

function route(method: string, path: string) {
  if (path === '/v1/ontology/status') return { available: true, reason: null };
  if (path === '/v1/ontology/projects') return [PROJECT];
  if (path === '/v1/projects') return [];
  if (path.startsWith('/v1/ontology/backlog?')) return [SCOPE_ITEM, ...ITEMS];
  if (path === '/v1/ontology/projects/p1/topics') return TOPICS;
  if (path.startsWith('/v1/ontology/graph?')) return GRAPH;
  if (path === '/v1/ontology/nodes/n2') return NODE;
  if (path === '/v1/ontology/nodes/n3') return NODE3;
  if (path.startsWith('/v1/ontology/projects/p1/extract')) return { running: false, project: null, summary: null, last_error: null };
  if (method === 'POST' && path.startsWith('/v1/ontology/backlog/')) return { ok: true, seq: 5 };
  return null;
}

beforeEach(() => {
  request.mockReset();
  request.mockImplementation(async (method: string, path: string) => ({ ok: true, data: route(method, path) }));
  useOntologyView.getState().reset();
  useNoteView.setState({ path: null });
  useToasts.setState({ toasts: [] });
  window.gb = { ...window.gb, api: { request } } as typeof window.gb;
});

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><OntologyScreen /></QueryClientProvider>);
}

describe('OntologyScreen', () => {
  it('lists binding and candidate items for the selected project', async () => {
    renderScreen();
    expect(await screen.findByText('lapse day')).toBeInTheDocument();
    expect(screen.getByText(/1 notes look like Orbit/i)).toBeInTheDocument();
    expect(screen.getAllByText(/day 31/).length).toBeGreaterThan(0);
  });

  it('ratifies a candidate with an edited value', async () => {
    renderScreen();
    const input = await screen.findByLabelText('value for lapse day');
    fireEvent.change(input, { target: { value: '30' } });
    fireEvent.click(screen.getByRole('button', { name: 'ratify lapse day' }));
    await waitFor(() =>
      expect(request).toHaveBeenCalledWith('POST', '/v1/ontology/backlog/2/action', { action: 'ratify', value: '30' }),
    );
  });

  it('shows the unavailable reason', async () => {
    request.mockImplementation(async (_m: string, path: string) => ({
      ok: true, data: path === '/v1/ontology/status' ? { available: false, reason: 'locked by another process' } : [],
    }));
    renderScreen();
    expect(await screen.findByText(/locked by another process/)).toBeInTheDocument();
  });

  const failActions = (status: number, error: string) =>
    request.mockImplementation(async (method: string, path: string) =>
      method === 'POST' && path.startsWith('/v1/ontology/backlog/')
        ? { ok: false, error, status }
        : { ok: true, data: route(method, path) });

  it('sends one POST on a double-click ratify', async () => {
    renderScreen();
    const btn = await screen.findByRole('button', { name: 'ratify lapse day' });
    fireEvent.click(btn);
    fireEvent.click(btn);
    await waitFor(() => expect(request.mock.calls.filter(([m, p]) => m === 'POST' && String(p).includes('/action'))).toHaveLength(1));
  });

  it('toasts an error when a reject fails', async () => {
    failActions(500, 'boom');
    renderScreen();
    fireEvent.click(await screen.findByRole('button', { name: 'reject lapse day' }));
    await waitFor(() => expect(useToasts.getState().toasts.some((t) => t.kind === 'error' && t.message === 'boom')).toBe(true));
  });

  it('does not show an error toast on a 409 ratify', async () => {
    failActions(409, 'already decided');
    renderScreen();
    fireEvent.click(await screen.findByRole('button', { name: 'ratify lapse day' }));
    await waitFor(() => expect(useToasts.getState().toasts.length).toBeGreaterThan(0));
    expect(useToasts.getState().toasts.some((t) => t.kind === 'error')).toBe(false);
  });

  it('shows only the unavailable error, not the empty state', async () => {
    request.mockImplementation(async (_m: string, path: string) => ({
      ok: true, data: path === '/v1/ontology/status' ? { available: false, reason: 'locked' } : [],
    }));
    renderScreen();
    expect(await screen.findByText(/locked/)).toBeInTheDocument();
    expect(screen.queryByText('no project has an ontology yet')).toBeNull();
  });

  it('ratifies a binding with an unticked artefact excluded', async () => {
    const two = [{ ...ITEMS[0]!, artefacts: [
      { aid: 'a1', path: 'p/a1.md', title: 'Kickoff' }, { aid: 'a2', path: 'p/a2.md', title: 'Retro' }] }];
    request.mockImplementation(async (method: string, path: string) => ({
      ok: true, data: path.startsWith('/v1/ontology/backlog?') ? two : route(method, path) }));
    renderScreen();
    fireEvent.click(await screen.findByLabelText('include Kickoff'));
    fireEvent.click(screen.getByRole('button', { name: 'ratify binding 1' }));
    await waitFor(() =>
      expect(request).toHaveBeenCalledWith('POST', '/v1/ontology/backlog/1/action', { action: 'ratify', exclude: ['a1'] }));
  });

  it('renders the graph canvas on the graph tab', async () => {
    renderScreen();
    fireEvent.click(await screen.findByRole('tab', { name: 'graph' }));
    expect(await screen.findByLabelText('ontology graph')).toBeInTheDocument();
  });

  it('says when the ontology graph was truncated', async () => {
    request.mockImplementation(async (method: string, path: string) => ({
      ok: true, data: path.startsWith('/v1/ontology/graph?') ? { ...GRAPH, truncated: true } : route(method, path) }));
    renderScreen();
    fireEvent.click(await screen.findByRole('tab', { name: 'graph' }));
    expect(await screen.findByText(/showing the first 2 nodes — recentre to explore/)).toBeInTheDocument();
  });

  it('does not show the truncation note for a complete graph', async () => {
    renderScreen();
    fireEvent.click(await screen.findByRole('tab', { name: 'graph' }));
    await screen.findByLabelText('ontology graph');
    expect(screen.queryByText(/recentre to explore/)).toBeNull();
  });

  describe('node panel', () => {
    async function select(name: string) {
      renderScreen();
      fireEvent.click(await screen.findByRole('tab', { name: 'graph' }));
      fireEvent.click(await screen.findByRole('button', { name }));
    }

    it('shows the selected node without recentring', async () => {
      await select('lapse day');
      expect(await screen.findByText('Lapse happens on day 31.')).toBeInTheDocument();
      expect(useOntologyView.getState().selected).toBe('n2');
      expect(useOntologyView.getState().focus).toBeNull();
    });

    it('opens the source note when an evidence item is clicked', async () => {
      await select('lapse day');
      fireEvent.click(await screen.findByRole('button', { name: /day 31.*Kickoff/ }));
      expect(useNoteView.getState().path).toBe('20-contexts/work/a1.md');
    });

    it('opens the generated note and focuses from the panel', async () => {
      await select('lapse day');
      fireEvent.click(await screen.findByRole('button', { name: 'open note' }));
      expect(useNoteView.getState().path).toBe('20-contexts/work/projects/orbit/ontology/rule/n2-lapse-day.md');
      fireEvent.click(screen.getByRole('button', { name: 'focus' }));
      expect(useOntologyView.getState().focus).toBe('n2');
    });

    it('loads a related node when it is clicked, and closes', async () => {
      await select('lapse day');
      fireEvent.click(await screen.findByRole('button', { name: /grace period/ }));
      expect(await screen.findByText('Grace is 30 days.')).toBeInTheDocument();
      expect(useOntologyView.getState().selected).toBe('n3');
      fireEvent.click(screen.getByRole('button', { name: 'close details' }));
      expect(useOntologyView.getState().selected).toBeNull();
    });
  });

  describe('scope question', () => {
    it('asks the scope question and posts no', async () => {
      renderScreen();
      expect(await screen.findByText(/claims triage/)).toBeInTheDocument();
      expect(screen.getByText(/probably not/i)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'no claims triage' }));
      await waitFor(() => expect(request).toHaveBeenCalledWith('POST', '/v1/ontology/backlog/3/action', { action: 'no' }));
    });

    it('yes with an unticked note sends exclude', async () => {
      renderScreen();
      fireEvent.click(await screen.findByRole('button', { name: /show all 2/i }));
      fireEvent.click(screen.getByLabelText('include N2'));
      fireEvent.click(screen.getByRole('button', { name: 'yes claims triage' }));
      await waitFor(() =>
        expect(request).toHaveBeenCalledWith('POST', '/v1/ontology/backlog/3/action', { action: 'yes', exclude: ['n2'] }));
    });

    it('posts investigate for not sure', async () => {
      renderScreen();
      fireEvent.click(await screen.findByRole('button', { name: 'not sure claims triage' }));
      await waitFor(() =>
        expect(request).toHaveBeenCalledWith('POST', '/v1/ontology/backlog/3/action', { action: 'investigate' }));
    });

    it('opens a sample note', async () => {
      renderScreen();
      fireEvent.click(await screen.findByRole('button', { name: 'N1' }));
      expect(useNoteView.getState().path).toBe('20-contexts/work/n1.md');
    });
  });

  it('shows the boundary', async () => {
    renderScreen();
    expect(await screen.findByText(/boundary/i)).toBeInTheDocument();
    expect(await screen.findByText(/billing · 2/)).toBeInTheDocument();
  });
});
