import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { BacklinksPanel } from '../components/BacklinksPanel';

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  apiRequest.mockResolvedValue({
    ok: true,
    data: { items: [{ path: 's.md', title: 'Standup', context: 'work', snippet: '' }], indexing: false },
  });
  window.gb = { ...window.gb, api: { request: apiRequest } };
});

function withQuery(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe('BacklinksPanel controlled (A7)', () => {
  it('stays closed when the parent says so and reports toggles', async () => {
    const onOpenChange = vi.fn();
    render(withQuery(<BacklinksPanel path="n.md" onOpen={() => {}} open={false} onOpenChange={onOpenChange} />));
    const header = await screen.findByRole('button', { name: /backlinks/ });
    expect(header).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Standup')).toBeNull();
    fireEvent.click(header);
    expect(onOpenChange).toHaveBeenCalledWith(true);
  });

  it('shows the list when the parent opens it', async () => {
    render(withQuery(<BacklinksPanel path="n.md" onOpen={() => {}} open onOpenChange={() => {}} />));
    expect(await screen.findByText('Standup')).toBeInTheDocument();
  });

  it('without the props it is open by default, as before', async () => {
    render(withQuery(<BacklinksPanel path="n.md" onOpen={() => {}} />));
    expect(await screen.findByText('Standup')).toBeInTheDocument();
  });
});
