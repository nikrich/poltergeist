import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '../lib/api/client';
import { WhatsAppChatPicker } from '../components/WhatsAppChatPicker';
import type { VaultContexts, WhatsAppChat } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});

const chats: WhatsAppChat[] = [
  { jid: 'g1@g.us', name: 'Book Club', kind: 'group', lastMessageAt: '2026-10-09T09:00:00+02:00', messageCount: 40, allowed: false, context: null },
  { jid: 'd1@s.whatsapp.net', name: 'Alex Example', kind: 'direct', lastMessageAt: '2026-10-08T09:00:00+02:00', messageCount: 12, allowed: true, context: 'work' },
];
const contexts: VaultContexts = { contexts: ['personal', 'work'], archived: [] };

function setup() {
  vi.mocked(client.get).mockImplementation(async (path: string) => {
    if (path === '/v1/connectors/whatsapp/chats') return chats;
    if (path === '/v1/vault/contexts') return contexts;
    throw new Error(`unexpected ${path}`);
  });
  vi.mocked(client.put).mockResolvedValue(chats);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <WhatsAppChatPicker />
    </QueryClientProvider>,
  );
}

describe('WhatsAppChatPicker', () => {
  beforeEach(() => vi.clearAllMocks());
  afterEach(() => vi.clearAllMocks());

  it('lists chats and filters by search and kind', async () => {
    setup();
    expect(await screen.findByText('Book Club')).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText('search chats'), { target: { value: 'alex' } });
    expect(screen.queryByText('Book Club')).toBeNull();
    expect(screen.getByText('Alex Example')).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText('search chats'), { target: { value: '' } });
    fireEvent.click(screen.getByRole('button', { name: 'groups' }));
    expect(screen.queryByText('Alex Example')).toBeNull();
  });

  it('saves only changed chats with their context', async () => {
    setup();
    fireEvent.click(await screen.findByLabelText('include Book Club'));
    fireEvent.change(screen.getByLabelText('context for Book Club'), { target: { value: 'work' } });
    fireEvent.click(screen.getByRole('button', { name: 'save' }));
    await waitFor(() => expect(client.put).toHaveBeenCalled());
    expect(client.put).toHaveBeenCalledWith('/v1/connectors/whatsapp/chats', {
      chats: { 'g1@g.us': { allowed: true, context: 'work' } },
    });
  });

  it('shows the access error from the sidecar', async () => {
    vi.mocked(client.get).mockImplementation(async (path: string) => {
      if (path === '/v1/vault/contexts') return contexts;
      throw new client.ApiError('Grant Full Disk Access', 409);
    });
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={qc}><WhatsAppChatPicker /></QueryClientProvider>);
    expect(await screen.findByText(/Full Disk Access/)).toBeTruthy();
  });

  it('shows a failed save', async () => {
    setup();
    vi.mocked(client.put).mockRejectedValue(new client.ApiError("unknown context: 'x'", 422));
    fireEvent.click(await screen.findByLabelText('include Book Club'));
    fireEvent.click(screen.getByRole('button', { name: 'save' }));
    expect(await screen.findByText(/unknown context: 'x'/)).toBeTruthy();
  });
});
