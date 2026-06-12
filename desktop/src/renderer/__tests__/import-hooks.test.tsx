import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { ApiError } from '../lib/api/client';
import {
  useConfluencePages,
  useConfluenceSearch,
  useImportItems,
  useImportSpaces,
  useJiraIssues,
} from '../lib/api/hooks';
import type { ImportItem, ImportResponse } from '../../shared/api-types';

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  window.gb.api.request = apiRequest as typeof window.gb.api.request;
});

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
  Wrapper.displayName = 'QueryClientWrapper';
  return Wrapper;
}

describe('useImportSpaces', () => {
  it('fetches /v1/import/confluence/spaces', async () => {
    apiRequest.mockResolvedValueOnce({ ok: true, data: [] });
    const { result } = renderHook(() => useImportSpaces(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiRequest).toHaveBeenCalledWith('GET', '/v1/import/confluence/spaces');
  });

  it('surfaces a 409 as ApiError with status', async () => {
    apiRequest.mockResolvedValue({
      ok: false,
      error: 'confluence connector not configured — run onboarding',
      status: 409,
    });
    const { result } = renderHook(() => useImportSpaces(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isError).toBe(true));
    const err = result.current.error;
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).status).toBe(409);
    // retry: false → exactly one request, the CTA renders immediately
    expect(apiRequest).toHaveBeenCalledTimes(1);
  });
});

describe('useConfluencePages', () => {
  it('fetches pages with site/space/parent params', async () => {
    apiRequest.mockResolvedValueOnce({
      ok: true,
      data: { items: [], nextCursor: null },
    });
    const { result } = renderHook(
      () => useConfluencePages('sft.atlassian.net', 'DIG', '100'),
      { wrapper: makeWrapper() },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiRequest).toHaveBeenCalledWith(
      'GET',
      '/v1/import/confluence/pages?site=sft.atlassian.net&space=DIG&parent=100',
    );
  });

  it('does not fetch when site or space is null', () => {
    renderHook(() => useConfluencePages(null, null), { wrapper: makeWrapper() });
    expect(apiRequest).not.toHaveBeenCalled();
  });
});

describe('useConfluenceSearch', () => {
  it('does not fetch under 2 characters', () => {
    renderHook(() => useConfluenceSearch('a'), { wrapper: makeWrapper() });
    expect(apiRequest).not.toHaveBeenCalled();
  });

  it('fetches with an encoded query', async () => {
    apiRequest.mockResolvedValueOnce({ ok: true, data: [] });
    const { result } = renderHook(() => useConfluenceSearch('quote domain'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiRequest).toHaveBeenCalledWith(
      'GET',
      '/v1/import/confluence/search?q=quote%20domain',
    );
  });
});

describe('useJiraIssues', () => {
  it('fetches my issues when no query', async () => {
    apiRequest.mockResolvedValueOnce({ ok: true, data: [] });
    const { result } = renderHook(() => useJiraIssues(), { wrapper: makeWrapper() });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiRequest).toHaveBeenCalledWith('GET', '/v1/import/jira/issues');
  });

  it('fetches a text search when a query is set', async () => {
    apiRequest.mockResolvedValueOnce({ ok: true, data: [] });
    const { result } = renderHook(() => useJiraIssues('cashback'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiRequest).toHaveBeenCalledWith(
      'GET',
      '/v1/import/jira/issues?q=cashback',
    );
  });
});

describe('useImportItems', () => {
  const items: ImportItem[] = [
    { kind: 'confluence_page', site: 'sft.atlassian.net', id: '100' },
    { kind: 'jira_issue', site: 'sft.atlassian.net', key: 'DIGISURE-1' },
  ];

  it('POSTs one item at a time and reports progress', async () => {
    apiRequest.mockImplementation(async (_m: string, _p: string, body?: unknown) => {
      const item = (body as { items: ImportItem[] }).items[0]!;
      return {
        ok: true,
        data: {
          results: [{
            kind: item.kind,
            id: item.id ?? null,
            key: item.key ?? null,
            ok: true,
            path: 'x.md',
            context: 'sanlam',
            updated: false,
            error: null,
          }],
        },
      };
    });
    const onItem = vi.fn();
    const { result } = renderHook(() => useImportItems(), { wrapper: makeWrapper() });
    let res: ImportResponse | undefined;
    await act(async () => {
      res = await result.current.mutateAsync({ items, onItem });
    });
    expect(apiRequest).toHaveBeenCalledTimes(2);
    expect(apiRequest).toHaveBeenNthCalledWith(1, 'POST', '/v1/import', {
      items: [items[0]],
    });
    expect(apiRequest).toHaveBeenNthCalledWith(2, 'POST', '/v1/import', {
      items: [items[1]],
    });
    expect(onItem).toHaveBeenNthCalledWith(1, 0, 2, items[0]);
    expect(onItem).toHaveBeenNthCalledWith(2, 1, 2, items[1]);
    expect(res!.results).toHaveLength(2);
    expect(res!.results.map((r) => r.ok)).toEqual([true, true]);
  });
});
