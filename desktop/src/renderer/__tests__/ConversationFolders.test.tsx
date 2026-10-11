import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { ChatScreen } from '../screens/chat';
import { useChat } from '../stores/chat';
import * as client from '../lib/api/client';
import type { ChatTree, ChatTreeChat, Conversation, Project } from '../../shared/api-types';

vi.mock('../lib/api/client', () => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  del: vi.fn(),
  put: vi.fn(),
}));

const projects: Project[] = [
  { id: 'p1', context: 'personal', slug: 'site', name: 'Site Rebuild', description: '', archived: false, created_at: 1 },
];

function chat(id: string, title: string, over: Partial<ChatTreeChat> = {}): ChatTreeChat {
  return {
    id, title, created_at: 1, updated_at: 1, message_count: 2,
    context: null, project: null, folder: null, auto_filed: 'done', unknown_location: false, ...over,
  };
}

const tree: ChatTree = {
  unfiled: [chat('c2', 'loose thread')],
  scopes: [
    {
      context: 'personal', project: 'site', name: 'Site Rebuild', archived: false,
      folders: [{
        name: 'drafts', path: 'drafts', folders: [],
        chats: [chat('c1', 'filed thread', { context: 'personal', project: 'site', folder: 'drafts' })],
      }],
      chats: [],
    },
  ],
};

function conv(id: string, title: string, text: string): Conversation {
  return {
    id, title, created_at: 1, updated_at: 1, claude_session_id: null,
    context: null, project: null, folder: null, auto_filed: 'done',
    messages: [{ role: 'user', text }],
  };
}

function stub() {
  vi.mocked(client.get).mockImplementation((path: string) => {
    if (path === '/v1/chat') return Promise.resolve([]) as never;
    if (path === '/v1/chat/tree') return Promise.resolve(tree) as never;
    if (path === '/v1/chat/c1') return Promise.resolve(conv('c1', 'filed thread', 'inside the folder')) as never;
    if (path === '/v1/chat/c2') return Promise.resolve(conv('c2', 'loose thread', 'out in the open')) as never;
    if (path.startsWith('/v1/projects')) return Promise.resolve(projects) as never;
    return Promise.resolve(null) as never;
  });
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
  useChat.setState({ activeId: 'c2', streams: {}, errors: {}, exporting: {}, filed: {} });
  window.gb.chat = {
    ...window.gb.chat,
    send: vi.fn().mockResolvedValue({ ok: true }),
    stop: vi.fn().mockResolvedValue({ ok: true }),
  } as typeof window.gb.chat;
  window.gb.on = (() => () => {}) as typeof window.gb.on;
  stub();
});

describe('chat sidebar tree (screen integration)', () => {
  it('renders the tree from /v1/chat/tree', async () => {
    const { container } = renderChat();
    const sidebar = within(container.querySelector('aside')!);
    expect(await sidebar.findByText('Site Rebuild')).toBeInTheDocument();
    expect(sidebar.getByTestId('chat-unfiled')).toBeInTheDocument();
    expect(sidebar.getByText('drafts')).toBeInTheDocument();
    expect(sidebar.getByText('filed thread')).toBeInTheDocument();
    expect(sidebar.getByText('loose thread')).toBeInTheDocument();
  });

  it('selecting a chat inside a folder opens it', async () => {
    const { container } = renderChat();
    expect(await screen.findByText('out in the open')).toBeInTheDocument();
    const sidebar = within(container.querySelector('aside')!);
    await userEvent.click(await sidebar.findByText('filed thread'));
    expect(useChat.getState().activeId).toBe('c1');
    expect(await screen.findByText('inside the folder')).toBeInTheDocument();
  });

  it('shows the filed notice for the active chat', async () => {
    useChat.setState({ filed: { c2: { context: 'personal', project: 'site', folder: null } } });
    renderChat();
    expect(await screen.findByText('Filed under personal / Site Rebuild')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'dismiss' }));
    await waitFor(() => expect(screen.queryByText(/Filed under/)).not.toBeInTheDocument());
  });
});
