import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { ChangesScreen, dayKey } from '../screens/changes';
import { useNoteView } from '../stores/note-view';
import { useToasts } from '../stores/toast';
import type {
  ChangeDetailResponse,
  ChangesListResponse,
  ChangeSummary,
} from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);
const postMock = vi.mocked(client.post);
const delMock = vi.mocked(client.del);

const AI: ChangeSummary = {
  id: 2, ts: '2026-10-09T12:00:00+00:00', actor: 'assistant', path: '20-contexts/work/plan.md',
  destPath: null, op: 'modify', reason: 'polished intro', status: 'applied', riskReasons: [],
  resolvedTs: null,
};
const PLUGIN: ChangeSummary = {
  id: 1, ts: '2026-10-07T12:00:00+00:00', actor: 'plugin:familiar', path: 'Familiar/brief.md',
  destPath: null, op: 'create', reason: 'plugin write-back', status: 'reverted', riskReasons: [],
  resolvedTs: '2026-10-08T12:00:00+00:00',
};
const DETAIL: ChangeDetailResponse = {
  ...AI, before: 'old intro', after: 'new intro', current: 'typed since', changedSince: true,
  diff: '',
};

function list(over: Partial<ChangesListResponse> = {}): ChangesListResponse {
  return { items: [AI, PLUGIN], pendingCount: 0, degraded: false, ...over };
}

function setup(
  listResponse: ChangesListResponse = list(),
  detail: () => Promise<ChangeDetailResponse> = async () => DETAIL,
) {
  getMock.mockImplementation(async (path: string) => {
    if (path.startsWith('/v1/changes?')) return listResponse;
    if (path === '/v1/changes/2') return detail();
    throw new Error(`unexpected GET ${path}`);
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ChangesScreen />
    </QueryClientProvider>,
  );
}

const messages = () => useToasts.getState().toasts.map((t) => t.message);

afterEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  delMock.mockReset();
  useToasts.setState({ toasts: [] });
  useNoteView.setState({ path: null });
});

describe('ChangesScreen', () => {
  it('lists changes grouped by day with actor chips and reasons', async () => {
    setup();
    expect(await screen.findByText('polished intro')).toBeInTheDocument();
    // Scoped to the rows: the "✦ assistant" filter chip carries the same label.
    expect(within(screen.getByTestId('change-2')).getByText('✦ assistant')).toBeInTheDocument();
    expect(within(screen.getByTestId('change-1')).getByText('⧉ familiar')).toBeInTheDocument();
    const day = screen.getByRole('region', { name: dayKey(AI.ts) });
    expect(within(day).getByText('polished intro')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: dayKey(PLUGIN.ts) })).toBeInTheDocument();
  });

  it('filters by actor kind and by path', async () => {
    setup();
    await screen.findByText('polished intro');
    expect(getMock).toHaveBeenCalledWith('/v1/changes?limit=200');
    fireEvent.click(screen.getByRole('button', { name: '⧉ plugins' }));
    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/v1/changes?limit=200&actor=plugin'));
    fireEvent.click(screen.getByRole('button', { name: 'all' }));
    fireEvent.change(screen.getByLabelText('filter by path'), { target: { value: 'plan' } });
    await waitFor(() => expect(getMock).toHaveBeenCalledWith('/v1/changes?limit=200&q=plan'));
  });

  it('shows the per-change diff on demand', async () => {
    setup();
    const row = await screen.findByTestId('change-2');
    fireEvent.click(within(row).getByRole('button', { name: 'diff' }));
    const diff = await screen.findByTestId('change-diff-2');
    expect(diff).toHaveTextContent('- old intro');
    expect(diff).toHaveTextContent('+ new intro');
  });

  it('reverts with one click', async () => {
    postMock.mockResolvedValue({ id: 2, status: 'reverted', path: AI.path, etag: 'e' });
    setup();
    const row = await screen.findByTestId('change-2');
    fireEvent.click(within(row).getByRole('button', { name: 'revert' }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/v1/changes/2/revert', { force: false }));
    await waitFor(() => expect(messages().some((m) => m.includes('reverted'))).toBe(true));
  });

  it('asks before reverting a note that changed since, then forces', async () => {
    postMock
      .mockRejectedValueOnce(new client.ApiError('the note changed since this change', 409))
      .mockResolvedValueOnce({ id: 2, status: 'reverted', path: AI.path, etag: 'e' });
    setup();
    const row = await screen.findByTestId('change-2');
    fireEvent.click(within(row).getByRole('button', { name: 'revert' }));
    const prompt = await within(row).findByRole('alert');
    expect(prompt).toHaveTextContent('changed since');
    const drift = await screen.findByTestId('change-drift-2');
    expect(drift).toHaveTextContent('+ typed since');
    fireEvent.click(within(row).getByRole('button', { name: 'revert anyway' }));
    await waitFor(() => expect(postMock).toHaveBeenLastCalledWith('/v1/changes/2/revert', { force: true }));
  });

  it('keeps "revert anyway" disabled until the drift has loaded', async () => {
    postMock.mockRejectedValueOnce(new client.ApiError('the note changed since this change', 409));
    let release: (d: ChangeDetailResponse) => void = () => {};
    setup(list(), () => new Promise<ChangeDetailResponse>((resolve) => { release = resolve; }));
    const row = await screen.findByTestId('change-2');
    fireEvent.click(within(row).getByRole('button', { name: 'revert' }));
    const prompt = await within(row).findByRole('alert');
    expect(prompt).toHaveTextContent('loading…');
    expect(within(row).getByRole('button', { name: 'revert anyway' })).toBeDisabled();
    release(DETAIL);
    expect(await screen.findByTestId('change-drift-2')).toHaveTextContent('+ typed since');
    expect(within(row).getByRole('button', { name: 'revert anyway' })).toBeEnabled();
  });

  it('shows why the drift could not load and keeps "revert anyway" disabled', async () => {
    postMock.mockRejectedValueOnce(new client.ApiError('the note changed since this change', 409));
    setup(list(), async () => {
      throw new client.ApiError('change log unavailable', 503);
    });
    const row = await screen.findByTestId('change-2');
    fireEvent.click(within(row).getByRole('button', { name: 'revert' }));
    const prompt = await within(row).findByRole('alert');
    await waitFor(() => expect(prompt).toHaveTextContent('change log unavailable'));
    expect(within(row).getByRole('button', { name: 'revert anyway' })).toBeDisabled();
  });

  it('a reverted row offers undo', async () => {
    postMock.mockResolvedValue({ id: 1, status: 'applied', path: PLUGIN.path, etag: 'e' });
    setup();
    const row = await screen.findByTestId('change-1');
    expect(within(row).getByText('reverted')).toBeInTheDocument();
    expect(within(row).queryByRole('button', { name: 'revert' })).toBeNull();
    fireEvent.click(within(row).getByRole('button', { name: 'undo' }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/v1/changes/1/undo', { force: false }));
  });

  it('warns when the change log missed something, and can dismiss it', async () => {
    delMock.mockResolvedValue(null);
    setup(list({ degraded: true }));
    expect(await screen.findByText('some changes may be missing; see page history')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'dismiss' }));
    await waitFor(() => expect(delMock).toHaveBeenCalledWith('/v1/changes/degraded'));
  });

  it('opens the note when its path is clicked', async () => {
    setup();
    fireEvent.click(await screen.findByRole('button', { name: AI.path }));
    expect(useNoteView.getState().path).toBe(AI.path);
  });

  it('shows an empty state', async () => {
    setup(list({ items: [] }));
    expect(await screen.findByText('nothing has changed your notes yet')).toBeInTheDocument();
  });

  it('shows held changes above the history and keeps them out of it', async () => {
    const held: ChangeSummary = {
      ...AI, id: 9, status: 'pending', riskReasons: ['edits a template'], reason: 'held one',
    };
    setup(list({ items: [held, AI, PLUGIN], pendingCount: 1 }));
    expect(await screen.findByTestId('pending-9')).toBeInTheDocument();
    expect(screen.queryByTestId('change-9')).toBeNull();
    expect(screen.getByTestId('change-2')).toBeInTheDocument();
  });
});
