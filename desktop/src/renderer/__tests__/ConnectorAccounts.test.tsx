import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '../lib/api/client';
import { ConnectorAccounts } from '../components/ConnectorAccounts';
import type { ConnectorAccount, ConnectorDetail, VaultContexts } from '../../shared/api-types';

vi.mock('../lib/api/client', () => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}));

const contextsResponse: VaultContexts = {
  contexts: ['work', 'personal', 'agencyx'],
  archived: ['acme'],
};

const accounts: ConnectorAccount[] = [
  {
    id: 'a@x.com',
    context: 'work',
    enabled: true,
    health: { status: 'ok', checkedAt: null, lastSuccessAt: null, error: null },
  },
  {
    id: 'b@x.com',
    context: null,
    enabled: true,
    health: { status: 'auth_required', checkedAt: null, lastSuccessAt: null, error: null },
  },
  {
    id: 'c@x.com',
    context: 'acme',
    enabled: false,
    health: { status: 'error', checkedAt: null, lastSuccessAt: null, error: 'boom 500' },
  },
  { id: 'd@x.com', context: 'personal', enabled: true, health: null },
];

function detail(accs: ConnectorAccount[] | undefined): ConnectorDetail {
  return {
    id: 'gmail',
    displayName: 'Gmail',
    state: 'on',
    count: 0,
    lastSyncAt: null,
    account: null,
    throughput: null,
    error: null,
    scopes: [],
    pulls: [],
    vaultDestination: '',
    accounts: accs,
  };
}

function renderAccounts(accs: ConnectorAccount[] | undefined) {
  vi.mocked(client.get).mockImplementation(((path: string) =>
    path === '/v1/vault/contexts'
      ? Promise.resolve(contextsResponse)
      : Promise.resolve({})) as never);
  vi.mocked(client.patch).mockResolvedValue({} as never);
  vi.mocked(client.del).mockResolvedValue(null as never);
  const onAddAccount = vi.fn();
  const onReauth = vi.fn();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ConnectorAccounts connector={detail(accs)} onAddAccount={onAddAccount} onReauth={onReauth} />
    </QueryClientProvider>,
  );
  return { onAddAccount, onReauth };
}

describe('ConnectorAccounts', () => {
  const originalConfirm = window.confirm;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  afterEach(() => {
    window.confirm = originalConfirm;
  });

  it('renders a row per account with health pills', async () => {
    renderAccounts(accounts);
    expect(screen.getByText('a@x.com')).toBeTruthy();
    expect(screen.getByText('b@x.com')).toBeTruthy();
    expect(screen.getByText('syncing')).toBeTruthy();
    expect(screen.getByText('needs re-auth')).toBeTruthy();
    expect(screen.getByText('error').getAttribute('title')).toBe('boom 500');
    expect(screen.getByText('not synced yet')).toBeTruthy();
  });

  it('renders the empty state with an add account button', () => {
    const { onAddAccount } = renderAccounts([]);
    expect(screen.getByText(/no accounts yet/i)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /add account/i }));
    expect(onAddAccount).toHaveBeenCalledTimes(1);
  });

  it('renders nothing when accounts is not an array', () => {
    renderAccounts(undefined);
    expect(screen.queryByRole('button', { name: /add account/i })).toBeNull();
  });

  it('sends the chosen context and null for unassigned', async () => {
    renderAccounts(accounts);
    const select = screen.getByLabelText('context for b@x.com') as HTMLSelectElement;
    await screen.findAllByRole('option', { name: 'agencyx' });
    fireEvent.change(select, { target: { value: 'agencyx' } });
    await waitFor(() =>
      expect(vi.mocked(client.patch)).toHaveBeenCalledWith(
        '/v1/connectors/gmail/accounts/b%40x.com',
        { context: 'agencyx' },
      ),
    );
    fireEvent.change(screen.getByLabelText('context for a@x.com'), { target: { value: '' } });
    await waitFor(() =>
      expect(vi.mocked(client.patch)).toHaveBeenCalledWith(
        '/v1/connectors/gmail/accounts/a%40x.com',
        { context: null },
      ),
    );
  });

  it('shows an archived stored context as "(archived)"', async () => {
    renderAccounts(accounts);
    const select = screen.getByLabelText('context for c@x.com') as HTMLSelectElement;
    const opt = await screen.findByRole('option', { name: 'acme (archived)' });
    expect((opt as HTMLOptionElement).value).toBe('acme');
    expect(select.value).toBe('acme');
  });

  it('toggles enabled off', async () => {
    renderAccounts(accounts);
    const row = screen.getByTestId('account-row-a@x.com');
    const toggle = row.querySelector('button[aria-pressed]') as HTMLButtonElement;
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(vi.mocked(client.patch)).toHaveBeenCalledWith(
        '/v1/connectors/gmail/accounts/a%40x.com',
        { enabled: false },
      ),
    );
  });

  it('removes an account after confirm', async () => {
    window.confirm = vi.fn(() => true);
    renderAccounts(accounts);
    fireEvent.click(screen.getByRole('button', { name: 'remove b@x.com' }));
    expect(window.confirm).toHaveBeenCalledWith(
      'Remove b@x.com? This deletes its stored credentials.',
    );
    await waitFor(() =>
      expect(vi.mocked(client.del)).toHaveBeenCalledWith(
        '/v1/connectors/gmail/credentials?account=b%40x.com',
      ),
    );
  });

  it('does nothing when remove is not confirmed', () => {
    window.confirm = vi.fn(() => false);
    renderAccounts(accounts);
    fireEvent.click(screen.getByRole('button', { name: 'remove b@x.com' }));
    expect(vi.mocked(client.del)).not.toHaveBeenCalled();
  });

  it('calls onAddAccount and onReauth', () => {
    const { onAddAccount, onReauth } = renderAccounts(accounts);
    fireEvent.click(screen.getByRole('button', { name: /add account/i }));
    expect(onAddAccount).toHaveBeenCalledTimes(1);
    const reauths = screen.getAllByRole('button', { name: /reauthorize/i });
    expect(reauths).toHaveLength(1);
    fireEvent.click(reauths[0]!);
    expect(onReauth).toHaveBeenCalledWith('b@x.com');
  });
});
