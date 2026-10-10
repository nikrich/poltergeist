import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { PendingChanges } from '../components/PendingChanges';
import { PENDING_CHANGES_PATH } from '../lib/api/hooks';
import { useToasts } from '../stores/toast';
import type { ChangeDetailResponse, ChangeSummary } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);
const postMock = vi.mocked(client.post);

const HELD: ChangeSummary = {
  id: 7, ts: '2026-10-10T09:00:00+00:00', actor: 'plugin:familiar',
  path: '90-meta/templates/standup.md', destPath: null, op: 'create', reason: 'plugin write-back',
  status: 'pending', riskReasons: ['edits a template'], resolvedTs: null,
};

const detailOf = (over: Partial<ChangeDetailResponse> = {}): ChangeDetailResponse => ({
  ...HELD, before: null, after: '# Standup', current: null, changedSince: false, diff: '', ...over,
});

function setup(
  items: ChangeSummary[],
  detail: Partial<ChangeDetailResponse> | (() => Promise<ChangeDetailResponse>) = {},
) {
  getMock.mockImplementation(async (path: string) => {
    if (path === PENDING_CHANGES_PATH) return { items, pendingCount: items.length, degraded: false };
    if (path === '/v1/changes/7') {
      return typeof detail === 'function' ? detail() : detailOf(detail);
    }
    throw new Error(`unexpected GET ${path}`);
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PendingChanges />
    </QueryClientProvider>,
  );
}

const messages = () => useToasts.getState().toasts.map((t) => t.message);

afterEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  useToasts.setState({ toasts: [] });
});

describe('PendingChanges', () => {
  it('lists held changes with the actor, the reasons and the proposed diff', async () => {
    setup([HELD]);
    const card = await screen.findByTestId('pending-7');
    expect(within(card).getByText('⧉ familiar')).toBeInTheDocument();
    expect(within(card).getByText('would create')).toBeInTheDocument();
    expect(within(within(card).getByRole('list', { name: 'why it waits' })).getByText('edits a template'))
      .toBeInTheDocument();
    expect(await screen.findByTestId('pending-diff-7')).toHaveTextContent('+ # Standup');
    expect(screen.getByText('- when proposed · + proposed')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'waiting for your approval' })).toBeInTheDocument();
  });

  it('renders nothing when nothing waits', async () => {
    setup([]);
    await waitFor(() => expect(getMock).toHaveBeenCalledWith(PENDING_CHANGES_PATH));
    expect(screen.queryByRole('region', { name: 'waiting for your approval' })).toBeNull();
  });

  it('approves', async () => {
    postMock.mockResolvedValue({ id: 7, status: 'applied', path: HELD.path, etag: 'e' });
    setup([HELD]);
    const card = await screen.findByTestId('pending-7');
    await screen.findByTestId('pending-diff-7');
    fireEvent.click(within(card).getByRole('button', { name: 'approve' }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/v1/changes/7/approve', { force: false }));
    await waitFor(() => expect(messages().some((m) => m.startsWith('approved'))).toBe(true));
  });

  it('a stale approval shows what changed and can be forced', async () => {
    postMock
      .mockRejectedValueOnce(new client.ApiError('the note changed since this was proposed', 409))
      .mockResolvedValueOnce({ id: 7, status: 'applied', path: HELD.path, etag: 'e' });
    setup([HELD], { current: 'the user wrote this', changedSince: true });
    const card = await screen.findByTestId('pending-7');
    await screen.findByTestId('pending-diff-7');
    fireEvent.click(within(card).getByRole('button', { name: 'approve' }));
    const alert = await within(card).findByRole('alert');
    expect(alert).toHaveTextContent('changed since');
    expect(await screen.findByTestId('pending-drift-7')).toHaveTextContent('+ the user wrote this');
    fireEvent.click(within(card).getByRole('button', { name: 'approve anyway' }));
    await waitFor(() => expect(postMock).toHaveBeenLastCalledWith('/v1/changes/7/approve', { force: true }));
  });

  it('rejects', async () => {
    postMock.mockResolvedValue({ id: 7, status: 'rejected' });
    setup([HELD]);
    const card = await screen.findByTestId('pending-7');
    fireEvent.click(within(card).getByRole('button', { name: 'reject' }));
    await waitFor(() => expect(postMock).toHaveBeenCalledWith('/v1/changes/7/reject'));
    await waitFor(() => expect(messages().some((m) => m.startsWith('rejected'))).toBe(true));
  });

  it('reports a failed approval', async () => {
    postMock.mockRejectedValue(new client.ApiError('history unavailable', 500));
    setup([HELD]);
    const card = await screen.findByTestId('pending-7');
    await screen.findByTestId('pending-diff-7');
    fireEvent.click(within(card).getByRole('button', { name: 'approve' }));
    await waitFor(() => expect(messages()).toContain('approve failed: history unavailable'));
  });

  it('only offers approve anyway once the drift has been re-read after the 409', async () => {
    let release: (d: ChangeDetailResponse) => void = () => {};
    let calls = 0;
    postMock.mockRejectedValueOnce(new client.ApiError('the note changed since this was proposed', 409));
    setup([HELD], () => {
      calls += 1;
      if (calls === 1) return Promise.resolve(detailOf());
      return new Promise<ChangeDetailResponse>((resolve) => {
        release = resolve;
      });
    });
    const card = await screen.findByTestId('pending-7');
    await screen.findByTestId('pending-diff-7');
    fireEvent.click(within(card).getByRole('button', { name: 'approve' }));
    const alert = await within(card).findByRole('alert');
    await waitFor(() => expect(calls).toBe(2));
    expect(within(alert).getByRole('button', { name: 'approve anyway' })).toBeDisabled();
    expect(screen.queryByTestId('pending-drift-7')).toBeNull();
    expect(alert).toHaveTextContent('loading…');
    release(detailOf({ current: 'the user wrote this', changedSince: true }));
    expect(await screen.findByTestId('pending-drift-7')).toHaveTextContent('+ the user wrote this');
    expect(within(alert).getByRole('button', { name: 'approve anyway' })).toBeEnabled();
  });

  it('keeps approve anyway off when the drift cannot be re-read', async () => {
    let calls = 0;
    postMock.mockRejectedValueOnce(new client.ApiError('the note changed since this was proposed', 409));
    setup([HELD], () => {
      calls += 1;
      if (calls === 1) return Promise.resolve(detailOf());
      return Promise.reject(new client.ApiError('history unavailable', 503));
    });
    const card = await screen.findByTestId('pending-7');
    await screen.findByTestId('pending-diff-7');
    fireEvent.click(within(card).getByRole('button', { name: 'approve' }));
    const alert = await within(card).findByRole('alert');
    await waitFor(() => expect(alert).toHaveTextContent("couldn't load what changed: history unavailable"));
    expect(screen.queryByTestId('pending-drift-7')).toBeNull();
    expect(within(alert).getByRole('button', { name: 'approve anyway' })).toBeDisabled();
  });

  it('keeps approve off until the proposed change can be shown', async () => {
    setup([HELD], () => Promise.reject(new client.ApiError('history unavailable', 503)));
    const card = await screen.findByTestId('pending-7');
    expect(within(card).getByRole('button', { name: 'approve' })).toBeDisabled();
    await waitFor(() =>
      expect(card).toHaveTextContent("couldn't load the proposed change: history unavailable"),
    );
    expect(screen.queryByTestId('pending-diff-7')).toBeNull();
    expect(within(card).getByRole('button', { name: 'approve' })).toBeDisabled();
    expect(within(card).getByRole('button', { name: 'reject' })).toBeEnabled();
  });
});
