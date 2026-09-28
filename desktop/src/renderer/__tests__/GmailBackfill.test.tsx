import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '../lib/api/client';
import { ConnectorAccounts } from '../components/ConnectorAccounts';
import type {
  BackfillState,
  ConnectorAccount,
  ConnectorDetail,
  VaultContexts,
} from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return {
    ApiError: actual.ApiError,
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    del: vi.fn(),
  };
});

const ACCOUNT = 'a@x.com';
const BASE = '/v1/connectors/gmail/accounts/a%40x.com/backfill';

const contextsResponse: VaultContexts = { contexts: ['work'], archived: [] };

const account: ConnectorAccount = {
  id: ACCOUNT,
  context: 'work',
  enabled: true,
  health: { status: 'ok', checkedAt: null, lastSuccessAt: null, error: null },
};

function detail(id: string): ConnectorDetail {
  return {
    id,
    displayName: id,
    state: 'on',
    count: 0,
    lastSyncAt: null,
    account: null,
    throughput: null,
    error: null,
    scopes: [],
    pulls: [],
    vaultDestination: '',
    accounts: [account],
  };
}

function state(over: Partial<BackfillState>): BackfillState {
  return {
    account: ACCOUNT,
    status: 'running',
    since: '2023-09-28',
    cursor: '2025-03',
    pageToken: null,
    imported: 120,
    skipped: 4,
    failed: 1,
    error: null,
    startedAt: '2026-09-28T10:00:00Z',
    updatedAt: '2026-09-28T11:00:00Z',
    monthsTotal: 36,
    monthsDone: 18,
    ...over,
  };
}

function setup(opts: {
  connectorId?: string;
  backfill?: BackfillState | null;
  estimate?: (years: number) => unknown;
}) {
  const backfill = opts.backfill ?? null;
  vi.mocked(client.get).mockImplementation(((path: string) => {
    if (path === '/v1/vault/contexts') return Promise.resolve(contextsResponse);
    if (path === BASE) {
      return backfill === null
        ? Promise.reject(new client.ApiError('no backfill', 404))
        : Promise.resolve(backfill);
    }
    if (path.startsWith(`${BASE}/estimate?years=`)) {
      const years = Number(path.split('=')[1]);
      if (opts.estimate) return Promise.resolve(opts.estimate(years));
      return Promise.resolve({ threads: 1500, since: '2023-09-28' });
    }
    return Promise.resolve({});
  }) as never);
  vi.mocked(client.post).mockResolvedValue(state({}) as never);
  vi.mocked(client.del).mockResolvedValue({ ok: true } as never);
  const onReauth = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ConnectorAccounts
        connector={detail(opts.connectorId ?? 'gmail')}
        onAddAccount={vi.fn()}
        onReauth={onReauth}
      />
    </QueryClientProvider>,
  );
  return { onReauth };
}

describe('GmailBackfill', () => {
  const originalConfirm = window.confirm;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    window.confirm = originalConfirm;
  });

  it('shows no backfill button for non-gmail connectors', async () => {
    setup({ connectorId: 'outlook' });
    await screen.findByText(ACCOUNT);
    expect(screen.queryByRole('button', { name: `backfill ${ACCOUNT}` })).toBeNull();
    const paths = vi.mocked(client.get).mock.calls.map((c) => String(c[0]));
    expect(paths.some((p) => p.includes('/backfill'))).toBe(false);
  });

  it('renders nothing for the backfill area while the initial status fetch is pending', async () => {
    let rejectBackfill: (e: unknown) => void = () => {};
    const pending = new Promise((_resolve, reject) => {
      rejectBackfill = reject;
    });
    vi.mocked(client.get).mockImplementation(((path: string) => {
      if (path === '/v1/vault/contexts') return Promise.resolve(contextsResponse);
      if (path === BASE) return pending;
      return Promise.resolve({});
    }) as never);
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ConnectorAccounts connector={detail('gmail')} onAddAccount={vi.fn()} onReauth={vi.fn()} />
      </QueryClientProvider>,
    );
    await screen.findByText(ACCOUNT);
    expect(screen.queryByRole('button', { name: `backfill ${ACCOUNT}` })).toBeNull();
    expect(screen.queryByTestId(`backfill-${ACCOUNT}`)).toBeNull();

    rejectBackfill(new client.ApiError('no backfill', 404));
    expect(await screen.findByRole('button', { name: `backfill ${ACCOUNT}` })).toBeTruthy();
  });

  it('opens the dialog with an estimate and starts a 3-year backfill', async () => {
    setup({});
    fireEvent.click(await screen.findByRole('button', { name: `backfill ${ACCOUNT}` }));
    expect(
      await screen.findByText('~1,500 threads you took part in · roughly 2 h or more'),
    ).toBeTruthy();
    expect((screen.getByLabelText('years to backfill') as HTMLSelectElement).value).toBe('3');
    expect(vi.mocked(client.get)).toHaveBeenCalledWith(`${BASE}/estimate?years=3`, expect.anything());
    fireEvent.click(screen.getByRole('button', { name: /start backfill/i }));
    await waitFor(() => expect(vi.mocked(client.post)).toHaveBeenCalledWith(BASE, { years: 3 }));
  });

  it('shows an "under an hour" estimate below pace instead of "about 0 h"', async () => {
    setup({ estimate: () => ({ threads: 500, since: '2025-09-28' }) });
    fireEvent.click(await screen.findByRole('button', { name: `backfill ${ACCOUNT}` }));
    expect(
      await screen.findByText('~500 threads you took part in · under an hour at the current pace'),
    ).toBeTruthy();
  });

  it('refetches the estimate when the years change', async () => {
    setup({ estimate: (years) => ({ threads: years * 1000, since: '2021-09-28' }) });
    fireEvent.click(await screen.findByRole('button', { name: `backfill ${ACCOUNT}` }));
    await screen.findByText(/~3,000 threads/);
    fireEvent.change(screen.getByLabelText('years to backfill'), { target: { value: '5' } });
    expect(
      await screen.findByText('~5,000 threads you took part in · roughly 7 h or more'),
    ).toBeTruthy();
    expect(vi.mocked(client.get)).toHaveBeenCalledWith(`${BASE}/estimate?years=5`, expect.anything());
  });

  it('shows the scheduler-off message and hides start on 409', async () => {
    setup({});
    const msg = "Backfill needs the in-app scheduler. Enable 'Run scheduler in-app' in Settings.";
    vi.mocked(client.post).mockRejectedValue(new client.ApiError(msg, 409));
    fireEvent.click(await screen.findByRole('button', { name: `backfill ${ACCOUNT}` }));
    await screen.findByText(/threads you took part in/);
    fireEvent.click(screen.getByRole('button', { name: /start backfill/i }));
    expect(await screen.findByText(msg)).toBeTruthy();
    expect(screen.queryByRole('button', { name: /start backfill/i })).toBeNull();
  });

  it('is a modal dialog that takes focus and closes on Escape', async () => {
    setup({});
    fireEvent.click(await screen.findByRole('button', { name: `backfill ${ACCOUNT}` }));
    const dialog = await screen.findByRole('dialog', { name: `backfill ${ACCOUNT}` });
    expect(dialog.getAttribute('aria-modal')).toBe('true');
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    fireEvent.keyDown(window, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  });

  it('offers reauthorize instead of start when the estimate needs re-auth', async () => {
    const { onReauth } = setup({
      estimate: () => Promise.reject(new client.ApiError('needs re-auth', 409)),
    });
    fireEvent.click(await screen.findByRole('button', { name: `backfill ${ACCOUNT}` }));
    fireEvent.click(
      await screen.findByRole('button', { name: `reauthorize ${ACCOUNT} for backfill` }),
    );
    expect(onReauth).toHaveBeenCalledWith(ACCOUNT);
    expect(screen.queryByRole('button', { name: /start backfill/i })).toBeNull();
  });

  it('still allows starting when the estimate fails transiently', async () => {
    setup({ estimate: () => Promise.reject(new client.ApiError('Gmail unavailable', 502)) });
    fireEvent.click(await screen.findByRole('button', { name: `backfill ${ACCOUNT}` }));
    expect(await screen.findByText('Gmail unavailable')).toBeTruthy();
    const startBtn = screen.getByRole('button', { name: /start backfill/i }) as HTMLButtonElement;
    expect(startBtn.disabled).toBe(false);
    fireEvent.click(startBtn);
    await waitFor(() => expect(vi.mocked(client.post)).toHaveBeenCalledWith(BASE, { years: 3 }));
    expect(
      screen.queryByRole('button', { name: `reauthorize ${ACCOUNT} for backfill` }),
    ).toBeNull();
  });

  it('renders the running line with pause and cancel', async () => {
    window.confirm = vi.fn(() => true);
    setup({ backfill: state({}) });
    expect(
      await screen.findByText('backfilling · Mar 2025 · 120 imported · 4 already had · 1 failed'),
    ).toBeTruthy();
    expect(screen.queryByRole('button', { name: `backfill ${ACCOUNT}` })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: `pause backfill for ${ACCOUNT}` }));
    await waitFor(() => expect(vi.mocked(client.post)).toHaveBeenCalledWith(`${BASE}/pause`));
    fireEvent.click(screen.getByRole('button', { name: `cancel backfill for ${ACCOUNT}` }));
    await waitFor(() => expect(vi.mocked(client.del)).toHaveBeenCalledWith(BASE));
  });

  it('shows a transient retry hint while running', async () => {
    setup({ backfill: state({ error: 'HttpError' }) });
    expect(await screen.findByText('retrying after HttpError')).toBeTruthy();
  });

  it('resumes a paused backfill', async () => {
    setup({ backfill: state({ status: 'paused' }) });
    fireEvent.click(await screen.findByRole('button', { name: `resume backfill for ${ACCOUNT}` }));
    await waitFor(() => expect(vi.mocked(client.post)).toHaveBeenCalledWith(`${BASE}/resume`));
    expect(screen.getByRole('button', { name: `cancel backfill for ${ACCOUNT}` })).toBeTruthy();
    expect(screen.queryByRole('button', { name: `pause backfill for ${ACCOUNT}` })).toBeNull();
  });

  it('shows needs re-auth with reauthorize and resume on auth error', async () => {
    const { onReauth } = setup({ backfill: state({ status: 'error', error: 'needs re-auth' }) });
    fireEvent.click(
      await screen.findByRole('button', { name: `reauthorize backfill for ${ACCOUNT}` }),
    );
    expect(onReauth).toHaveBeenCalledWith(ACCOUNT);
    expect(screen.getByText(/backfill paused · needs re-auth/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: `resume backfill for ${ACCOUNT}` }));
    await waitFor(() => expect(vi.mocked(client.post)).toHaveBeenCalledWith(`${BASE}/resume`));
  });

  it('dismisses a completed backfill with DELETE', async () => {
    setup({ backfill: state({ status: 'done', imported: 900 }) });
    expect(await screen.findByText('backfill complete · 900 imported')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: `dismiss backfill for ${ACCOUNT}` }));
    await waitFor(() => expect(vi.mocked(client.del)).toHaveBeenCalledWith(BASE));
  });
});
