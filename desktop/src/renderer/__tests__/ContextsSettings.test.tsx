import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '../lib/api/client';
import { ContextsSettings } from '../screens/settings';
import { useToasts } from '../stores/toast';
import type { VaultContexts } from '../../shared/api-types';

vi.mock('../lib/api/client', () => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}));

const contextsResponse: VaultContexts = {
  contexts: ['work', 'personal'],
  archived: ['agencyx'],
};

function renderSection() {
  vi.mocked(client.get).mockImplementation(((path: string) =>
    path === '/v1/vault/contexts' ? Promise.resolve(contextsResponse) : Promise.resolve({})) as never);
  vi.mocked(client.post).mockResolvedValue(contextsResponse as never);
  vi.mocked(client.del).mockResolvedValue(contextsResponse as never);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ContextsSettings />
    </QueryClientProvider>,
  );
}

describe('ContextsSettings', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    useToasts.setState({ toasts: [] });
  });

  it('renders active and archived contexts', async () => {
    renderSection();
    expect(await screen.findByText('work')).toBeTruthy();
    expect(screen.getByText('personal')).toBeTruthy();
    expect(screen.getByText(/archived/i)).toBeTruthy();
    expect(screen.getByText('agencyx')).toBeTruthy();
  });

  it('creates a context from the form, lower-cased', async () => {
    renderSection();
    await screen.findByText('work');
    fireEvent.change(screen.getByPlaceholderText(/context name/i), {
      target: { value: 'AgencyX' },
    });
    fireEvent.click(screen.getByRole('button', { name: /add context/i }));
    await waitFor(() =>
      expect(vi.mocked(client.post)).toHaveBeenCalledWith('/v1/vault/contexts', {
        name: 'agencyx',
      }),
    );
  });

  it('archives a context after confirm', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderSection();
    await screen.findByText('work');
    const archiveButtons = screen.getAllByRole('button', { name: /archive/i });
    fireEvent.click(archiveButtons[0]!);
    await waitFor(() =>
      expect(vi.mocked(client.del)).toHaveBeenCalledWith('/v1/vault/contexts/work'),
    );
  });

  it('does not archive when confirm is cancelled', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderSection();
    await screen.findByText('work');
    const archiveButtons = screen.getAllByRole('button', { name: /archive/i });
    fireEvent.click(archiveButtons[0]!);
    await waitFor(() => expect(window.confirm).toHaveBeenCalled());
    expect(vi.mocked(client.del)).not.toHaveBeenCalled();
  });

  it('restores an archived context', async () => {
    renderSection();
    await screen.findByText('agencyx');
    fireEvent.click(screen.getByRole('button', { name: /restore/i }));
    await waitFor(() =>
      expect(vi.mocked(client.post)).toHaveBeenCalledWith('/v1/vault/contexts', {
        name: 'agencyx',
      }),
    );
  });

  it('surfaces a toast on create failure and keeps the input', async () => {
    vi.mocked(client.get).mockImplementation(((path: string) =>
      path === '/v1/vault/contexts' ? Promise.resolve(contextsResponse) : Promise.resolve({})) as never);
    vi.mocked(client.post).mockRejectedValue(new Error('reserved name'));
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ContextsSettings />
      </QueryClientProvider>,
    );
    await screen.findByText('work');
    fireEvent.change(screen.getByPlaceholderText(/context name/i), {
      target: { value: 'needs_review' },
    });
    fireEvent.click(screen.getByRole('button', { name: /add context/i }));
    await waitFor(() =>
      expect(useToasts.getState().toasts.some((t) => /reserved name/.test(t.message))).toBe(true),
    );
    expect(screen.getByPlaceholderText(/context name/i)).toHaveValue('needs_review');
  });
});
