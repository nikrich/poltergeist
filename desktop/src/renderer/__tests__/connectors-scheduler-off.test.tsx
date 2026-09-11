import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { ConnectorsScreen } from '../screens/connectors';
import { useToasts } from '../stores/toast';
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

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

function renderConnectorsScreen() {
  return render(wrap(<ConnectorsScreen />));
}

beforeEach(() => {
  useToasts.setState({ toasts: [] });
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
    return Promise.resolve({ ok: false, status: 500, error: `unexpected ${method} ${path}` });
  });
  window.gb = {
    ...window.gb,
    api: { request: request as typeof window.gb.api.request },
  } as typeof window.gb;
});

describe('ConnectorsScreen sync now with scheduler off', () => {
  it('sync now with the scheduler off explains the setting instead of a dev placeholder', async () => {
    // Toaster (which renders toast messages into the DOM) is mounted only in
    // App.tsx, not by ConnectorsScreen, so we assert against the toast store
    // directly — matching the convention in RichMarkdownEditor.test.tsx's
    // "shows a success toast" tests.
    renderConnectorsScreen();
    fireEvent.click(await screen.findByRole('button', { name: /sync all/i }));
    await waitFor(() => {
      const messages = useToasts.getState().toasts.map((t) => t.message);
      expect(messages.some((m) => /scheduler is off/i.test(m))).toBe(true);
      expect(messages.some((m) => /Run scheduler in-app/.test(m))).toBe(true);
    });
    expect(
      useToasts.getState().toasts.some((t) => /wired in Slice/.test(t.message)),
    ).toBe(false);
  });
});
