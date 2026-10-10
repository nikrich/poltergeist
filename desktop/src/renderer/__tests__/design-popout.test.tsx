import { act, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '../lib/api/client';
import { DesignPopout, isDesignPopoutRoute } from '../screens/design-popout';
import { useDesignSession } from '../stores/design-session';
import { makeSession, sampleBoard } from './fixtures/design';
import type { DesignLiveEvent } from '../../shared/design-types';

vi.mock('../lib/api/client', () => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(client.get).mockRejectedValue(new Error('404'));
  useDesignSession.getState().reset();
});

describe('design pop-out', () => {
  it('recognises its hash route', () => {
    expect(isDesignPopoutRoute('#/design-popout')).toBe(true);
    expect(isDesignPopoutRoute('')).toBe(false);
    expect(isDesignPopoutRoute('#/today')).toBe(false);
  });

  it('subscribes to the design stream and shows only the focused canvas', () => {
    let emit: ((e: DesignLiveEvent) => void) | null = null;
    const on = vi.spyOn(window.gb, 'on').mockImplementation(((channel: string, cb: never) => {
      if (channel === 'design:live:event') emit = cb;
      return () => {};
    }) as never);
    const subscribe = vi.spyOn(window.gb.design, 'liveSubscribe');

    render(<DesignPopout />);
    expect(subscribe).toHaveBeenCalled();
    expect(screen.getByText(/waiting for a live design session/i)).toBeInTheDocument();

    act(() =>
      emit!({
        type: 'snapshot',
        session: makeSession({
          focus: 'board',
          board: { state: 'active', rev: 1, running: true },
          boardModel: sampleBoard,
        }),
      }),
    );
    expect(screen.getByText('Order placed')).toBeInTheDocument();
    expect(screen.getByText('Checkout redesign')).toBeInTheDocument();
    expect(screen.getByText('Updating…')).toBeInTheDocument();
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
    on.mockRestore();
  });
});
