import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { JotsScreen } from '../screens/jots';
import type { JotsPage, Note } from '../../shared/api-types';

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  window.gb = {
    ...window.gb,
    api: { request: apiRequest },
    jot: {
      save: async () => ({ ok: true as const }),
      cancel: async () => ({ ok: true as const }),
      onFocus: () => () => {},
      onSaveFailed: () => () => {},
    },
  };
});

function withQuery(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const page: JotsPage = {
  items: [
    {
      id: 'manual-20260514T093015-a',
      path: '20-contexts/sanlam/notes/manual-20260514T093015-a.md',
      title: 'first jot',
      excerpt: 'body',
      context: 'sanlam',
      routingStatus: 'routed',
      tags: [],
      created: '2026-05-14T09:30:15+02:00',
      updated: '2026-05-14T09:30:15+02:00',
    },
  ],
  total: 1,
};

const detail: Note = {
  path: '20-contexts/sanlam/notes/manual-20260514T093015-a.md',
  title: 'first jot',
  body: 'first jot\n\nfull body here',
  frontmatter: {},
};

describe('JotsScreen', () => {
  it('renders the tree and loads the first jot on select', async () => {
    apiRequest.mockImplementation(async (_m: string, path: string) => {
      if (path.includes('source=manual')) return { ok: true, status: 200, data: page };
      return { ok: true, status: 200, data: detail };
    });

    render(withQuery(<JotsScreen />));
    const leaf = await screen.findByText('first jot');
    fireEvent.click(leaf);
    await waitFor(() => expect(screen.getByText(/full body here/)).toBeInTheDocument());
  });

  it('shows empty state when there are no jots', async () => {
    apiRequest.mockImplementation(async (_m: string, path: string) => {
      if (path.includes('source=manual'))
        return { ok: true, status: 200, data: { items: [], total: 0 } satisfies JotsPage };
      return { ok: true, status: 200, data: detail };
    });

    render(withQuery(<JotsScreen />));
    await waitFor(() =>
      expect(screen.getAllByText(/no jots yet/)[0]).toBeInTheDocument(),
    );
  });

  it('auto-selects the first jot when the list loads', async () => {
    apiRequest.mockImplementation(async (_m: string, path: string) => {
      if (path.includes('source=manual')) return { ok: true, status: 200, data: page };
      return { ok: true, status: 200, data: detail };
    });

    render(withQuery(<JotsScreen />));
    // The list auto-selects the first item and loads its body.
    await waitFor(() => expect(screen.getByText(/full body here/)).toBeInTheDocument());
  });

  it('renders the rich editor with the source-mode escape hatch and copy button', async () => {
    apiRequest.mockImplementation(async (_m: string, path: string) => {
      if (path.includes('source=manual')) return { ok: true, status: 200, data: page };
      return { ok: true, status: 200, data: detail };
    });

    render(withQuery(<JotsScreen />));
    await waitFor(() => expect(screen.getByText(/full body here/)).toBeInTheDocument());
    expect(screen.getByTestId('rich-markdown-editor')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'src' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /copy formatted/ })).toBeInTheDocument();
  });
});
