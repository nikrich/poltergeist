import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '../lib/api/client';
import { BACKFILL_CONNECTORS } from '../components/AccountBackfill';
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
const BASE = '/v1/connectors/gdrive/accounts/a%40x.com/backfill';

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
    updated: 7,
    tooLarge: 2,
    error: null,
    startedAt: '2026-09-28T10:00:00Z',
    updatedAt: '2026-09-28T11:00:00Z',
    monthsTotal: 36,
    monthsDone: 18,
    ...over,
  };
}

function setup(opts: {
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
      return Promise.resolve({ files: 5000, capped: true, since: '2023-09-28' });
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
        connector={detail('gdrive')}
        onAddAccount={vi.fn()}
        onReauth={onReauth}
      />
    </QueryClientProvider>,
  );
  return { onReauth };
}

describe('DriveBackfill', () => {
  const originalConfirm = window.confirm;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    window.confirm = originalConfirm;
  });

  it('opens the dialog with a capped estimate and starts a 3-year backfill', async () => {
    setup({});
    fireEvent.click(await screen.findByRole('button', { name: `backfill ${ACCOUNT}` }));
    expect(await screen.findByText(/~5,000\+ files you own or edited/)).toBeTruthy();
    expect((screen.getByLabelText('years to backfill') as HTMLSelectElement).value).toBe('3');
    expect(vi.mocked(client.get)).toHaveBeenCalledWith(`${BASE}/estimate?years=3`, expect.anything());
    fireEvent.click(screen.getByRole('button', { name: /start backfill/i }));
    await waitFor(() => expect(vi.mocked(client.post)).toHaveBeenCalledWith(BASE, { years: 3 }));
  });

  it('renders the running line with updated and too-large counters', async () => {
    window.confirm = vi.fn(() => true);
    setup({ backfill: state({}) });
    const row = await screen.findByTestId(`backfill-${ACCOUNT}`);
    expect(row.textContent).toContain('120 imported');
    expect(row.textContent).toContain('7 updated');
    expect(row.textContent).toContain('1 failed');
    expect(row.textContent).toContain('2 too large');
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

  it('shows an API-disabled 409 as the estimate line and still offers start', async () => {
    const enable =
      "Enable the Google Drive API in Google Cloud for your OAuth client's project " +
      '(APIs & Services → Library).';
    const { onReauth } = setup({
      estimate: () => Promise.reject(new client.ApiError(enable, 409)),
    });
    fireEvent.click(await screen.findByRole('button', { name: `backfill ${ACCOUNT}` }));
    expect(await screen.findByText(enable)).toBeTruthy();
    expect(screen.queryByRole('button', { name: `reauthorize ${ACCOUNT} for backfill` })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /start backfill/i }));
    await waitFor(() => expect(vi.mocked(client.post)).toHaveBeenCalledWith(BASE, { years: 3 }));
    expect(onReauth).not.toHaveBeenCalled();
  });

  it('shows needs re-auth with reauthorize on the running-state auth error', async () => {
    const { onReauth } = setup({ backfill: state({ status: 'error', error: 'needs re-auth' }) });
    fireEvent.click(
      await screen.findByRole('button', { name: `reauthorize backfill for ${ACCOUNT}` }),
    );
    expect(onReauth).toHaveBeenCalledWith(ACCOUNT);
    expect(screen.getByText(/backfill paused · needs re-auth/)).toBeTruthy();
  });

  it('offers backfill exactly for the connectors that have a dialog config', () => {
    expect([...BACKFILL_CONNECTORS].sort()).toEqual(['gdrive', 'gmail']);
  });

  it('dismisses a completed backfill with DELETE', async () => {
    setup({ backfill: state({ status: 'done', imported: 900 }) });
    expect(await screen.findByText('backfill complete · 900 imported')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: `dismiss backfill for ${ACCOUNT}` }));
    await waitFor(() => expect(vi.mocked(client.del)).toHaveBeenCalledWith(BASE));
  });
});
