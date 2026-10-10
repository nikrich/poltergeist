import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { VaultScreen } from '../screens/vault';
import { useGraphView } from '../stores/graph-view';

const request = vi.fn();
beforeEach(() => {
  request.mockReset();
  request.mockResolvedValue({ ok: true, data: { nodes: [], edges: [], regions: [] } });
  useGraphView.getState().reset();
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
    expect(screen.getByRole('tab', { name: 'constellation' })).toHaveAttribute('aria-selected', 'true');
  });

  it('switches to the graph tab', () => {
    renderScreen();
    fireEvent.click(screen.getByRole('tab', { name: 'graph' }));
    expect(screen.getByRole('tab', { name: 'graph' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText(/pick a page to centre the graph on/)).toBeInTheDocument();
    expect(useGraphView.getState().tab).toBe('graph');
  });
});
