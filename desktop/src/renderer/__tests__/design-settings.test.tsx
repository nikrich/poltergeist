import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '../lib/api/client';
import { LiveDesignSettings } from '../screens/settings';
import { useToasts } from '../stores/toast';
import type { DesignPack, DesignPackImportJob, DesignSettings } from '../../shared/design-types';

vi.mock('../lib/api/client', () => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
}));

const settings: DesignSettings = { listen: true, budget_usd: 2, default_pack: 'poltergeist-neutral', code_roots: ['~/development'], web: true };
let packs: DesignPack[];
let job: DesignPackImportJob;

function renderSection() {
  vi.mocked(client.get).mockImplementation(((path: string) => {
    if (path === '/v1/design/settings') return Promise.resolve(settings);
    if (path === '/v1/design/packs') return Promise.resolve(packs);
    if (path.startsWith('/v1/design/packs/import/')) return Promise.resolve(job);
    return Promise.reject(new Error(`unexpected GET ${path}`));
  }) as never);
  vi.mocked(client.put).mockImplementation(((_p: string, body: unknown) => Promise.resolve(body)) as never);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <LiveDesignSettings />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useToasts.setState({ toasts: [] });
  packs = [
    { id: 'poltergeist-neutral', name: 'Poltergeist neutral', source: 'builtin', imported_at: null, builtin: true },
    { id: 'acme', name: 'Acme', source: 'https://acme.design', imported_at: '2026-10-01', builtin: false },
  ];
  job = { id: 'job-1', source: '/Users/me/ds', status: 'running', message: 'Reading tokens', pack_id: null };
});

afterEach(() => {
  vi.useRealTimers();
});

describe('LiveDesignSettings', () => {
  it('toggles listening for spoken commands', async () => {
    renderSection();
    const toggle = await screen.findByRole('button', { name: /listen for spoken design commands/i });
    fireEvent.click(toggle);
    await waitFor(() =>
      expect(client.put).toHaveBeenCalledWith('/v1/design/settings', { ...settings, listen: false }),
    );
  });

  it('saves the budget per run on blur', async () => {
    renderSection();
    const input = await screen.findByLabelText(/budget per run/i);
    fireEvent.change(input, { target: { value: '3.5' } });
    fireEvent.blur(input);
    await waitFor(() =>
      expect(client.put).toHaveBeenCalledWith('/v1/design/settings', { ...settings, budget_usd: 3.5 }),
    );
  });

  it('picks the default design system', async () => {
    renderSection();
    await screen.findByRole('option', { name: 'Acme' });
    fireEvent.change(screen.getByLabelText(/default design system/i), { target: { value: 'acme' } });
    await waitFor(() =>
      expect(client.put).toHaveBeenCalledWith('/v1/design/settings', { ...settings, default_pack: 'acme' }),
    );
  });

  it('lists the library and only lets imported packs be deleted', async () => {
    vi.mocked(client.del).mockResolvedValue(null as never);
    renderSection();
    expect(await screen.findByText('Poltergeist neutral', { selector: 'div' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /delete poltergeist neutral/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /delete acme/i }));
    fireEvent.click(screen.getByRole('button', { name: /confirm delete acme/i }));
    await waitFor(() => expect(client.del).toHaveBeenCalledWith('/v1/design/packs/acme'));
  });

  it('imports a design system and polls the job until it is done', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.mocked(client.post).mockResolvedValue(job as never);
    renderSection();
    fireEvent.change(await screen.findByPlaceholderText(/claude design url/i), {
      target: { value: '/Users/me/ds' },
    });
    fireEvent.change(screen.getByPlaceholderText(/name \(optional\)/i), { target: { value: 'Mine' } });
    fireEvent.click(screen.getByRole('button', { name: /^import$/i }));
    await waitFor(() =>
      expect(client.post).toHaveBeenCalledWith('/v1/design/packs/import', {
        source: '/Users/me/ds',
        name: 'Mine',
      }),
    );
    expect(await screen.findByText(/reading tokens/i)).toBeInTheDocument();
    const polls = () =>
      vi.mocked(client.get).mock.calls.filter(([p]) => p === '/v1/design/packs/import/job-1').length;
    const before = polls();

    job = { ...job, status: 'done', message: null, pack_id: 'mine' };
    packs = [...packs, { id: 'mine', name: 'Mine', source: '/Users/me/ds', imported_at: '2026-10-10', builtin: false }];
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2_100);
    });
    await waitFor(() => expect(polls()).toBeGreaterThan(before));
    expect(await screen.findByText('Mine', { selector: 'div' })).toBeInTheDocument();
    const after = polls();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6_000);
    });
    expect(polls()).toBe(after); // stopped polling once done
  });

  it('shows the error when an import fails', async () => {
    vi.mocked(client.post).mockResolvedValue({ ...job, status: 'error', message: 'No tokens found' } as never);
    job = { ...job, status: 'error', message: 'No tokens found' };
    renderSection();
    fireEvent.change(await screen.findByPlaceholderText(/claude design url/i), {
      target: { value: 'https://figma.com/file/x' },
    });
    fireEvent.click(screen.getByRole('button', { name: /^import$/i }));
    expect(await screen.findByText(/no tokens found/i)).toBeInTheDocument();
  });
});
