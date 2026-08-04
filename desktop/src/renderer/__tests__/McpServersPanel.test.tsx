import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { McpServersPanel } from '../components/McpServersPanel';
import type { McpServersResponse } from '../../shared/api-types';

const apiRequest = vi.fn();

beforeEach(() => {
  apiRequest.mockReset();
  window.gb.api.request = apiRequest as typeof window.gb.api.request;
});

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <McpServersPanel />
    </QueryClientProvider>,
  );
}

const state: McpServersResponse = {
  servers: [
    {
      name: 'mempalace',
      command: 'npx',
      args: ['-y', 'mempalace-mcp'],
      envKeys: ['KEY'],
      enabled: true,
      tools: '',
    },
  ],
  available: [{ name: 'linear', command: 'npx', args: ['-y', 'linear-mcp'] }],
};

function mockGet() {
  apiRequest.mockImplementation(async (method: string) =>
    method === 'GET'
      ? { ok: true, status: 200, data: state }
      : { ok: true, status: 200, data: { servers: state.servers } },
  );
}

function lastPutServers() {
  const put = apiRequest.mock.calls.filter(([m]) => m === 'PUT').at(-1);
  expect(put).toBeTruthy();
  expect(put![1]).toBe('/v1/chat/mcp-servers');
  return (put![2] as { servers: unknown[] }).servers as Array<Record<string, unknown>>;
}

describe('McpServersPanel', () => {
  it('lists saved servers and import candidates', async () => {
    mockGet();
    renderPanel();
    expect(await screen.findByText('mempalace')).toBeInTheDocument();
    expect(screen.getByText('linear')).toBeInTheDocument();
  });

  it('toggling a server PUTs the flipped enabled state with env preserved', async () => {
    mockGet();
    renderPanel();
    await screen.findByText('mempalace');
    await userEvent.click(screen.getByRole('button', { pressed: true }));
    await waitFor(() => {
      const servers = lastPutServers();
      expect(servers[0]).toMatchObject({ name: 'mempalace', enabled: false, env: null });
    });
  });

  it('importing an available server PUTs it enabled with all tools', async () => {
    mockGet();
    renderPanel();
    await screen.findByText('linear');
    await userEvent.click(screen.getByRole('button', { name: /add linear/i }));
    await waitFor(() => {
      const servers = lastPutServers();
      expect(servers).toHaveLength(2);
      expect(servers[1]).toMatchObject({
        name: 'linear',
        command: 'npx',
        enabled: true,
        tools: '',
      });
    });
  });

  it('removing a server PUTs the list without it', async () => {
    mockGet();
    renderPanel();
    await screen.findByText('mempalace');
    await userEvent.click(screen.getByRole('button', { name: /remove mempalace/i }));
    await waitFor(() => {
      expect(lastPutServers()).toHaveLength(0);
    });
  });
});
