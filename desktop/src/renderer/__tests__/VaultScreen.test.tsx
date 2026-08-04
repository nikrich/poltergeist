import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { VaultScreen } from '../screens/vault';

const request = vi.fn();
beforeEach(() => {
  request.mockReset();
  request.mockResolvedValue({ ok: true, data: { nodes: [], edges: [], regions: [] } });
  window.gb = {
    ...window.gb,
    api: { request },
    shell: { ...window.gb?.shell, openPath: vi.fn().mockResolvedValue({ ok: true }) },
  } as typeof window.gb;
});

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}><VaultScreen /></QueryClientProvider>);
}

describe('VaultScreen', () => {
  it('requests the vault graph and shows the empty state when there are no notes', async () => {
    renderScreen();
    expect(await screen.findByText(/your vault is on disk/i)).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith('GET', '/v1/vault/graph');
  });
});
