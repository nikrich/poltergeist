import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { PendingChangesBadge } from '../components/PendingChangesBadge';
import { PENDING_CHANGES_PATH } from '../lib/api/hooks';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);

function renderBadge(pendingCount: number) {
  getMock.mockResolvedValue({ items: [], pendingCount, degraded: false });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PendingChangesBadge />
    </QueryClientProvider>,
  );
}

afterEach(() => getMock.mockReset());

describe('PendingChangesBadge', () => {
  it('shows how many changes wait for approval', async () => {
    renderBadge(3);
    const badge = await screen.findByTestId('pending-changes-badge');
    expect(badge).toHaveTextContent('3');
    expect(badge).toHaveAttribute('aria-label', '3 changes waiting for approval');
    expect(getMock).toHaveBeenCalledWith(PENDING_CHANGES_PATH);
  });

  it('uses the singular for one', async () => {
    renderBadge(1);
    expect(await screen.findByTestId('pending-changes-badge')).toHaveAttribute(
      'aria-label',
      '1 change waiting for approval',
    );
  });

  it('caps the number', async () => {
    renderBadge(140);
    expect(await screen.findByTestId('pending-changes-badge')).toHaveTextContent('99+');
  });

  it('shows nothing when nothing waits', async () => {
    renderBadge(0);
    await waitFor(() => expect(getMock).toHaveBeenCalled());
    expect(screen.queryByTestId('pending-changes-badge')).toBeNull();
  });
});
