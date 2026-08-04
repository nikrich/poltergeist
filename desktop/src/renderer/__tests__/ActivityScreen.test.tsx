import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { ActivityScreen } from '../screens/activity';
import { useSelectedDay } from '../stores/selected-day';
import { useNoteView } from '../stores/note-view';
import type { ActivityRow, HeatmapResponse } from '../../shared/api-types';

// Dynamic recent dates: the screen's heatmap always ends at the real today,
// so fixture days must fall inside the rendered window whenever the test runs.
function recentIso(daysAgo: number): string {
  const d = new Date();
  d.setDate(d.getDate() - daysAgo);
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

const D_MAIN = recentIso(6);
const D_OTHER = recentIso(1);

const heatmapPayload: HeatmapResponse = {
  days: [
    { date: D_MAIN, count: 3, bySource: { gmail: 2, system: 1 } },
    { date: D_OTHER, count: 1, bySource: { slack: 1 } },
  ],
  total: 4,
  maxCount: 3,
};

const rowsMain: ActivityRow[] = [
  {
    id: `audit-${D_MAIN}-2`,
    source: 'gmail',
    verb: 'processed',
    subject: 'newsletters',
    atRelative: '6d',
    at: `${D_MAIN}T10:30:00+00:00`,
    path: '20-contexts/personal/notes/newsletters.md',
  },
  {
    id: `audit-${D_MAIN}-1`,
    source: 'gmail',
    verb: 'processed',
    subject: 'standup-notes',
    atRelative: '6d',
    at: `${D_MAIN}T09:00:00+00:00`,
    path: null,
  },
  {
    id: `audit-${D_MAIN}-0`,
    source: 'system',
    verb: 'connector skipped',
    subject: 'joplin',
    atRelative: '6d',
    at: `${D_MAIN}T08:00:00+00:00`,
    path: null,
  },
];

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  apiRequest.mockImplementation(async (_method: string, path: string) => {
    if (path.startsWith('/v1/activity/heatmap')) {
      return { ok: true, status: 200, data: heatmapPayload };
    }
    if (path === `/v1/activity?date=${D_MAIN}`) {
      return { ok: true, status: 200, data: rowsMain };
    }
    return { ok: true, status: 200, data: [] };
  });
  window.gb.api.request = apiRequest as typeof window.gb.api.request;
  useSelectedDay.setState({ selectedDate: D_MAIN });
  useNoteView.setState({ path: null });
});

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

describe('ActivityScreen', () => {
  it('renders the year heatmap and the selected day log', async () => {
    render(wrap(<ActivityScreen />));
    expect(
      await screen.findByRole('button', { name: `${D_MAIN} — 3 events` }),
    ).toBeInTheDocument();
    expect(await screen.findByText('newsletters')).toBeInTheDocument();
    expect(screen.getByText('standup-notes')).toBeInTheDocument();
    expect(screen.getByText('joplin')).toBeInTheDocument();
  });

  it('clicking a heatmap day loads that day log', async () => {
    render(wrap(<ActivityScreen />));
    const cell = await screen.findByRole('button', { name: `${D_OTHER} — 1 event` });
    fireEvent.click(cell);
    expect(useSelectedDay.getState().selectedDate).toBe(D_OTHER);
    await waitFor(() =>
      expect(apiRequest).toHaveBeenCalledWith('GET', `/v1/activity?date=${D_OTHER}`),
    );
  });

  it('source chips filter the visible rows client-side', async () => {
    render(wrap(<ActivityScreen />));
    await screen.findByText('newsletters');
    fireEvent.click(screen.getByRole('button', { name: /^gmail/ }));
    expect(screen.getByText('newsletters')).toBeInTheDocument();
    expect(screen.getByText('standup-notes')).toBeInTheDocument();
    expect(screen.queryByText('joplin')).not.toBeInTheDocument();
  });

  it('clicking a row with a path opens NoteView', async () => {
    render(wrap(<ActivityScreen />));
    fireEvent.click(await screen.findByText('newsletters'));
    expect(useNoteView.getState().path).toBe(
      '20-contexts/personal/notes/newsletters.md',
    );
  });
});
