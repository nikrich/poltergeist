import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { BacklinksPanel, displaySnippet } from '../components/BacklinksPanel';
import type { Backlink, BacklinksResponse } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);

function withQuery(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

const STANDUP: Backlink = {
  path: '20-contexts/work/notes/standup.md',
  title: 'Standup',
  context: 'work',
  snippet: 'ask [[20-contexts/work/alpha-plan|Alpha plan]] owner',
};
const ok = (items: Backlink[], indexing = false): BacklinksResponse => ({ items, indexing });

afterEach(() => getMock.mockReset());

describe('displaySnippet', () => {
  it('shows aliases or basenames instead of raw wikilinks', () => {
    expect(displaySnippet('ask [[20-contexts/work/a|Alpha]] and [[20-contexts/work/beta]]')).toBe(
      'ask Alpha and beta',
    );
    expect(displaySnippet('no links here')).toBe('no links here');
    expect(displaySnippet('see ![[20-contexts/work/beta]] here')).toBe('see beta here');
  });
});

describe('BacklinksPanel', () => {
  it('lists backlinks with readable snippets and opens one on click', async () => {
    getMock.mockResolvedValue(ok([STANDUP]));
    const onOpen = vi.fn();
    render(withQuery(<BacklinksPanel path="20-contexts/work/alpha-plan.md" onOpen={onOpen} />));
    expect(await screen.findByText('Standup')).toBeInTheDocument();
    expect(screen.getByText('ask Alpha plan owner')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /backlinks · 1/ })).toBeInTheDocument();
    expect(getMock).toHaveBeenCalledWith('/v1/vault/backlinks?path=20-contexts%2Fwork%2Falpha-plan.md');
    fireEvent.click(screen.getByText('Standup'));
    expect(onOpen).toHaveBeenCalledWith('20-contexts/work/notes/standup.md');
  });

  it('shows an empty state', async () => {
    getMock.mockResolvedValue(ok([]));
    render(withQuery(<BacklinksPanel path="20-contexts/work/a.md" onOpen={() => {}} />));
    expect(await screen.findByText('no backlinks yet')).toBeInTheDocument();
  });

  it('shows indexing while the sidecar builds its index', async () => {
    getMock.mockResolvedValue(ok([], true));
    render(withQuery(<BacklinksPanel path="20-contexts/work/a.md" onOpen={() => {}} />));
    expect(await screen.findByText('indexing vault…')).toBeInTheDocument();
    expect(screen.queryByText('no backlinks yet')).toBeNull();
  });

  it('shows an error with retry', async () => {
    getMock.mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce(ok([STANDUP]));
    render(withQuery(<BacklinksPanel path="20-contexts/work/a.md" onOpen={() => {}} />));
    expect(await screen.findByText(/backlinks unavailable/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'retry' }));
    expect(await screen.findByText('Standup')).toBeInTheDocument();
  });

  it('collapses and expands', async () => {
    getMock.mockResolvedValue(ok([STANDUP]));
    render(withQuery(<BacklinksPanel path="20-contexts/work/a.md" onOpen={() => {}} />));
    await screen.findByText('Standup');
    const header = screen.getByRole('button', { name: /backlinks/ });
    fireEvent.click(header);
    await waitFor(() => expect(screen.queryByText('Standup')).toBeNull());
    expect(header).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(header);
    expect(await screen.findByText('Standup')).toBeInTheDocument();
  });

  it('tolerates a malformed response body', async () => {
    getMock.mockResolvedValue({ path: 'x' } as unknown as BacklinksResponse);
    render(withQuery(<BacklinksPanel path="20-contexts/work/a.md" onOpen={() => {}} />));
    expect(await screen.findByText('no backlinks yet')).toBeInTheDocument();
  });
});
