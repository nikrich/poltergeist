import { render, screen } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { ChatScreen } from '../screens/chat';
import { useChat } from '../stores/chat';
import * as client from '../lib/api/client';
import type {
  Conversation,
  ConversationSummary,
} from '../../shared/api-types';

vi.mock('../lib/api/client', () => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
}));

const summaries: ConversationSummary[] = [
  {
    id: 'c1',
    title: 'auth thread',
    created_at: 1,
    updated_at: 2,
    message_count: 2,
  },
];

const conversation: Conversation = {
  id: 'c1',
  title: 'auth thread',
  created_at: 1,
  updated_at: 2,
  claude_session_id: null,
  messages: [
    { role: 'user', text: 'how does auth work?' },
    {
      role: 'assistant',
      text: 'It uses **JWTs**.',
      tools: [{ name: 'search', summary: 'searched vault: auth' }],
    },
  ],
};

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

// Route the mocked client by path so both the list and detail queries resolve.
function stubGet() {
  vi.mocked(client.get).mockImplementation((path: string) => {
    if (path === '/v1/chat') return Promise.resolve(summaries) as never;
    if (path.startsWith('/v1/chat/')) {
      return Promise.resolve(conversation) as never;
    }
    return Promise.reject(new Error(`unexpected path ${path}`)) as never;
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  useChat.setState({ activeId: 'c1', streams: {}, errors: {} });
  stubGet();
  window.gb.chat = {
    send: vi.fn(async () => ({ ok: true }) as const),
    stop: vi.fn(async () => ({ ok: true }) as const),
  };
  window.gb.on = (() => () => {}) as typeof window.gb.on;
});

describe('ChatScreen', () => {
  it('renders the conversation list and a persisted thread', async () => {
    render(wrap(<ChatScreen />));

    // Conversation list row (also appears as the TopBar subtitle, hence getAllByText)
    expect((await screen.findAllByText('auth thread')).length).toBeGreaterThan(0);

    // Persisted user message
    expect(await screen.findByText('how does auth work?')).toBeInTheDocument();
    // Assistant markdown body (bold text becomes a <strong>, but the words are present)
    expect(screen.getByText(/JWTs/)).toBeInTheDocument();
    // Tool chip summary
    expect(screen.getByText('searched vault: auth')).toBeInTheDocument();
  });

  it('renders mid-stream state with optimistic bubble, live text, tool chip, and stop button', async () => {
    useChat.setState({
      activeId: 'c1',
      streams: {
        c1: {
          userText: 'and refresh tokens?',
          text: 'Refresh tokens rotate.',
          tools: [{ name: 'search', summary: 'searched vault: refresh' }],
        },
      },
      errors: {},
    });

    render(wrap(<ChatScreen />));

    expect(await screen.findByText('and refresh tokens?')).toBeInTheDocument();
    expect(screen.getByText(/Refresh tokens rotate\./)).toBeInTheDocument();
    expect(screen.getByText('searched vault: refresh')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: /stop/i }),
    ).toBeInTheDocument();
  });

  it('renders a turn error inline', async () => {
    useChat.setState({
      activeId: 'c1',
      streams: {},
      errors: { c1: 'LLMTimeout: claude -p timed out' },
    });

    render(wrap(<ChatScreen />));

    expect(
      await screen.findByText(/LLMTimeout: claude -p timed out/),
    ).toBeInTheDocument();
  });
});
