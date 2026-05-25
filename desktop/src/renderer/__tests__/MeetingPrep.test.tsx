import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { MeetingPrep } from '../components/MeetingPrep';
import * as hooks from '../lib/api/hooks';
import type { Prep } from '../../shared/api-types';

const fullPrep: Prep = {
  eventId: 'evt-1',
  brief: 'Continuing last week\'s auth thread.',
  related: [{
    path: '20-contexts/sanlam/meetings/2026-05-18-eng-standup.md',
    title: 'Eng standup 2026-05-18',
    source: 'meeting',
    snippet: 'agreed to spike auth',
    score: 0.82,
  }],
  eventSnapshot: {
    title: 'Eng standup',
    start: '2026-05-25T09:00:00+02:00',
    end: '2026-05-25T09:30:00+02:00',
    with: ['alice@example.com'],
    location: 'Zoom',
    description: 'sprint planning',
    hash: 'h1',
  },
  generatedAt: '2026-05-25T08:55:00+02:00',
  error: null,
};

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe('MeetingPrep', () => {
  it('renders the brief, attendees, and related items on success', () => {
    vi.spyOn(hooks, 'useMeetingPrep').mockReturnValue({
      data: fullPrep,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useMeetingPrep>);

    render(wrap(<MeetingPrep eventId="evt-1" />));

    expect(screen.getByText('Continuing last week\'s auth thread.')).toBeInTheDocument();
    expect(screen.getByText('alice@example.com')).toBeInTheDocument();
    expect(screen.getByText('Eng standup 2026-05-18')).toBeInTheDocument();
  });

  it('shows a loading state while the query is in flight', () => {
    vi.spyOn(hooks, 'useMeetingPrep').mockReturnValue({
      data: undefined,
      isLoading: true,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useMeetingPrep>);

    render(wrap(<MeetingPrep eventId="evt-1" />));

    expect(screen.getByRole('status', { name: /loading/i })).toBeInTheDocument();
  });

  it('renders event detail and related even when the brief errored', () => {
    const noBriefPrep: Prep = {
      ...fullPrep,
      brief: null,
      error: 'LLMTimeout: claude -p timed out after 30s',
    };
    vi.spyOn(hooks, 'useMeetingPrep').mockReturnValue({
      data: noBriefPrep,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useMeetingPrep>);

    render(wrap(<MeetingPrep eventId="evt-1" />));

    expect(screen.getByText(/couldn't generate brief/i)).toBeInTheDocument();
    expect(screen.getByText('alice@example.com')).toBeInTheDocument();
    expect(screen.getByText('Eng standup 2026-05-18')).toBeInTheDocument();
  });

  it('hides the related section when the list is empty', () => {
    const emptyRelatedPrep: Prep = { ...fullPrep, related: [] };
    vi.spyOn(hooks, 'useMeetingPrep').mockReturnValue({
      data: emptyRelatedPrep,
      isLoading: false,
      isError: false,
      error: null,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof hooks.useMeetingPrep>);

    render(wrap(<MeetingPrep eventId="evt-1" />));

    expect(screen.queryByText(/related/i)).not.toBeInTheDocument();
  });
});
