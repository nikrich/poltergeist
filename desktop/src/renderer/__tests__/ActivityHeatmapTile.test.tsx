import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { ActivityHeatmapTile } from '../components/ActivityHeatmapTile';
import { useNavigation } from '../stores/navigation';
import { useSelectedDay } from '../stores/selected-day';
import type { HeatmapResponse } from '../../shared/api-types';

function recentIso(daysAgo: number): string {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

const D = recentIso(3);

const payload: HeatmapResponse = {
  days: [{ date: D, count: 23, bySource: { gmail: 23 } }],
  total: 23,
  maxCount: 23,
};

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  apiRequest.mockResolvedValue({ ok: true, status: 200, data: payload });
  window.gb.api.request = apiRequest as typeof window.gb.api.request;
  useNavigation.setState({ active: 'today' });
  useSelectedDay.setState({ selectedDate: null });
});

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

describe('ActivityHeatmapTile', () => {
  it('requests 84 days (12 weeks) of heatmap data', async () => {
    render(wrap(<ActivityHeatmapTile />));
    await screen.findByRole('button', { name: `${D} — 23 events` });
    expect(apiRequest).toHaveBeenCalledWith('GET', '/v1/activity/heatmap?days=182');
  });

  it('cell click preselects the day and navigates to the activity screen', async () => {
    render(wrap(<ActivityHeatmapTile />));
    fireEvent.click(await screen.findByRole('button', { name: `${D} — 23 events` }));
    expect(useSelectedDay.getState().selectedDate).toBe(D);
    expect(useNavigation.getState().active).toBe('activity');
  });

  it('the open action navigates without preselecting a day', async () => {
    useSelectedDay.setState({ selectedDate: D });
    render(wrap(<ActivityHeatmapTile />));
    fireEvent.click(await screen.findByRole('button', { name: 'open' }));
    expect(useSelectedDay.getState().selectedDate).toBe(null);
    expect(useNavigation.getState().active).toBe('activity');
  });
});
