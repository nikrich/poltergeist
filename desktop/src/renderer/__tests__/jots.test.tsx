import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { JotsScreen } from '../screens/jots';
import type { JotsPage, Note, AutoRouteResponse, Project } from '../../shared/api-types';

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

// A page with two jots: first is routed, second is pending
const twoJotPage: JotsPage = {
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
    {
      id: 'manual-20260514T120000-b',
      path: '00-inbox/raw/manual/manual-20260514T120000-b.md',
      title: 'second jot',
      excerpt: 'pending content',
      context: null,
      routingStatus: 'pending',
      tags: [],
      created: '2026-05-14T12:00:00+02:00',
      updated: '2026-05-14T12:00:00+02:00',
    },
  ],
  total: 2,
};

const detailA: Note = {
  path: '20-contexts/sanlam/notes/manual-20260514T093015-a.md',
  title: 'first jot',
  body: 'first jot\n\nfull body here',
  frontmatter: {},
};

const detailB: Note = {
  path: '00-inbox/raw/manual/manual-20260514T120000-b.md',
  title: 'second jot',
  body: 'pending content here',
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

  // ── New-button sends route:false ─────────────────────────────────────────

  it('"new" button sends route:false in the create request', async () => {
    const createResponse: AutoRouteResponse = {
      id: 'manual-20260601T000000-new',
      path: '00-inbox/raw/manual/manual-20260601T000000-new.md',
      routingStatus: 'pending',
    };
    apiRequest.mockImplementation(async (method: string, path: string) => {
      if (path.includes('source=manual')) return { ok: true, status: 200, data: { items: [], total: 0 } satisfies JotsPage };
      if (method === 'POST' && path === '/v1/notes')
        return { ok: true, status: 200, data: createResponse };
      return { ok: true, status: 200, data: { items: [], total: 0 } };
    });

    render(withQuery(<JotsScreen />));
    await waitFor(() => screen.getByRole('button', { name: /new/ }));

    fireEvent.click(screen.getByRole('button', { name: /new/ }));

    await waitFor(() => {
      const postCall = apiRequest.mock.calls.find(
        (args: unknown[]) => args[0] === 'POST' && args[1] === '/v1/notes',
      );
      expect(postCall).toBeDefined();
      const body = postCall![2]; // third arg is the request body
      expect(body).toMatchObject({ route: false });
    });
  });

  // ── Auto-route on leave ────────────────────────────────────────────────────

  it('switching away from an unrouted jot fires POST .../route-auto', async () => {
    const routeAutoResponse: AutoRouteResponse = {
      id: 'manual-20260514T120000-b',
      path: '20-contexts/sanlam/notes/manual-20260514T120000-b.md',
      routingStatus: 'routed',
      context: 'sanlam',
    };

    apiRequest.mockImplementation(async (method: string, path: string) => {
      if (path.includes('source=manual')) return { ok: true, status: 200, data: twoJotPage };
      if (path.includes('manual-20260514T093015-a') && !path.includes('route'))
        return { ok: true, status: 200, data: detailA };
      if (path.includes('manual-20260514T120000-b') && !path.includes('route'))
        return { ok: true, status: 200, data: detailB };
      if (method === 'POST' && path.includes('route-auto'))
        return { ok: true, status: 200, data: routeAutoResponse };
      return { ok: true, status: 200, data: detailA };
    });

    render(withQuery(<JotsScreen />));

    // Auto-select first jot (routed)
    await waitFor(() => expect(screen.getByText(/full body here/)).toBeInTheDocument());

    // Click the second (pending) jot
    fireEvent.click(screen.getByText('second jot'));
    await waitFor(() => expect(screen.getByText(/pending content here/)).toBeInTheDocument());

    // Click back to the first jot — this should trigger route-auto for the pending jot
    fireEvent.click(screen.getByText('first jot'));

    await waitFor(() => {
      const routeAutoCall = apiRequest.mock.calls.find(
        (args: unknown[]) =>
          args[0] === 'POST' && typeof args[1] === 'string' && args[1].includes('manual-20260514T120000-b') && args[1].includes('route-auto'),
      );
      expect(routeAutoCall).toBeDefined();
    });
  });

  it('arriving at an unrouted jot does NOT fire route-auto (double-fire regression)', async () => {
    apiRequest.mockImplementation(async (method: string, path: string) => {
      if (path.includes('source=manual')) return { ok: true, status: 200, data: twoJotPage };
      if (path.includes('manual-20260514T093015-a') && !path.includes('route'))
        return { ok: true, status: 200, data: detailA };
      if (path.includes('manual-20260514T120000-b') && !path.includes('route'))
        return { ok: true, status: 200, data: detailB };
      return { ok: true, status: 200, data: detailA };
    });

    render(withQuery(<JotsScreen />));
    await waitFor(() => expect(screen.getByText(/full body here/)).toBeInTheDocument());

    // Select the pending jot and settle — selecting must not route it.
    fireEvent.click(screen.getByText('second jot'));
    await waitFor(() => expect(screen.getByText(/pending content here/)).toBeInTheDocument());

    const routeAutoCalls = apiRequest.mock.calls.filter(
      (args: unknown[]) => args[0] === 'POST' && typeof args[1] === 'string' && args[1].includes('route-auto'),
    );
    expect(routeAutoCalls).toHaveLength(0);
  });

  // ── "route now" button visibility ────────────────────────────────────────

  it('"route now" button is visible for unrouted jot and absent for routed jot', async () => {
    apiRequest.mockImplementation(async (_m: string, path: string) => {
      if (path.includes('source=manual')) return { ok: true, status: 200, data: twoJotPage };
      if (path.includes('manual-20260514T093015-a') && !path.includes('route'))
        return { ok: true, status: 200, data: detailA };
      if (path.includes('manual-20260514T120000-b') && !path.includes('route'))
        return { ok: true, status: 200, data: detailB };
      return { ok: true, status: 200, data: detailA };
    });

    render(withQuery(<JotsScreen />));

    // Auto-selects first jot (routed) — "route now" should NOT be visible
    await waitFor(() => expect(screen.getByText(/full body here/)).toBeInTheDocument());
    expect(screen.queryByRole('button', { name: 'route now' })).not.toBeInTheDocument();

    // Click the second (pending) jot — "route now" SHOULD appear
    fireEvent.click(screen.getByText('second jot'));
    await waitFor(() => expect(screen.getByText(/pending content here/)).toBeInTheDocument());
    expect(screen.getByRole('button', { name: 'route now' })).toBeInTheDocument();
  });

  it('"route now" button fires POST .../route-auto for the selected jot', async () => {
    const pendingPage: JotsPage = {
      items: [
        {
          id: 'manual-20260514T120000-b',
          path: '00-inbox/raw/manual/manual-20260514T120000-b.md',
          title: 'pending jot',
          excerpt: 'pending content',
          context: null,
          routingStatus: 'pending',
          tags: [],
          created: '2026-05-14T12:00:00+02:00',
          updated: '2026-05-14T12:00:00+02:00',
        },
      ],
      total: 1,
    };

    const routeAutoResponse: AutoRouteResponse = {
      id: 'manual-20260514T120000-b',
      path: '20-contexts/sanlam/notes/manual-20260514T120000-b.md',
      routingStatus: 'routed',
      context: 'sanlam',
    };

    apiRequest.mockImplementation(async (method: string, path: string) => {
      if (path.includes('source=manual')) return { ok: true, status: 200, data: pendingPage };
      if (method === 'POST' && path.includes('route-auto'))
        return { ok: true, status: 200, data: routeAutoResponse };
      return { ok: true, status: 200, data: detailB };
    });

    render(withQuery(<JotsScreen />));

    // Auto-selects pending jot — "route now" visible
    await waitFor(() => expect(screen.getByText(/pending content here/)).toBeInTheDocument());
    const routeNowBtn = screen.getByRole('button', { name: 'route now' });
    expect(routeNowBtn).toBeInTheDocument();

    fireEvent.click(routeNowBtn);

    await waitFor(() => {
      const routeAutoCall = apiRequest.mock.calls.find(
        (args: unknown[]) =>
          args[0] === 'POST' && typeof args[1] === 'string' && args[1].includes('manual-20260514T120000-b') && args[1].includes('route-auto'),
      );
      expect(routeAutoCall).toBeDefined();
    });
  });
});

// ── Re-route picker with projects ─────────────────────────────────────────

const projectsData: Project[] = [
  {
    id: 'codeship/poltergeist',
    context: 'codeship',
    slug: 'poltergeist',
    name: 'Poltergeist',
    description: '',
    archived: false,
    created_at: 1,
  },
];

describe('JotsScreen re-route picker', () => {
  it('re-route select offers project destinations', async () => {
    apiRequest.mockImplementation(async (_m: string, path: string) => {
      if (path.includes('source=manual')) return { ok: true, status: 200, data: page };
      if (path === '/v1/projects') return { ok: true, status: 200, data: projectsData };
      return { ok: true, status: 200, data: detail };
    });

    render(withQuery(<JotsScreen />));
    // Wait for the jot to load so footer is visible
    await waitFor(() => expect(screen.getByText(/full body here/)).toBeInTheDocument());

    const select = screen.getByDisplayValue('re-route…');
    const options = Array.from(select.querySelectorAll('option')).map((o) => o.getAttribute('value'));
    expect(options).toContain('codeship');
    expect(options).toContain('codeship/poltergeist');
  });
});
