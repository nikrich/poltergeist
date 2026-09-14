import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import * as client from '../lib/api/client';
import { AiProviderSettings } from '../screens/settings';
import { ProviderSwitcher } from '../components/ProviderSwitcher';
import type { LlmProvidersResponse, LlmSettings } from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ...actual, get: vi.fn(), post: vi.fn(), put: vi.fn() };
});

// openai_http (= the "local" provider) fails its probe here on purpose: the
// settings panel must still let the user select `local` to configure it
// (allowUnavailable), while the plain chat-header switcher keeps it disabled.
const mixedProviders: LlmProvidersResponse = {
  active: 'claude',
  providers: {
    claude: { ok: true, reason: '2.1.0', detail: {} },
    codex: { ok: false, reason: 'not installed', detail: {} },
    gemini: { ok: false, reason: 'not installed', detail: {} },
    openai_http: { ok: false, reason: 'not answering', detail: { models: ['llama3.2', 'qwen3'] } },
  },
};

function makeSettings(overrides: Partial<LlmSettings> = {}): LlmSettings {
  return {
    provider: 'claude',
    models: { fast: null, balanced: null, quality: null },
    base_url: 'http://127.0.0.1:11434/v1',
    api_key_env: 'OPENAI_API_KEY',
    effective_models: { fast: 'claude-haiku-4-5', balanced: 'claude-sonnet-5', quality: 'claude-opus-5' },
    ...overrides,
  };
}

/** Stateful stub: PUT mutates the in-memory settings so a subsequent GET
 * (React Query's post-mutation refetch) reflects the change, mirroring how
 * the real sidecar persists and re-serves `/v1/settings/llm`. */
function stubApi(providers: LlmProvidersResponse, initialSettings: LlmSettings) {
  let current = initialSettings;
  vi.mocked(client.get).mockImplementation((path: string) => {
    if (path === '/v1/settings/llm') return Promise.resolve(current) as never;
    if (path === '/v1/llm/providers') return Promise.resolve(providers) as never;
    return Promise.reject(new Error(`unexpected path ${path}`)) as never;
  });
  vi.mocked(client.put).mockImplementation((path: string, body?: unknown) => {
    if (path !== '/v1/settings/llm') return Promise.reject(new Error(`unexpected PUT ${path}`)) as never;
    const patch = body as Partial<LlmSettings>;
    current = {
      ...current,
      ...patch,
      models: { ...current.models, ...(patch.models ?? {}) },
    };
    return Promise.resolve(current) as never;
  });
}

function renderWith(node: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('AiProviderSettings', () => {
  it('shows the active provider diagnostics and lets the user switch to local (even unavailable) with model pickers', async () => {
    stubApi(mixedProviders, makeSettings());
    renderWith(<AiProviderSettings />);

    expect(await screen.findByText(/2\.1\.0/)).toBeInTheDocument();

    // openai_http.ok === false here — the settings panel must still allow
    // selecting `local` so the user can configure it (see allowUnavailable).
    fireEvent.change(screen.getByLabelText(/provider/i), { target: { value: 'local' } });
    await waitFor(() =>
      expect(client.put).toHaveBeenCalledWith('/v1/settings/llm', { provider: 'openai_http' }),
    );

    expect(await screen.findByLabelText(/fast model/i)).toBeInTheDocument();
    expect(screen.getAllByRole('option', { name: 'qwen3' }).length).toBeGreaterThan(0);
  });
});

describe('ProviderSwitcher', () => {
  it('disables providers whose probe failed and blocks a PUT for a disabled selection', async () => {
    stubApi(mixedProviders, makeSettings());
    renderWith(<ProviderSwitcher />);

    const codex = await screen.findByRole('option', { name: /codex — not installed/ });
    expect(codex).toBeDisabled();
    expect(screen.getByRole('option', { name: /claude/ })).not.toBeDisabled();

    fireEvent.change(screen.getByLabelText(/provider/i), { target: { value: 'gemini' } });
    expect(client.put).not.toHaveBeenCalledWith('/v1/settings/llm', { provider: 'gemini' });
  });

  it('with allowUnavailable, a provider whose probe failed is still selectable and sends a PUT', async () => {
    stubApi(mixedProviders, makeSettings());
    renderWith(<ProviderSwitcher allowUnavailable />);

    const local = await screen.findByRole('option', { name: /local — not answering/ });
    expect(local).not.toBeDisabled();

    fireEvent.change(screen.getByLabelText(/provider/i), { target: { value: 'local' } });
    await waitFor(() =>
      expect(client.put).toHaveBeenCalledWith('/v1/settings/llm', { provider: 'openai_http' }),
    );
  });
});
