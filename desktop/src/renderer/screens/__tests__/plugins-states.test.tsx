import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { PluginsScreen } from '../plugins';

beforeEach(() => {
  window.gb.plugins.list = vi.fn(async () => []);
  window.gb.plugins.marketplace.list = vi.fn(async () => []);
});

describe('PluginsScreen states', () => {
  it('renders an inline error with retry when marketplace.list fails, and retry re-fetches', async () => {
    window.gb.plugins.marketplace.list = vi.fn(async () => ({ ok: false as const, error: 'boom' }));
    render(<PluginsScreen />);

    expect(await screen.findByText(/boom/)).toBeInTheDocument();
    const retryBtn = screen.getByRole('button', { name: /retry/i });

    const callsBefore = (window.gb.plugins.marketplace.list as ReturnType<typeof vi.fn>).mock.calls.length;
    await userEvent.click(retryBtn);
    await waitFor(() =>
      expect((window.gb.plugins.marketplace.list as ReturnType<typeof vi.fn>).mock.calls.length).toBeGreaterThan(
        callsBefore,
      ),
    );
  });

  it('renders distinct empty-state copy for an empty installed list and empty marketplace', async () => {
    render(<PluginsScreen />);

    expect(await screen.findByText(/nothing haunting this app yet/i)).toBeInTheDocument();
    expect(screen.getByText(/no plugins in the marketplace yet/i)).toBeInTheDocument();
  });

  it('shows a loading placeholder instead of "…" while records/listings are pending', async () => {
    window.gb.plugins.list = vi.fn(() => new Promise<never>(() => {}));
    window.gb.plugins.marketplace.list = vi.fn(() => new Promise<never>(() => {}));
    render(<PluginsScreen />);

    expect(screen.queryByText('…')).not.toBeInTheDocument();
    expect(screen.getAllByTestId(/-skeleton$/).length).toBeGreaterThan(0);
  });
});
