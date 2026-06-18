import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import * as hooks from '../lib/api/hooks';
import MicrosoftConnectCard from '../components/MicrosoftConnectCard';

function stubStatus(data: { state: string; account: string | null; error: string | null }) {
  vi.spyOn(hooks, 'useMicrosoftAuthStatus').mockReturnValue({ data } as never);
}

describe('MicrosoftConnectCard', () => {
  const start = vi.fn().mockResolvedValue({ state: 'pending' });
  const disconnect = vi.fn().mockResolvedValue({ state: 'idle' });

  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(hooks, 'useStartMicrosoftAuth').mockReturnValue({ mutateAsync: start } as never);
    vi.spyOn(hooks, 'useDisconnectMicrosoft').mockReturnValue({ mutateAsync: disconnect } as never);
  });

  it('shows connected account', () => {
    stubStatus({ state: 'connected', account: 'me@tenant', error: null });
    render(<MicrosoftConnectCard />);
    expect(screen.getByText(/me@tenant/)).toBeInTheDocument();
  });

  it('connect button triggers start when not connected', () => {
    stubStatus({ state: 'idle', account: null, error: null });
    render(<MicrosoftConnectCard />);
    fireEvent.click(screen.getByRole('button', { name: /connect microsoft/i }));
    expect(start).toHaveBeenCalled();
  });

  it('renders the error message', () => {
    stubStatus({ state: 'error', account: null, error: 'consent denied' });
    render(<MicrosoftConnectCard />);
    expect(screen.getByText(/consent denied/)).toBeInTheDocument();
  });
});
