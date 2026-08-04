import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { UpcomingMeetings } from '../components/UpcomingMeetings';
import { useSelectedEvent } from '../stores/selected-event';
import type { AgendaItem } from '../../shared/api-types';

const items: AgendaItem[] = [
  { id: 'a', time: '09:00', duration: '30m', title: 'Eng standup', with: ['alice@example.com'], status: 'upcoming' },
  { id: 'b', time: '11:00', duration: '1h', title: 'Design review', with: [], status: 'upcoming' },
  { id: 'c', time: '08:00', duration: '30m', title: 'Past meeting', with: [], status: 'recorded' },
];

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

beforeEach(() => {
  useSelectedEvent.setState({ selectedEventId: null });
  vi.restoreAllMocks();
});

describe('UpcomingMeetings', () => {
  it('lists upcoming items and hides recorded ones', () => {
    render(wrap(<UpcomingMeetings items={items} />));
    expect(screen.getByText('Eng standup')).toBeInTheDocument();
    expect(screen.getByText('Design review')).toBeInTheDocument();
    expect(screen.queryByText('Past meeting')).not.toBeInTheDocument();
  });

  it('expands the prep panel on row click', () => {
    render(wrap(<UpcomingMeetings items={items} />));
    fireEvent.click(screen.getByText('Eng standup'));
    expect(useSelectedEvent.getState().selectedEventId).toBe('a');
  });

  it('auto-expands the row matching selectedEventId from the store', () => {
    useSelectedEvent.setState({ selectedEventId: 'b' });
    render(wrap(<UpcomingMeetings items={items} />));
    // The MeetingPrep inside the expanded row mounts and renders its loading state.
    expect(screen.getByRole('status', { name: /loading/i })).toBeInTheDocument();
  });
});
