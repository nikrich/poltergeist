import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { ImportScreen } from '../screens/import';
import { useNavigation } from '../stores/navigation';
import type {
  ConfluencePagesResponse,
  ImportJiraIssue,
  ImportPage,
  ImportSpace,
} from '../../shared/api-types';

const spaces: ImportSpace[] = [
  { site: 'sft.atlassian.net', siteSlug: 'sft', key: 'DIG', name: 'Digisure', context: 'sanlam' },
  { site: 'sft.atlassian.net', siteSlug: 'sft', key: 'SPE', name: 'Short-term', context: 'sanlam' },
];

const digPages: ConfluencePagesResponse = {
  items: [
    { site: 'sft.atlassian.net', id: '100', title: 'ASCP architecture', parentId: null,
      hasChildren: true, updatedAt: '2026-06-01T10:00:00.000Z', version: 4, space: 'DIG' },
    { site: 'sft.atlassian.net', id: '200', title: 'Runbooks', parentId: null,
      hasChildren: false, updatedAt: null, version: 1, space: 'DIG' },
  ],
  nextCursor: null,
};

const searchHits: ImportPage[] = [
  { site: 'sft.atlassian.net', id: '300', title: 'Quote domain design', parentId: null,
    hasChildren: false, updatedAt: '2026-04-01T09:00:00.000Z', version: 7, space: 'SPE' },
];

const issues: ImportJiraIssue[] = [
  { site: 'sft.atlassian.net', key: 'DIGISURE-1', summary: 'Fix the BFF',
    status: 'In Progress', project: 'DIGISURE', updatedAt: '2026-06-08T10:00:00.000+0000' },
  { site: 'sft.atlassian.net', key: 'DIGISURE-2', summary: 'Add cashback',
    status: 'To Do', project: 'DIGISURE', updatedAt: '2026-06-07T10:00:00.000+0000' },
];

const apiRequest = vi.fn();

function mockBrowseApi() {
  apiRequest.mockImplementation(async (method: string, path: string, body?: unknown) => {
    if (path === '/v1/import/confluence/spaces') return { ok: true, data: spaces };
    if (path.startsWith('/v1/import/confluence/pages')) return { ok: true, data: digPages };
    if (path.startsWith('/v1/import/confluence/search')) return { ok: true, data: searchHits };
    if (path.startsWith('/v1/import/jira/issues')) return { ok: true, data: issues };
    if (method === 'POST' && path === '/v1/import') {
      const item = (body as { items: Array<{ kind: string; key?: string; id?: string }> }).items[0]!;
      if (item.key === 'DIGISURE-2') {
        return { ok: true, data: { results: [{ kind: item.kind, key: item.key ?? null, id: item.id ?? null, ok: false, error: 'not found' }] } };
      }
      return { ok: true, data: { results: [{ kind: item.kind, key: item.key ?? null, id: item.id ?? null, ok: true, path: '20-contexts/sanlam/x.md', context: 'sanlam', updated: false, error: null }] } };
    }
    return { ok: true, data: null };
  });
}

beforeEach(() => {
  apiRequest.mockReset();
  mockBrowseApi();
  window.gb.api.request = apiRequest as typeof window.gb.api.request;
  useNavigation.setState({ active: 'import' });
});

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

describe('ImportScreen', () => {
  it('lists monitored spaces, expands one to its pages, and ticking shows the selection bar', async () => {
    render(wrap(<ImportScreen />));
    expect(await screen.findByText('Digisure')).toBeInTheDocument();
    expect(screen.getByText('Short-term')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: 'toggle space DIG' }));
    expect(await screen.findByText('ASCP architecture')).toBeInTheDocument();
    expect(screen.getByText('Runbooks')).toBeInTheDocument();
    // only the page with children gets an expand affordance
    expect(screen.getByRole('button', { name: 'expand ASCP architecture' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'expand Runbooks' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('checkbox', { name: 'select ASCP architecture' }));
    expect(screen.getByRole('button', { name: 'import 1 selected' })).toBeInTheDocument();
  });

  it('a confluence search replaces the space list with results', async () => {
    render(wrap(<ImportScreen />));
    await screen.findByText('Digisure');
    fireEvent.change(screen.getByPlaceholderText('search pages by title…'), {
      target: { value: 'quote' },
    });
    expect(await screen.findByText('Quote domain design')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'toggle space DIG' })).not.toBeInTheDocument();
    await waitFor(() =>
      expect(apiRequest).toHaveBeenCalledWith('GET', '/v1/import/confluence/search?q=quote'),
    );
  });

  it('the jira tab lists my issues by default', async () => {
    render(wrap(<ImportScreen />));
    fireEvent.click(screen.getByRole('button', { name: 'jira' }));
    expect(await screen.findByText('DIGISURE-1')).toBeInTheDocument();
    expect(screen.getByText('Fix the BFF')).toBeInTheDocument();
    expect(apiRequest).toHaveBeenCalledWith('GET', '/v1/import/jira/issues');
  });

  it('imports the selection one item at a time, marks results, and keeps failed items ticked', async () => {
    render(wrap(<ImportScreen />));
    fireEvent.click(screen.getByRole('button', { name: 'jira' }));
    await screen.findByText('DIGISURE-1');
    fireEvent.click(screen.getByRole('checkbox', { name: 'select DIGISURE-1' }));
    fireEvent.click(screen.getByRole('checkbox', { name: 'select DIGISURE-2' }));
    fireEvent.click(screen.getByRole('button', { name: 'import 2 selected' }));

    expect(await screen.findByText('imported')).toBeInTheDocument();
    expect(screen.getByText('failed')).toBeInTheDocument();

    const posts = apiRequest.mock.calls.filter(([m]) => m === 'POST');
    expect(posts).toHaveLength(2);
    expect(posts[0]![2]).toEqual({
      items: [{ kind: 'jira_issue', site: 'sft.atlassian.net', key: 'DIGISURE-1' }],
    });
    expect(posts[1]![2]).toEqual({
      items: [{ kind: 'jira_issue', site: 'sft.atlassian.net', key: 'DIGISURE-2' }],
    });

    // success unticked; failure stays ticked for retry
    expect(screen.getByRole('checkbox', { name: 'select DIGISURE-1' })).not.toBeChecked();
    expect(screen.getByRole('checkbox', { name: 'select DIGISURE-2' })).toBeChecked();
    expect(screen.getByRole('button', { name: 'import 1 selected' })).toBeInTheDocument();
  });

  it('renders a connectors call-to-action on 409 instead of an error panel', async () => {
    apiRequest.mockImplementation(async (_m: string, path: string) => {
      if (path === '/v1/import/confluence/spaces') {
        return {
          ok: false,
          error: 'confluence connector not configured — run onboarding',
          status: 409,
        };
      }
      return { ok: true, data: [] };
    });
    render(wrap(<ImportScreen />));
    expect(await screen.findByText(/not connected yet/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'open connectors' }));
    expect(useNavigation.getState().active).toBe('connectors');
  });
});
