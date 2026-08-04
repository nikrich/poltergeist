import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import React from 'react';

import { OnboardingScreen } from '../screens/onboarding';
import { useNavigation } from '../stores/navigation';
import { useSettings } from '../stores/settings';
import type { Connector } from '../../shared/api-types';

const emptyConnectors: Connector[] = [];

// Shared need_input session for the slack paste-token auth pattern — reused
// for both /auth/start and the poll's /auth/status response so the poll is a
// stable no-op rather than racing the need_input step.
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

function wrap(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{node}</QueryClientProvider>;
}

beforeEach(() => {
  useNavigation.setState({ active: 'onboarding' });
  useSettings.setState({ onboardingComplete: false, schedulerEnabled: false });

  const request = vi.fn((method: string, path: string) => {
    if (method === 'GET' && path === '/v1/connectors') {
      return Promise.resolve({ ok: true, status: 200, data: emptyConnectors });
    }
    if (method === 'POST' && path === '/v1/connectors/slack/auth/start') {
      return Promise.resolve({ ok: true, status: 200, data: waitingInputSession });
    }
    if (method === 'GET' && path.startsWith('/v1/connectors/slack/auth/status')) {
      return Promise.resolve({ ok: true, status: 200, data: waitingInputSession });
    }
    return Promise.resolve({ ok: false, status: 500, error: `unexpected ${method} ${path}` });
  });
  window.gb = {
    ...window.gb,
    api: { request: request as typeof window.gb.api.request },
  } as typeof window.gb;
});

describe('OnboardingScreen', () => {
  it('renders the welcome step and advances to the vault step', async () => {
    render(wrap(<OnboardingScreen />));

    expect(await screen.findByText(/welcome to poltergeist/i)).toBeInTheDocument();

    await userEvent.click(screen.getByRole('button', { name: /get started/i }));

    expect(await screen.findByText(/vault path/i)).toBeInTheDocument();
  });

  it('walks pick → connect and shows ConnectorAuthFlow for the selected card', async () => {
    render(wrap(<OnboardingScreen />));

    await userEvent.click(await screen.findByRole('button', { name: /get started/i }));
    await userEvent.click(await screen.findByRole('button', { name: /^continue$/i }));

    const slackCheckbox = await screen.findByRole('checkbox', { name: /slack/i });
    await userEvent.click(slackCheckbox);
    await userEvent.click(screen.getByRole('button', { name: /^continue$/i }));

    // The connect step's progress indicator and the auth flow's first field.
    expect(await screen.findByText(/1 of 1/i)).toBeInTheDocument();
    expect(await screen.findByLabelText('Token')).toBeInTheDocument();
  });

  it('"I\'ll do this later" sets onboardingComplete and navigates away', async () => {
    const setSpy = vi.fn(async () => ({ ok: true as const }));
    window.gb.settings.set = setSpy as typeof window.gb.settings.set;

    render(wrap(<OnboardingScreen />));

    await userEvent.click(await screen.findByRole('button', { name: /do this later/i }));

    expect(setSpy).toHaveBeenCalledWith('onboardingComplete', true);
    expect(useNavigation.getState().active).toBe('connectors');
  });
});
