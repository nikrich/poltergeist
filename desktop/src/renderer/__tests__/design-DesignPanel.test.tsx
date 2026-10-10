import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '../lib/api/client';
import { DesignPanel } from '../components/design/DesignPanel';
import { useDesignSession } from '../stores/design-session';
import { useToasts } from '../stores/toast';
import { makeSession, sampleBoard } from './fixtures/design';
import type { CodebaseCandidate, DesignSessionSnapshot } from '../../shared/design-types';
import type { Project } from '../../shared/api-types';

vi.mock('../lib/api/client', () => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
}));

const projects: Project[] = [
  {
    id: 'work/checkout',
    context: 'work',
    slug: 'checkout',
    name: 'Checkout',
    description: '',
    archived: false,
    created_at: 1,
    design_system: null,
  },
];

const codebases: CodebaseCandidate[] = [
  { path: '/code/acme/web-app', rel: 'acme/web-app', name: 'web-app', frontend: true },
  { path: '/code/shop/storefront', rel: 'shop/storefront', name: 'storefront', frontend: true },
];

const worktreeInfo = {
  repo: '/code/acme/web-app',
  name: 'web-app',
  app_dir: '/code/acme/web-app-poltergeist-2026-10-10-login',
  worktree: '/code/acme/web-app-poltergeist-2026-10-10-login',
  branch: 'poltergeist/2026-10-10-login',
  base: 'origin/main',
};

function setSession(session: DesignSessionSnapshot | null) {
  act(() => useDesignSession.setState({ session }));
}

function renderPanel() {
  vi.mocked(client.get).mockImplementation(((path: string) => {
    if (path.startsWith('/v1/projects')) return Promise.resolve(projects);
    if (path === '/v1/design/packs')
      return Promise.resolve([
        { id: 'poltergeist-neutral', name: 'Neutral', source: 'builtin', imported_at: null, builtin: true },
        { id: 'acme', name: 'Acme', source: 'https://acme.design', imported_at: '2026-10-01', builtin: false },
      ]);
    if (path.startsWith('/v1/design/codebases'))
      return Promise.resolve(
        path.includes('q=shop')
          ? [codebases[1]]
          : codebases,
      );
    return Promise.reject(new Error(`unexpected GET ${path}`));
  }) as never);
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <DesignPanel />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(client.post).mockResolvedValue({} as never);
  useDesignSession.getState().reset();
  useToasts.setState({ toasts: [] });
});

describe('DesignPanel', () => {
  it('collapses to a hint bar while every canvas is off', () => {
    setSession(makeSession());
    renderPanel();
    expect(screen.getByText(/let's kick off a frontend prototype/i)).toBeInTheDocument();
    expect(screen.queryByRole('tab')).not.toBeInTheDocument();
  });

  it('starts a canvas from the collapsed bar', async () => {
    setSession(makeSession());
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /start prototype/i }));
    await waitFor(() =>
      expect(client.post).toHaveBeenCalledWith('/v1/design/session/start', { canvas: 'ui' }),
    );
  });

  it('shows tabs with the focused one marked, and switching only changes the view', () => {
    setSession(
      makeSession({
        focus: 'board',
        ui: { state: 'paused', rev: 2 },
        board: { state: 'active', rev: 1 },
        boardModel: sampleBoard,
      }),
    );
    renderPanel();
    const boardTab = screen.getByRole('tab', { name: /board/i });
    expect(boardTab).toHaveAttribute('aria-selected', 'true');
    expect(boardTab).toHaveAttribute('data-focused', 'true');
    expect(screen.getByText('Order placed')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('tab', { name: /prototype/i }));
    expect(screen.getByRole('tab', { name: /prototype/i })).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByText('Order placed')).not.toBeInTheDocument();
    expect(client.post).not.toHaveBeenCalled();
  });

  it('shows the state pill for the focused canvas', () => {
    setSession(makeSession({ focus: 'ui', ui: { state: 'active', rev: 1 } }));
    renderPanel();
    expect(screen.getByText('Listening · UI')).toBeInTheDocument();
    setSession(makeSession({ focus: 'ui', ui: { state: 'active', rev: 1, running: true } }));
    expect(screen.getByText('Updating…', { selector: '[data-pill]' })).toBeInTheDocument();
    setSession(makeSession({ focus: 'ui', ui: { state: 'paused', rev: 1 } }));
    expect(screen.getByText('Paused', { selector: '[data-pill]' })).toBeInTheDocument();
  });

  it('offers Start on the empty state of an off canvas', async () => {
    setSession(makeSession({ focus: 'ui', ui: { state: 'active', rev: 1 } }));
    renderPanel();
    fireEvent.click(screen.getByRole('tab', { name: /board/i }));
    fireEvent.click(screen.getByRole('button', { name: /start board/i }));
    await waitFor(() =>
      expect(client.post).toHaveBeenCalledWith('/v1/design/session/start', { canvas: 'board' }),
    );
  });

  it('sends a nudge for the visible canvas on Enter', async () => {
    setSession(makeSession({ focus: 'ui', ui: { state: 'active', rev: 1 } }));
    renderPanel();
    const input = screen.getByPlaceholderText(/nudge/i);
    fireEvent.change(input, { target: { value: 'make the button green' } });
    fireEvent.keyDown(input, { key: 'Enter' });
    await waitFor(() =>
      expect(client.post).toHaveBeenCalledWith('/v1/design/session/nudge', {
        canvas: 'ui',
        text: 'make the button green',
      }),
    );
    await waitFor(() => expect(input).toHaveValue(''));
  });

  it('updates now from the button and the keyboard shortcut', async () => {
    setSession(makeSession({ focus: 'ui', ui: { state: 'active', rev: 1 } }));
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /update now/i }));
    await waitFor(() =>
      expect(client.post).toHaveBeenCalledWith('/v1/design/session/update', { canvas: 'ui' }),
    );
    vi.mocked(client.post).mockClear();
    fireEvent.keyDown(window, { key: 'U', shiftKey: true, metaKey: true });
    await waitFor(() =>
      expect(client.post).toHaveBeenCalledWith('/v1/design/session/update', { canvas: 'ui' }),
    );
  });

  it('pauses and resumes the visible canvas', async () => {
    setSession(makeSession({ focus: 'ui', ui: { state: 'active', rev: 1 } }));
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /^pause$/i }));
    await waitFor(() =>
      expect(client.post).toHaveBeenCalledWith('/v1/design/session/pause', { canvas: 'ui' }),
    );
    setSession(makeSession({ focus: 'ui', ui: { state: 'paused', rev: 1 } }));
    fireEvent.click(screen.getByRole('button', { name: /^resume$/i }));
    await waitFor(() =>
      expect(client.post).toHaveBeenCalledWith('/v1/design/session/resume', { canvas: 'ui' }),
    );
  });

  it('confirms inline before restoring an older revision', async () => {
    const revs = [1, 2, 3].map((rev) => ({ rev, at: '2026-10-10T10:00:00Z', summary: `rev ${rev}` }));
    setSession(makeSession({ focus: 'ui', ui: { state: 'active', rev: 3, revs } }));
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /previous revision/i }));
    fireEvent.click(screen.getByRole('button', { name: /previous revision/i }));
    expect(screen.getByText('Restore rev 1?')).toBeInTheDocument();
    expect(client.post).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: /^restore$/i }));
    await waitFor(() =>
      expect(client.post).toHaveBeenCalledWith('/v1/design/session/revert', { canvas: 'ui', rev: 1 }),
    );
  });

  it('changes the project and design system through config', async () => {
    setSession(makeSession({ focus: 'ui', ui: { state: 'active', rev: 1 } }));
    renderPanel();
    await screen.findByRole('option', { name: 'Checkout' });
    fireEvent.change(screen.getByLabelText('Project'), { target: { value: 'work/checkout' } });
    await waitFor(() =>
      expect(client.post).toHaveBeenCalledWith('/v1/design/session/config', {
        project_id: 'work/checkout',
      }),
    );
    await screen.findByRole('option', { name: 'Acme' });
    fireEvent.change(screen.getByLabelText('Design system'), { target: { value: 'acme' } });
    await waitFor(() =>
      expect(client.post).toHaveBeenCalledWith('/v1/design/session/config', { pack_id: 'acme' }),
    );
  });

  it('pops out', () => {
    const openPopout = vi.spyOn(window.gb.design, 'openPopout');
    setSession(makeSession({ focus: 'ui', ui: { state: 'active', rev: 1 } }));
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /pop out/i }));
    expect(openPopout).toHaveBeenCalled();
  });

  it('ejects an ended prototype and shows the folder', async () => {
    vi.mocked(client.post).mockResolvedValue({ path: '/vault/proto' } as never);
    const show = vi.spyOn(window.gb.shell, 'showItemInFolder');
    setSession(makeSession({ focus: 'ui', ui: { state: 'ended', rev: 4 } }));
    renderPanel();
    fireEvent.click(screen.getByRole('button', { name: /eject/i }));
    expect(await screen.findByText('/vault/proto')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /show in folder/i }));
    expect(show).toHaveBeenCalledWith('/vault/proto');
  });

  describe('codebase', () => {
    it('shows Scratch and picks a repo from the searchable list', async () => {
      setSession(makeSession({ focus: 'ui', ui: { state: 'active', rev: 0 } }));
      renderPanel();
      fireEvent.click(screen.getByRole('button', { name: /codebase: scratch/i }));
      expect(await screen.findByText('web-app')).toBeInTheDocument();
      expect(screen.getByText('acme/web-app')).toBeInTheDocument();
      expect(client.get).toHaveBeenCalledWith('/v1/design/codebases?q=');

      fireEvent.change(screen.getByPlaceholderText(/search repos/i), { target: { value: 'shop' } });
      await waitFor(() => expect(client.get).toHaveBeenCalledWith('/v1/design/codebases?q=shop'));
      await waitFor(() => expect(screen.queryByText('web-app')).not.toBeInTheDocument());
      fireEvent.click(screen.getByRole('option', { name: /storefront/i }));
      await waitFor(() =>
        expect(client.post).toHaveBeenCalledWith('/v1/design/session/codebase', {
          path: '/code/shop/storefront',
        }),
      );
      expect(screen.queryByPlaceholderText(/search repos/i)).not.toBeInTheDocument();
    });

    it('switches back to a scratch prototype', async () => {
      setSession(
        makeSession({ focus: 'ui', ui: { state: 'active', rev: 0 }, ui_kind: 'worktree', codebase: worktreeInfo }),
      );
      renderPanel();
      fireEvent.click(
        screen.getByRole('button', { name: /codebase: web-app · poltergeist\/2026-10-10-login/i }),
      );
      fireEvent.click(await screen.findByRole('option', { name: /scratch prototype/i }));
      await waitFor(() =>
        expect(client.post).toHaveBeenCalledWith('/v1/design/session/codebase', { path: null }),
      );
    });

    it('is locked once the prototype has a revision', () => {
      setSession(makeSession({ focus: 'ui', ui: { state: 'active', rev: 1 } }));
      renderPanel();
      const chip = screen.getByRole('button', { name: /codebase: scratch/i });
      expect(chip).toBeDisabled();
      expect(chip).toHaveAttribute('title', expect.stringMatching(/start a new session/i));
    });

    it('opens from the store (the "Choose repo" toast action)', async () => {
      setSession(makeSession({ focus: 'ui', ui: { state: 'active', rev: 0 } }));
      renderPanel();
      expect(screen.queryByPlaceholderText(/search repos/i)).not.toBeInTheDocument();
      act(() => useDesignSession.getState().setPickerOpen(true));
      expect(await screen.findByPlaceholderText(/search repos/i)).toBeInTheDocument();
    });

    it('shows the dependency install while it runs', () => {
      setSession(
        makeSession({
          focus: 'ui',
          ui: { state: 'active', rev: 0, running: true },
          ui_kind: 'worktree',
          codebase: worktreeInfo,
          install: 'running',
        }),
      );
      renderPanel();
      expect(screen.getByText(/installing dependencies/i)).toBeInTheDocument();
    });

    it('asks before building on a spoken repo, and both answers post the choice', async () => {
      setSession(
        makeSession({
          focus: 'ui',
          ui: { state: 'active', rev: 0 },
          ui_kind: 'worktree',
          codebase: worktreeInfo,
          codebase_confirmed: false,
        }),
      );
      renderPanel();
      expect(screen.getByText(/will create a worktree, install its dependencies/i)).toBeInTheDocument();
      expect(screen.queryByText(/listening for the first design discussion/i)).not.toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: 'Use web-app' }));
      await waitFor(() =>
        expect(client.post).toHaveBeenCalledWith('/v1/design/session/codebase', {
          path: '/code/acme/web-app',
        }),
      );
      fireEvent.click(screen.getByRole('button', { name: /scratch instead/i }));
      await waitFor(() =>
        expect(client.post).toHaveBeenCalledWith('/v1/design/session/codebase', { path: null }),
      );
    });

    it('does not offer Eject for a worktree prototype', () => {
      setSession(
        makeSession({ focus: 'ui', ui: { state: 'ended', rev: 2 }, ui_kind: 'worktree', codebase: worktreeInfo }),
      );
      renderPanel();
      expect(screen.queryByRole('button', { name: /eject/i })).not.toBeInTheDocument();
    });

    it('offers scratch when the worktree could not be prepared', async () => {
      setSession(
        makeSession({
          focus: 'ui',
          ui: { state: 'unavailable', rev: 0, reason: 'Dependency install failed: npm ERR! boom' },
          ui_kind: 'worktree',
          codebase: worktreeInfo,
          install: 'failed',
        }),
      );
      renderPanel();
      expect(screen.getByText(/npm ERR! boom/)).toBeInTheDocument();
      fireEvent.click(screen.getByRole('button', { name: /use scratch instead/i }));
      await waitFor(() =>
        expect(client.post).toHaveBeenCalledWith('/v1/design/session/codebase', { path: null }),
      );
    });
  });
});
