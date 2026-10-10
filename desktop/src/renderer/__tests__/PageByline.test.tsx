import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { PageByline } from '../components/page/PageByline';

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  window.gb = { ...window.gb, api: { request: apiRequest } };
});

function withQuery(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const twoLinks = {
  ok: true,
  data: {
    items: [
      { path: 'a.md', title: 'A', context: null, snippet: '' },
      { path: 'b.md', title: 'B', context: null, snippet: '' },
    ],
    indexing: false,
  },
};

describe('PageByline', () => {
  it('shows the author, relative update time, history and backlink count', async () => {
    apiRequest.mockResolvedValue(twoLinks);
    const onShow = vi.fn();
    const updated = new Date(Date.now() - 3 * 3_600_000).toISOString();
    render(
      withQuery(
        <PageByline author="you" updated={updated} path="n.md" guardRef={{ current: null }} onShowBacklinks={onShow} />,
      ),
    );
    expect(screen.getByText('you')).toBeInTheDocument();
    expect(screen.getByText('updated 3h ago')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'history' })).toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: '2 backlinks' }));
    expect(onShow).toHaveBeenCalledOnce();
  });

  it('says "1 backlink" for one', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: { items: [twoLinks.data.items[0]], indexing: false } });
    render(withQuery(<PageByline author="you" updated={null} path="n.md" guardRef={{ current: null }} onShowBacklinks={() => {}} />));
    expect(await screen.findByRole('button', { name: '1 backlink' })).toBeInTheDocument();
  });

  it('hides the count while the link index is building, and the time when unknown', async () => {
    apiRequest.mockResolvedValue({ ok: true, data: { items: [], indexing: true } });
    render(withQuery(<PageByline author="you" updated={null} path="n.md" guardRef={{ current: null }} onShowBacklinks={() => {}} />));
    await waitFor(() => expect(apiRequest).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: /backlink/ })).toBeNull();
    expect(screen.queryByText(/updated/)).toBeNull();
  });
});
