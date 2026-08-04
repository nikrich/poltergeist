import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { ConnectorsScreen } from '../screens/connectors';

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

// Shared need_input session — reused for both /auth/start and the poll's
// /auth/status response so the poll is a stable no-op (mirrors the pattern in
// connectors-connect.test.tsx).
const waitingInputSession = {
  session_id: 's1',
  status: 'waiting_input',
  account: null,
  error: null,
  next: {
    kind: 'need_input',
    fields: [{ name: 'token', label: 'Token', type: 'password' }],
    auth_url: null,
    verification_uri: null,
    user_code: null,
    message: 'paste it',
  },
};

beforeEach(() => {
  const request = vi.fn((method: string, path: string) => {
    // No connectors configured yet — exercises the "add connector" entry
    // point from an empty state, not just from an existing connector row.
    if (method === 'GET' && path === '/v1/connectors') {
      return Promise.resolve({ ok: true, status: 200, data: [] });
    }
    if (method === 'GET' && path === '/v1/scheduler/status') {
      return Promise.resolve({ ok: true, status: 200, data: { enabled: false, jobs: {} } });
    }
    if (method === 'GET' && path === '/v1/scheduler/diagnostics') {
      return Promise.resolve({
        ok: true,
        status: 200,
        data: {
          enabled: false,
          active_launchd_plists: [],
          double_scheduling: false,
          ffmpeg_available: true,
        },
      });
    }
    if (method === 'GET' && path.startsWith('/v1/connectors/slack/auth/status')) {
      return Promise.resolve({ ok: true, status: 200, data: waitingInputSession });
    }
    if (method === 'POST' && path === '/v1/connectors/slack/auth/start') {
      return Promise.resolve({ ok: true, status: 200, data: waitingInputSession });
    }
    return Promise.resolve({ ok: false, status: 500, error: `unexpected ${method} ${path}` });
  });
  window.gb = {
    ...window.gb,
    api: { request: request as typeof window.gb.api.request },
  } as typeof window.gb;
});

describe('ConnectorsScreen add-connector picker', () => {
  it('opens a connector picker, then the auth flow for the selected connector', async () => {
    render(wrap(<ConnectorsScreen />));

    const addBtn = await screen.findByRole('button', { name: /add connector/i });
    await userEvent.click(addBtn);

    // Picker lists catalog cards — Slack is one of CONNECTOR_CARDS.
    const slackCard = await screen.findByRole('button', { name: /slack/i });
    await userEvent.click(slackCard);

    // Selecting a card closes the picker and opens ConnectorAuthModal for it.
    expect(await screen.findByText(/connect slack/i)).toBeInTheDocument();
    // ConnectorAuthFlow's need_input step renders once /auth/start resolves.
    expect(await screen.findByLabelText('Token')).toBeInTheDocument();
  });
});
