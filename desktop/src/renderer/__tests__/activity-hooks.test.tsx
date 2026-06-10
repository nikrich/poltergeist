import { renderHook, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { useActivityHeatmap, useActivityForDate } from '../lib/api/hooks';
import type { HeatmapResponse } from '../../shared/api-types';

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  window.gb.api.request = apiRequest as typeof window.gb.api.request;
});

function makeWrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={qc}>{children}</QueryClientProvider>
  );
}

const payload: HeatmapResponse = {
  days: [{ date: '2026-06-04', count: 23, bySource: { gmail: 9, slack: 5, system: 9 } }],
  total: 23,
  maxCount: 23,
};

describe('useActivityHeatmap', () => {
  it('fetches /v1/activity/heatmap with the days param', async () => {
    apiRequest.mockResolvedValueOnce({ ok: true, status: 200, data: payload });
    const { result } = renderHook(() => useActivityHeatmap(84), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiRequest).toHaveBeenCalledWith('GET', '/v1/activity/heatmap?days=84');
    expect(result.current.data).toEqual(payload);
  });
});

describe('useActivityForDate', () => {
  it('fetches the day log for a date', async () => {
    apiRequest.mockResolvedValueOnce({ ok: true, status: 200, data: [] });
    const { result } = renderHook(() => useActivityForDate('2026-06-04'), {
      wrapper: makeWrapper(),
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(apiRequest).toHaveBeenCalledWith('GET', '/v1/activity?date=2026-06-04');
  });

  it('does not fetch when date is null', () => {
    renderHook(() => useActivityForDate(null), { wrapper: makeWrapper() });
    expect(apiRequest).not.toHaveBeenCalled();
  });
});
