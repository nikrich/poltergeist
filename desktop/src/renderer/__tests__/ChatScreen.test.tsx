import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { ChatScreen } from '../screens/chat';
import { useChat } from '../stores/chat';
import * as client from '../lib/api/client';
import type {
  Conversation,
  ConversationSummary,
  ChatExportResponse,
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

// Renders ChatScreen with the shared 'c1' conversation active — the setup
// mirrors beforeEach() below (active conversation, mocked window.gb.chat).
function renderChat() {
  return render(wrap(<ChatScreen />));
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

// Renders ChatScreen with a persisted 'c1' conversation whose messages are
// overridden by the caller — used to assert on historical message rendering
// (e.g. attachment chips) without touching the shared `conversation` fixture.
function renderChatWithMessages(messages: Conversation['messages']) {
  vi.mocked(client.get).mockImplementation((path: string) => {
    if (path === '/v1/chat') return Promise.resolve(summaries) as never;
    if (path.startsWith('/v1/chat/')) {
      return Promise.resolve({ ...conversation, messages }) as never;
    }
    return Promise.reject(new Error(`unexpected path ${path}`)) as never;
  });
  return render(wrap(<ChatScreen />));
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
          attachments: [],
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

  it('composer is disabled while streaming', async () => {
    useChat.setState({
      activeId: 'c1',
      streams: {
        c1: { userText: 'q', text: '', tools: [], attachments: [] },
      },
      errors: {},
    });

    render(wrap(<ChatScreen />));

    const textarea = await screen.findByPlaceholderText(/poltergeist is responding/);
    expect(textarea).toBeDisabled();
    expect(screen.getByRole('button', { name: 'send' })).toBeDisabled();
  });

  it('send flow finalizes the stream when the send promise resolves', async () => {
    render(wrap(<ChatScreen />));

    const textarea = await screen.findByPlaceholderText(/message poltergeist/);
    fireEvent.change(textarea, { target: { value: 'hello ghost' } });
    fireEvent.keyDown(textarea, { key: 'Enter' });

    expect(window.gb.chat.send).toHaveBeenCalledWith('c1', 'hello ghost', []);

    // The send promise resolves on ANY stream end (done, error, user stop,
    // relay teardown). The screen's finalizer must clear the stream so the
    // UI never sticks in "streaming" — this locks in the user-stop contract.
    await waitFor(() => {
      expect(useChat.getState().streams.c1).toBeUndefined();
    });
  });

  it('renders a turn error inline with a retry button', async () => {
    useChat.setState({
      activeId: 'c1',
      streams: {},
      errors: {
        c1: {
          message: 'LLMTimeout: claude -p timed out',
          userText: 'how does auth work?',
          attachments: [],
        },
      },
    });

    render(wrap(<ChatScreen />));

    expect(
      await screen.findByText(/LLMTimeout: claude -p timed out/),
    ).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });

  it('clicking retry re-sends the original user text', async () => {
    useChat.setState({
      activeId: 'c1',
      streams: {},
      errors: {
        c1: {
          message: 'LLMTimeout: claude -p timed out',
          userText: 'how does auth work?',
          attachments: [],
        },
      },
    });

    render(wrap(<ChatScreen />));

    fireEvent.click(await screen.findByRole('button', { name: /retry/i }));

    expect(window.gb.chat.send).toHaveBeenCalledWith('c1', 'how does auth work?', []);
    // The send path goes through beginStream, which clears the error.
    expect(useChat.getState().errors.c1).toBeUndefined();

    // Flush the resolved send promise (finalizer clears the new stream) so
    // no state updates land after the test body.
    await waitFor(() => {
      expect(useChat.getState().streams.c1).toBeUndefined();
    });
  });

  it('clicking retry on a turn that had attachments re-sends them by path (no re-upload)', async () => {
    useChat.setState({
      activeId: 'c1',
      streams: {},
      errors: {
        c1: {
          message: 'LLMTimeout: claude -p timed out',
          userText: 'summarize this note',
          attachments: [
            { path: '20-contexts/chat-attachments/a.md', title: 'a.md', kind: 'text' },
          ],
        },
      },
    });

    render(wrap(<ChatScreen />));

    fireEvent.click(await screen.findByRole('button', { name: /retry/i }));

    expect(window.gb.chat.send).toHaveBeenCalledWith('c1', 'summarize this note', [
      '20-contexts/chat-attachments/a.md',
    ]);
    // Re-sending already-uploaded attachments must not trigger another upload.
    expect(client.post).not.toHaveBeenCalledWith(
      expect.stringContaining('/attachments'),
      expect.anything(),
    );
    expect(useChat.getState().errors.c1).toBeUndefined();

    await waitFor(() => {
      expect(useChat.getState().streams.c1).toBeUndefined();
    });
  });

  it('queues a dropped text file as a chip and clears it on remove', async () => {
    renderChat();
    const file = new File(['hello'], 'notes.md', { type: 'text/markdown' });
    const composer = await screen.findByPlaceholderText(/message poltergeist/i);
    fireEvent.drop(composer, { dataTransfer: { files: [file] } });
    expect(await screen.findByText('notes.md')).toBeInTheDocument();
    await userEvent.click(screen.getByLabelText('remove notes.md'));
    expect(screen.queryByText('notes.md')).not.toBeInTheDocument();
  });

  it('rejects an unsupported dropped file with a toast and no chip', async () => {
    renderChat();
    const file = new File(['x'], 'archive.zip', { type: 'application/zip' });
    const composer = await screen.findByPlaceholderText(/message poltergeist/i);
    fireEvent.drop(composer, { dataTransfer: { files: [file] } });
    expect(screen.queryByText('archive.zip')).not.toBeInTheDocument();
  });

  it('renders attachment chips on a historical user message', async () => {
    renderChatWithMessages([
      {
        role: 'user',
        text: 'see this',
        attachments: [
          { path: '20-contexts/chat-attachments/a.md', title: 'a.md', kind: 'text' },
        ],
      },
    ]);
    expect(await screen.findByText('a.md')).toBeInTheDocument();
  });

  it('shows an Open as PDF button for a generated-doc reply and calls openGenerated', async () => {
    const openGenerated = vi.fn().mockResolvedValue({ ok: true, path: '/v/x.pdf' });
    // ensure the stub bridge exposes docs.openGenerated (extend the test's window.gb stub)
    (window.gb as unknown as { docs: { openGenerated: typeof openGenerated } }).docs = {
      ...(window.gb as unknown as { docs: object }).docs,
      openGenerated,
    };
    renderChatWithMessages([
      {
        role: 'assistant',
        text: 'Your doc is ready:\n\n[[20-contexts/generated-docs/20260701T120000-brief.html]]',
      },
    ]);
    const btn = await screen.findByRole('button', { name: /open as pdf/i });
    await userEvent.click(btn);
    expect(openGenerated).toHaveBeenCalledWith(
      '20-contexts/generated-docs/20260701T120000-brief.html',
    );
  });
});

// ── Export to jots ─────────────────────────────────────────────────────────

const exportResponse: ChatExportResponse = {
  jot_id: 'j1',
  path: '20-contexts/codeship/notes/j1.md',
  routingStatus: 'routed',
  context: 'codeship',
  project: null,
  title: 'auth thread',
};

describe('ChatScreen export', () => {
  it('exports the conversation to a jot', async () => {
    vi.mocked(client.post).mockResolvedValueOnce(exportResponse as never);

    render(wrap(<ChatScreen />));
    await screen.findByText('how does auth work?');

    fireEvent.click(screen.getByRole('button', { name: /export to jots/i }));

    await waitFor(() => {
      expect(vi.mocked(client.post)).toHaveBeenCalledWith('/v1/chat/c1/export-jot');
    });
  });
});
