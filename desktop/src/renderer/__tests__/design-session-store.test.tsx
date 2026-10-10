import { act, fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '../lib/api/client';
import { Toaster } from '../components/Toaster';
import { designSession, useDesignSession } from '../stores/design-session';
import { useToasts } from '../stores/toast';
import { makeSession } from './fixtures/design';

vi.mock('../lib/api/client', () => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
}));

beforeEach(() => {
  vi.clearAllMocks();
  useDesignSession.getState().reset();
  useToasts.setState({ toasts: [] });
});

describe('design session store', () => {
  it('replaces the session on snapshot and clears it on idle', () => {
    const { apply } = useDesignSession.getState();
    apply({ type: 'snapshot', session: makeSession({ id: 'a' }) });
    expect(useDesignSession.getState().session?.id).toBe('a');
    apply({ type: 'snapshot', session: makeSession({ id: 'b' }) });
    expect(useDesignSession.getState().session?.id).toBe('b');
    apply({ type: 'idle' });
    expect(useDesignSession.getState().session).toBeNull();
    expect(useDesignSession.getState().idle).toBe(true);
  });

  it('tracks the last revision and end', () => {
    const { apply } = useDesignSession.getState();
    apply({ type: 'revision', canvas: 'ui', rev: 3, summary: 'added login' });
    expect(useDesignSession.getState().lastRevision).toEqual({
      canvas: 'ui',
      rev: 3,
      summary: 'added login',
    });
    apply({ type: 'end' });
    expect(useDesignSession.getState().ended).toBe(true);
  });

  it('toasts errors', () => {
    useDesignSession.getState().apply({ type: 'error', canvas: 'ui', message: 'agent failed' });
    const toasts = useToasts.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0]?.kind).toBe('error');
    expect(toasts[0]?.message).toMatch(/agent failed/);
  });

  it('toasts spoken commands with an Undo that posts the token', () => {
    vi.mocked(client.post).mockResolvedValue({} as never);
    useDesignSession.getState().apply({
      type: 'command',
      command: 'start_ui',
      canvas: 'ui',
      label: 'Started frontend prototype',
      undo_token: 'tok-1',
      spoken: true,
    });
    render(<Toaster />);
    expect(screen.getByText('Started frontend prototype')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(client.post).toHaveBeenCalledWith('/v1/design/session/undo', { token: 'tok-1' });
    expect(useToasts.getState().toasts).toHaveLength(0);
  });

  it('shows no Undo when the command is not undoable', () => {
    act(() =>
      useDesignSession.getState().apply({
        type: 'command',
        command: 'nudge',
        canvas: 'ui',
        label: 'Noted',
        undo_token: null,
        spoken: true,
      }),
    );
    render(<Toaster />);
    expect(screen.getByText('Noted')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Undo' })).not.toBeInTheDocument();
  });

  it('does not toast commands that came from a button', () => {
    useDesignSession.getState().apply({
      type: 'command',
      command: 'pause',
      canvas: 'ui',
      label: 'Paused prototype',
      undo_token: 'tok-2',
      spoken: false,
    });
    expect(useToasts.getState().toasts).toHaveLength(0);
  });

  it('applies the snapshot a session POST answers with', async () => {
    const session = makeSession({ id: 'fresh', ui: { state: 'active' } });
    vi.mocked(client.post).mockResolvedValue({ event: null, session } as never);
    await designSession.start('ui');
    expect(useDesignSession.getState().session?.id).toBe('fresh');
  });

  it('toasts a spoken codebase match with Undo', () => {
    vi.mocked(client.post).mockResolvedValue({} as never);
    useDesignSession.getState().apply({
      type: 'command',
      command: 'codebase',
      canvas: 'ui',
      label: 'Using web-app',
      undo_token: 'tok-cb',
      spoken: true,
    });
    render(<Toaster />);
    expect(screen.getByText('Using web-app')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Undo' }));
    expect(client.post).toHaveBeenCalledWith('/v1/design/session/undo', { token: 'tok-cb' });
  });

  it("offers Choose repo when a spoken codebase couldn't be found", () => {
    useDesignSession.getState().apply({
      type: 'command',
      command: 'codebase',
      canvas: 'ui',
      label: "Couldn't find 'Billing' — using a scratch prototype",
      undo_token: null,
      spoken: true,
    });
    render(<Toaster />);
    expect(useDesignSession.getState().pickerOpen).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Choose repo' }));
    expect(useDesignSession.getState().pickerOpen).toBe(true);
  });

  it('posts the codebase choice', async () => {
    vi.mocked(client.post).mockResolvedValue({ event: null, session: makeSession() } as never);
    await designSession.codebase('/code/web');
    expect(client.post).toHaveBeenCalledWith('/v1/design/session/codebase', { path: '/code/web' });
    await designSession.codebase(null);
    expect(client.post).toHaveBeenCalledWith('/v1/design/session/codebase', { path: null });
  });

  it('offers Confirm on a spoken "Use …" codebase toast', () => {
    vi.mocked(client.post).mockResolvedValue({} as never);
    useDesignSession.setState({
      session: makeSession({
        ui_kind: 'worktree',
        codebase_confirmed: false,
        codebase: {
          repo: '/code/web-app',
          name: 'web-app',
          app_dir: '/code/web-app-poltergeist-x',
          worktree: '/code/web-app-poltergeist-x',
          branch: 'poltergeist/x',
          base: 'origin/main',
        },
      }),
    });
    useDesignSession.getState().apply({
      type: 'command',
      command: 'codebase',
      canvas: 'ui',
      label: 'Use web-app?',
      undo_token: 'tok-u',
      spoken: true,
    });
    render(<Toaster />);
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    expect(client.post).toHaveBeenCalledWith('/v1/design/session/codebase', { path: '/code/web-app' });
  });
});
