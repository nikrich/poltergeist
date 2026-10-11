import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { ChatTree, CHAT_DRAG_MIME } from '../components/chat/ChatTree';
import { FiledNotice } from '../components/chat/FiledNotice';
import { useChat } from '../stores/chat';
import type { ChatTree as ChatTreeData, ChatTreeChat, Project } from '../../shared/api-types';

function chat(id: string, title: string, over: Partial<ChatTreeChat> = {}): ChatTreeChat {
  return {
    id, title, created_at: 1, updated_at: 1, message_count: 2,
    context: null, project: null, folder: null, auto_filed: 'done', unknown_location: false, ...over,
  };
}

const tree: ChatTreeData = {
  unfiled: [
    chat('c2', 'loose thread'),
    chat('c3', 'ghost thread', { context: 'gone', unknown_location: true }),
  ],
  scopes: [
    {
      context: 'work', project: null, name: 'work', archived: false,
      folders: [{ name: 'plans', path: 'plans', folders: [], chats: [chat('c1', 'filed thread', { context: 'work', folder: 'plans' })] }],
      chats: [],
    },
    { context: 'work', project: 'atlas', name: 'Atlas', archived: false, folders: [], chats: [] },
    { context: 'personal', project: null, name: 'personal', archived: false, folders: [], chats: [] },
  ],
};

const projects: Project[] = [
  { id: 'p1', context: 'work', slug: 'atlas', name: 'Atlas', description: '', archived: false, created_at: 1 },
];

type Call = { method: string; path: string; body: unknown };
let calls: Call[] = [];

function stubApi() {
  calls = [];
  window.gb.api.request = vi.fn(async (method: string, path: string, body?: unknown) => {
    calls.push({ method, path, body });
    if (method === 'GET' && path === '/v1/chat/tree') return { ok: true, data: tree };
    if (method === 'GET' && path.startsWith('/v1/projects')) return { ok: true, data: projects };
    return { ok: true, data: null };
  }) as unknown as typeof window.gb.api.request;
}

const mutations = (method: string) => calls.filter((c) => c.method === method);

function dt(data: Record<string, string>) {
  return { getData: (k: string) => data[k] ?? '', setData: vi.fn(), types: Object.keys(data), files: [], dropEffect: 'move', effectAllowed: 'all' };
}

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

function renderTree(onSelect = vi.fn()) {
  wrap(<ChatTree activeId={null} onSelect={onSelect} />);
  return onSelect;
}

const leaf = (id: string) => JSON.stringify({ kind: 'leaf', id });

beforeEach(() => {
  stubApi();
  useChat.setState({ filed: {}, manualMoved: {} });
});

describe('ChatTree', () => {
  it('renders unfiled, scopes, folders and chats', async () => {
    renderTree();
    expect(await screen.findByText('loose thread')).toBeInTheDocument();
    expect(screen.getByTestId('chat-unfiled')).toHaveTextContent('unfiled');
    expect(screen.getAllByText('work').length).toBeGreaterThan(0);
    expect(screen.getByText('Atlas')).toBeInTheDocument();
    expect(screen.getByText('plans')).toBeInTheDocument();
    expect(screen.getByText('filed thread')).toBeInTheDocument();
  });

  it('selects a chat on click', async () => {
    const onSelect = renderTree();
    await userEvent.click(await screen.findByText('filed thread'));
    expect(onSelect).toHaveBeenCalledWith('c1');
  });

  it('drops an unfiled chat onto a project', async () => {
    renderTree();
    await screen.findByText('loose thread');
    fireEvent.drop(screen.getByTestId('folder-work/atlas/'), { dataTransfer: dt({ [CHAT_DRAG_MIME]: leaf('c2') }) });
    await waitFor(() => expect(mutations('PATCH')).toHaveLength(1));
    expect(mutations('PATCH')[0]).toMatchObject({ path: '/v1/chat/c2', body: { context: 'work', project: 'atlas', folder: null } });
  });

  it('drops a filed chat onto unfiled', async () => {
    renderTree();
    await screen.findByText('filed thread');
    fireEvent.drop(screen.getByTestId('chat-unfiled'), { dataTransfer: dt({ [CHAT_DRAG_MIME]: leaf('c1') }) });
    await waitFor(() => expect(mutations('PATCH')).toHaveLength(1));
    expect(mutations('PATCH')[0]).toMatchObject({ path: '/v1/chat/c1', body: { context: null, project: null, folder: null } });
  });

  it('ignores a folder dropped onto unfiled', async () => {
    renderTree();
    await screen.findByText('filed thread');
    const ref = { context: 'work', project: null, path: 'plans' };
    fireEvent.drop(screen.getByTestId('chat-unfiled'), { dataTransfer: dt({ [CHAT_DRAG_MIME]: JSON.stringify({ kind: 'folder', ref }) }) });
    await new Promise((r) => setTimeout(r, 10));
    expect(mutations('PATCH')).toHaveLength(0);
  });

  it('moves a folder into a project', async () => {
    renderTree();
    await screen.findByText('plans');
    const ref = { context: 'work', project: null, path: 'plans' };
    fireEvent.drop(screen.getByTestId('folder-work/atlas/'), { dataTransfer: dt({ [CHAT_DRAG_MIME]: JSON.stringify({ kind: 'folder', ref }) }) });
    await waitFor(() => expect(mutations('PATCH')).toHaveLength(1));
    expect(mutations('PATCH')[0]).toMatchObject({
      path: '/v1/chat/folders',
      body: { from: ref, to: { context: 'work', project: 'atlas', path: 'plans' } },
    });
  });

  it('creates a folder inline', async () => {
    renderTree();
    await screen.findByText('plans');
    fireEvent.click(screen.getByLabelText('new folder in work/_/'));
    const input = screen.getByPlaceholderText('folder name');
    fireEvent.change(input, { target: { value: 'q4' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(mutations('POST')).toHaveLength(1));
    expect(mutations('POST')[0]).toMatchObject({ path: '/v1/chat/folders', body: { context: 'work', project: null, path: 'q4' } });
  });

  it('deletes a folder', async () => {
    renderTree();
    await screen.findByText('plans');
    fireEvent.click(screen.getByLabelText('delete work/_/plans'));
    await waitFor(() => expect(mutations('DELETE')).toHaveLength(1));
    expect(mutations('DELETE')[0]?.path).toBe('/v1/chat/folders?context=work&path=plans');
  });

  it('moves a chat via the Move-to menu', async () => {
    renderTree();
    await screen.findByText('loose thread');
    await userEvent.click(screen.getByRole('button', { name: 'move loose thread' }));
    const menu = screen.getByRole('menu');
    expect(menu).toBeInTheDocument();
    await userEvent.click(screen.getByRole('menuitem', { name: 'plans' }));
    await waitFor(() => expect(mutations('PATCH')).toHaveLength(1));
    expect(mutations('PATCH')[0]).toMatchObject({ path: '/v1/chat/c2', body: { context: 'work', project: null, folder: 'plans' } });
    expect(screen.queryByRole('menu')).not.toBeInTheDocument();
  });

  it('choosing the current location in the Move-to menu is a no-op', async () => {
    renderTree();
    await screen.findByText('loose thread');
    await userEvent.click(screen.getByRole('button', { name: 'move loose thread' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'unfiled' }));
    await new Promise((r) => setTimeout(r, 10));
    expect(mutations('PATCH')).toHaveLength(0);
  });

  it('renames a chat inline on double-click', async () => {
    renderTree();
    fireEvent.doubleClick(await screen.findByText('loose thread'));
    const input = screen.getByDisplayValue('loose thread');
    fireEvent.change(input, { target: { value: 'tight thread' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() => expect(mutations('PATCH')).toHaveLength(1));
    expect(mutations('PATCH')[0]).toMatchObject({ path: '/v1/chat/c2', body: { title: 'tight thread' } });
  });

  it('deleting the active chat clears the selection', async () => {
    const onSelect = vi.fn();
    wrap(<ChatTree activeId="c2" onSelect={onSelect} />);
    await screen.findByText('loose thread');
    const row = screen.getByText('loose thread').closest('[role="button"]') as HTMLElement;
    fireEvent.click(row.querySelector('[aria-label="delete conversation"]')!);
    await waitFor(() => expect(onSelect).toHaveBeenCalledWith(null));
    expect(mutations('DELETE')[0]?.path).toBe('/v1/chat/c2');
  });

  it('a manual drop clears a stale filed notice and marks the chat as manually moved', async () => {
    useChat.setState({ filed: { c1: { context: 'work', project: null, folder: 'plans' } } });
    renderTree();
    await screen.findByText('filed thread');
    fireEvent.drop(screen.getByTestId('chat-unfiled'), { dataTransfer: dt({ [CHAT_DRAG_MIME]: leaf('c1') }) });
    expect(useChat.getState().filed.c1).toBeUndefined();
    expect(useChat.getState().manualMoved.c1).toBe(true);
  });

  it('a Move-to choice clears a stale filed notice and marks the chat as manually moved', async () => {
    useChat.setState({ filed: { c2: { context: 'work', project: null, folder: null } } });
    renderTree();
    await screen.findByText('loose thread');
    await userEvent.click(screen.getByRole('button', { name: 'move loose thread' }));
    await userEvent.click(screen.getByRole('menuitem', { name: 'Atlas' }));
    expect(useChat.getState().filed.c2).toBeUndefined();
    expect(useChat.getState().manualMoved.c2).toBe(true);
  });

  it('a tree drop marks the chat as manually moved', async () => {
    renderTree();
    await screen.findByText('loose thread');
    fireEvent.drop(screen.getByTestId('folder-work/atlas/'), { dataTransfer: dt({ [CHAT_DRAG_MIME]: leaf('c2') }) });
    expect(useChat.getState().manualMoved.c2).toBe(true);
  });

  it('flags chats whose location no longer exists', async () => {
    renderTree();
    await screen.findByText('ghost thread');
    expect(screen.getByTitle('its project or context no longer exists')).toBeInTheDocument();
  });

  it('shows the empty state when there are no chats', async () => {
    window.gb.api.request = vi.fn(async (method: string, path: string) => {
      if (path === '/v1/chat/tree') return { ok: true, data: { unfiled: [], scopes: [] } };
      return { ok: true, data: [] };
    }) as unknown as typeof window.gb.api.request;
    renderTree();
    expect(await screen.findByText('no conversations yet')).toBeInTheDocument();
  });
});

describe('FiledNotice', () => {
  it('renders the location, and Undo unfiles and hides it', async () => {
    useChat.setState({ filed: { c1: { context: 'work', project: 'atlas', folder: null } } });
    wrap(<FiledNotice convId="c1" />);
    expect(await screen.findByText('Filed under work / Atlas')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Undo' }));
    await waitFor(() => expect(mutations('PATCH')).toHaveLength(1));
    expect(mutations('PATCH')[0]).toMatchObject({ path: '/v1/chat/c1', body: { context: null, project: null, folder: null } });
    await waitFor(() => expect(screen.queryByText(/Filed under/)).not.toBeInTheDocument());
    expect(useChat.getState().manualMoved.c1).toBe(true);
  });

  it('context-only shows just the context; dismiss clears it', async () => {
    useChat.setState({ filed: { c1: { context: 'personal', project: null, folder: null } } });
    wrap(<FiledNotice convId="c1" />);
    expect(await screen.findByText('Filed under personal')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'dismiss' }));
    expect(screen.queryByText(/Filed under/)).not.toBeInTheDocument();
    expect(useChat.getState().filed.c1).toBeUndefined();
  });

  it('renders nothing for a chat that was not just filed', () => {
    const { container } = wrap(<FiledNotice convId="c9" />);
    expect(container).toBeEmptyDOMElement();
  });
});
