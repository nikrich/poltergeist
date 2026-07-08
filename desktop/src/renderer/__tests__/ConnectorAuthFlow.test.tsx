import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ConnectorAuthFlow } from '../components/ConnectorAuthFlow';

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  const responses: Record<string, unknown> = {
    'POST /v1/connectors/slack/auth/start': { session_id: 's', status: 'waiting_input', account: null, error: null,
      next: { kind: 'need_input', fields: [{ name: 'token', label: 'Token', type: 'password' }], auth_url: null, verification_uri: null, user_code: null, message: 'paste it' } },
    'POST /v1/connectors/slack/auth/submit': { session_id: 's', status: 'success', account: '@me', error: null,
      next: { kind: 'done', fields: null, auth_url: null, verification_uri: null, user_code: null, message: null } },
  };
  window.gb = {
    ...window.gb,
    api: { request: vi.fn((m: string, p: string) => Promise.resolve({ ok: true, data: responses[`${m} ${p}`] })) },
    shell: { openExternal: vi.fn().mockResolvedValue({ ok: true }) },
  };
});

describe('ConnectorAuthFlow', () => {
  it('renders need_input form then completes on submit', async () => {
    const onDone = vi.fn();
    wrap(<ConnectorAuthFlow connectorId="slack" onDone={onDone} onCancel={() => {}} />);
    await waitFor(() => screen.getByLabelText('Token'));
    fireEvent.change(screen.getByLabelText('Token'), { target: { value: 'xoxp-abc' } });
    fireEvent.click(screen.getByRole('button', { name: /connect|submit|save/i }));
    await waitFor(() => expect(onDone).toHaveBeenCalledWith('@me'));
  });

  it('shows an error state with retry when the status poll fails persistently', async () => {
    window.gb = {
    ...window.gb,
      api: {
        request: vi.fn((m: string, p: string) => {
          if (m === 'POST' && p === '/v1/connectors/slack/auth/start') {
            return Promise.resolve({
              ok: true,
              data: {
                session_id: 's', status: 'pending', account: null, error: null,
                next: { kind: 'open_browser', fields: null, auth_url: 'https://example.com/auth', verification_uri: null, user_code: null, message: null },
              },
            });
          }
          if (m === 'GET' && p.startsWith('/v1/connectors/slack/auth/status')) {
            return Promise.resolve({ ok: false, error: 'boom', status: 500 });
          }
          return Promise.resolve({ ok: false, error: 'unexpected', status: 500 });
        }),
      },
      shell: { openExternal: vi.fn().mockResolvedValue({ ok: true }) },
    };

    wrap(<ConnectorAuthFlow connectorId="slack" onDone={() => {}} onCancel={() => {}} />);

    expect(await screen.findByRole('button', { name: /retry/i })).toBeInTheDocument();
    expect(screen.getByText('boom')).toBeInTheDocument();
  });
});
