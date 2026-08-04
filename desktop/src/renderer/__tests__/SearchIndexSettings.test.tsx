import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import * as client from '../lib/api/client';
import { SearchIndexSettings } from '../screens/settings';
import type { SearchIndexStatus } from '../lib/api/hooks';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ...actual, get: vi.fn(), post: vi.fn() };
});

function renderSection(status: SearchIndexStatus) {
  vi.mocked(client.get).mockResolvedValue(status as never);
  vi.mocked(client.post).mockResolvedValue({ started: true } as never);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <SearchIndexSettings />
    </QueryClientProvider>,
  );
}

const TWO_DAYS_AGO = new Date(Date.now() - 2 * 24 * 60 * 60 * 1000).toISOString();

beforeEach(() => vi.clearAllMocks());

describe('SearchIndexSettings', () => {
  it('shows last-indexed time and note count', async () => {
    renderSection({
      lastIndexedAt: TWO_DAYS_AGO,
      noteCount: 4708,
      model: 'sentence-transformers/all-MiniLM-L6-v2',
      running: false,
    });
    expect(await screen.findByText(/4708 notes indexed/)).toBeTruthy();
    expect(screen.getByText(/2d ago/)).toBeTruthy();
  });

  it('triggers a reindex POST when the button is clicked', async () => {
    renderSection({ lastIndexedAt: TWO_DAYS_AGO, noteCount: 1, model: 'm', running: false });
    const btn = await screen.findByRole('button', { name: /reindex/i });
    fireEvent.click(btn);
    await waitFor(() =>
      expect(vi.mocked(client.post)).toHaveBeenCalledWith('/v1/search/reindex'),
    );
  });

  it('shows an indexing state and disables the button while running', async () => {
    renderSection({ lastIndexedAt: TWO_DAYS_AGO, noteCount: 1, model: 'm', running: true });
    expect(await screen.findAllByText(/indexing…/)).toBeTruthy();
    const btn = screen.getByRole('button', { name: /indexing/i });
    expect((btn as HTMLButtonElement).disabled).toBe(true);
  });
});
