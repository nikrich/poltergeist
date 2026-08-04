import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { ChatScreen } from '../screens/chat';
import { useChat } from '../stores/chat';
import * as client from '../lib/api/client';
import type { Conversation, ConversationSummary, Project } from '../../shared/api-types';

vi.mock('../lib/api/client', () => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  put: vi.fn(),
}));

const projects: Project[] = [
  {
    id: 'p1',
    context: 'personal',
    slug: 'site',
    name: 'Site Rebuild',
    description: '',
    archived: false,
    created_at: 1,
  },
];

const summaries: ConversationSummary[] = [
  { id: 'c1', title: 'filed thread', created_at: 1, updated_at: 5, message_count: 2, project: 'personal/site' },
  { id: 'c2', title: 'loose thread', created_at: 1, updated_at: 4, message_count: 1, project: null },
  { id: 'c3', title: 'ghost thread', created_at: 1, updated_at: 3, message_count: 1, project: 'work/gone' },
];

const conversation: Conversation = {
  id: 'c1',
  title: 'filed thread',
  created_at: 1,
  updated_at: 5,
  claude_session_id: null,
  project: 'personal/site',
  messages: [{ role: 'user', text: 'hi' }],
};

function stub() {
  vi.mocked(client.get).mockImplementation((path: string) => {
    if (path === '/v1/chat') return Promise.resolve(summaries) as never;
    if (path.startsWith('/v1/chat/')) return Promise.resolve(conversation) as never;
    if (path.startsWith('/v1/projects')) return Promise.resolve(projects) as never;
    return Promise.reject(new Error(`unexpected path ${path}`)) as never;
  });
  vi.mocked(client.patch).mockResolvedValue({ ...conversation, project: null } as never);
}

function renderChat() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ChatScreen />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  useChat.setState({ activeId: 'c1', streams: {}, errors: {}, exporting: {} });
  window.gb.chat = {
    ...window.gb.chat,
    send: vi.fn().mockResolvedValue({ ok: true }),
    stop: vi.fn().mockResolvedValue({ ok: true }),
  } as typeof window.gb.chat;
  stub();
});

describe('conversation folders', () => {
  it('groups conversations under project sections with unfiled first', async () => {
    const { container } = renderChat();
    expect(await screen.findByText('Site Rebuild')).toBeInTheDocument();
    expect(screen.getByText('unfiled')).toBeInTheDocument();
    // unknown/archived project falls back to its raw key
    expect(screen.getByText(/work\/gone/)).toBeInTheDocument();
    const labels = [...container.querySelectorAll('[data-testid="chat-group"]')].map(
      (el) => el.getAttribute('data-group'),
    );
    expect(labels[0]).toBe('__unfiled__');
    expect(labels).toContain('personal/site');
  });

  it('collapsing a section hides its conversations', async () => {
    const { container } = renderChat();
    await screen.findByText('Site Rebuild');
    const sidebar = within(container.querySelector('aside')!);
    expect(sidebar.getByText('filed thread')).toBeInTheDocument();
    await userEvent.click(sidebar.getByRole('button', { name: /collapse Site Rebuild/i }));
    expect(sidebar.queryByText('filed thread')).not.toBeInTheDocument();
    await userEvent.click(sidebar.getByRole('button', { name: /expand Site Rebuild/i }));
    expect(sidebar.getByText('filed thread')).toBeInTheDocument();
  });

  it('filing dropdown PATCHes the chosen project', async () => {
    renderChat();
    await screen.findByText('loose thread');
    await userEvent.click(screen.getByRole('button', { name: /file loose thread/i }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /Site Rebuild/i }));
    await waitFor(() => {
      expect(client.patch).toHaveBeenCalledWith('/v1/chat/c2', { project: 'personal/site' });
    });
  });

  it('unfile option PATCHes project null', async () => {
    renderChat();
    await screen.findAllByText('filed thread');
    await userEvent.click(screen.getByRole('button', { name: /file filed thread/i }));
    await userEvent.click(await screen.findByRole('menuitem', { name: /unfiled/i }));
    await waitFor(() => {
      expect(client.patch).toHaveBeenCalledWith('/v1/chat/c1', { project: null });
    });
  });
});
