import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { ConnectorsScreen } from '../screens/connectors';
import type { Connector, ConnectorDetail } from '../../shared/api-types';

const slackList: Connector[] = [
  {
    id: 'slack',
    displayName: 'Slack',
    state: 'off',
    count: 0,
    lastSyncAt: null,
    account: null,
    throughput: null,
    error: null,
  },
];

const slackDetail: ConnectorDetail = {
  ...slackList[0]!,
  scopes: ['channels:history'],
  pulls: ['messages'],
  vaultDestination: '20-contexts/slack',
};

const slackConnected: Connector = {
  id: 'slack',
  displayName: 'Slack',
  state: 'on',
  count: 42,
  lastSyncAt: '2026-07-08T12:00:00Z',
  account: 'work',
  throughput: '5 events/min',
  error: null,
};

const slackConnectedDetail: ConnectorDetail = {
  ...slackConnected,
  scopes: ['channels:history'],
  pulls: ['messages'],
  vaultDestination: '20-contexts/slack',
};

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

// Shared need_input session — reused for both /auth/start and the poll's
// /auth/status response so the poll is a stable no-op rather than racing the
// need_input step with an undefined query result (React Query rejects a
// queryFn resolving to undefined).
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
    if (method === 'GET' && path === '/v1/connectors') {
      return Promise.resolve({ ok: true, status: 200, data: slackList });
    }
    if (method === 'GET' && path === '/v1/connectors/slack') {
      return Promise.resolve({ ok: true, status: 200, data: slackDetail });
    }
    if (method === 'GET' && path === '/v1/scheduler/status') {
      return Promise.resolve({
        ok: true,
        status: 200,
        data: { enabled: false, jobs: {} },
      });
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
      // Stable no-op poll — the same session the /auth/start call returned.
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

describe('ConnectorsScreen connect flow', () => {
  it('opens the auth flow when clicking connect on an off connector', async () => {
    render(wrap(<ConnectorsScreen />));

    const connectBtn = await screen.findByRole('button', { name: /connect slack/i });
    await userEvent.click(connectBtn);

    // The auth flow's need_input step renders the Token field once /auth/start resolves.
    expect(await screen.findByLabelText('Token')).toBeInTheDocument();
  });
});

describe('ConnectorsScreen disconnect flow', () => {
  it('sends DELETE request when clicking disconnect', async () => {
    // Create request mock specifically for this test with DELETE support
    const request = vi.fn((method: string, path: string) => {
      if (method === 'GET' && path === '/v1/connectors') {
        return Promise.resolve({ ok: true, status: 200, data: [slackConnected] });
      }
      if (method === 'GET' && path === '/v1/connectors/slack') {
        return Promise.resolve({ ok: true, status: 200, data: slackConnectedDetail });
      }
      if (method === 'GET' && path === '/v1/scheduler/status') {
        return Promise.resolve({
          ok: true,
          status: 200,
          data: { enabled: false, jobs: {} },
        });
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
      if (method === 'DELETE' && path === '/v1/connectors/slack/credentials') {
        return Promise.resolve({ ok: true, status: 200 });
      }
      return Promise.resolve({ ok: false, status: 500, error: `unexpected ${method} ${path}` });
    });

    // Override the API request for this test
    const originalRequest = window.gb.api.request;
    window.gb.api.request = request as typeof window.gb.api.request;

    // Mock window.confirm to return true
    const originalConfirm = window.confirm;
    window.confirm = vi.fn(() => true);

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <ConnectorsScreen />
      </QueryClientProvider>,
    );

    // Wait for the list to load
    await waitFor(() => {
      expect(screen.getByText('Slack')).toBeInTheDocument();
    });

    // Wait for detail panel to render by checking for detail content
    await waitFor(() => {
      expect(screen.getByText('channels:history')).toBeInTheDocument();
    });

    // Find and click the disconnect button (in detail panel, not the filter chip)
    const allBtns = screen.getAllByRole('button');
    const disconnectBtn = allBtns.find(btn => {
      // The disconnect button in the detail panel has the unplug icon and "disconnect" text
      const text = btn.textContent || '';
      return text.toLowerCase().includes('disconnect') && btn.className.includes('oxblood');
    });
    expect(disconnectBtn).toBeInTheDocument();
    await userEvent.click(disconnectBtn!);

    // Verify the DELETE request was sent and succeeded
    await waitFor(() => {
      expect(request).toHaveBeenCalledWith(
        'DELETE',
        expect.stringContaining('/v1/connectors/slack/credentials'),
      );
    });

    // Cleanup
    window.gb.api.request = originalRequest;
    window.confirm = originalConfirm;
  });
});
