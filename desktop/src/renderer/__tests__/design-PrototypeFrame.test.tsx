import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '../lib/api/client';
import { PrototypeFrame } from '../components/design/PrototypeFrame';
import { makeSession } from './fixtures/design';
import type { CodebaseInfo, DesignBuildResult, DevServerResult } from '../../shared/design-types';

vi.mock('../lib/api/client', () => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
}));

const DIR = '/vault/proto';
const originalBuild = window.gb.design.build;
let build: ReturnType<typeof vi.fn<(dir: string, rev: number) => Promise<DesignBuildResult>>>;

// jsdom fires `load` on its own whenever an iframe's src changes; hold those
// back so each test decides when the next bundle has "loaded".
let allowLoad = false;
const blockLoad = (e: Event) => {
  if (!allowLoad && e.target instanceof HTMLIFrameElement) e.stopPropagation();
};
function load(el: HTMLIFrameElement) {
  allowLoad = true;
  fireEvent.load(el);
  allowLoad = false;
}

beforeEach(() => {
  document.addEventListener('load', blockLoad, true);
  vi.clearAllMocks();
  vi.mocked(client.post).mockResolvedValue({} as never);
  build = vi.fn(async (_dir: string, rev: number) => ({
    ok: true as const,
    rev,
    url: `gbproto://prototype/index.html?rev=${rev}`,
  }));
  window.gb.design.build = build;
});

afterEach(() => {
  document.removeEventListener('load', blockLoad, true);
  window.gb.design.build = originalBuild;
});

const session = (rev: number, over: Parameters<typeof makeSession>[0] = {}) =>
  makeSession({ prototype_dir: DIR, ui: { state: 'active', rev }, ...over });

function frames() {
  return screen.getAllByTitle(/prototype/i) as HTMLIFrameElement[];
}
const visible = () => frames().find((f) => f.dataset.front === 'true')!;
const hidden = () => frames().find((f) => f.dataset.front !== 'true')!;

describe('PrototypeFrame', () => {
  it('shows a listening empty state before the first revision', () => {
    render(<PrototypeFrame session={session(0, { ui: { state: 'active', rev: 0, buffered_s: 12 } })} />);
    expect(screen.getByText(/listening for the first design discussion/i)).toBeInTheDocument();
    expect(screen.getByText(/12s/)).toBeInTheDocument();
    expect(build).not.toHaveBeenCalled();
  });

  it('builds on each new revision and swaps the buffer in on load', async () => {
    const { rerender } = render(<PrototypeFrame session={session(1)} />);
    await waitFor(() => expect(build).toHaveBeenCalledWith(DIR, 1));
    await waitFor(() => expect(hidden().getAttribute('src')).toContain('rev=1'));
    load(hidden());
    expect(visible().getAttribute('src')).toContain('rev=1');

    rerender(<PrototypeFrame session={session(2)} />);
    await waitFor(() => expect(build).toHaveBeenCalledWith(DIR, 2));
    await waitFor(() => expect(hidden().getAttribute('src')).toContain('rev=2'));
    // The old frame stays visible until the new one has loaded.
    expect(visible().getAttribute('src')).toContain('rev=1');
    load(hidden());
    expect(visible().getAttribute('src')).toContain('rev=2');
  });

  it('restores the route and scroll position in the new frame', async () => {
    const { rerender } = render(<PrototypeFrame session={session(1)} />);
    await waitFor(() => expect(hidden().getAttribute('src')).toContain('rev=1'));
    load(hidden());
    const front = visible();
    act(() => {
      window.dispatchEvent(
        new MessageEvent('message', {
          data: { type: 'gb-proto:route', hash: '#/checkout' },
          source: front.contentWindow,
        }),
      );
      window.dispatchEvent(
        new MessageEvent('message', {
          data: { type: 'gb-proto:scroll', y: 420 },
          source: front.contentWindow,
        }),
      );
    });

    rerender(<PrototypeFrame session={session(2)} />);
    await waitFor(() => expect(hidden().getAttribute('src')).toContain('rev=2'));
    expect(hidden().getAttribute('src')).toMatch(/rev=2#\/checkout$/);
    const next = hidden();
    const postMessage = vi.spyOn(next.contentWindow!, 'postMessage');
    load(next);
    expect(postMessage).toHaveBeenCalledWith({ type: 'gb-proto:scroll', y: 420 }, '*');
  });

  it('reports a failed build once and keeps the last good frame', async () => {
    const { rerender } = render(<PrototypeFrame session={session(1)} />);
    await waitFor(() => expect(hidden().getAttribute('src')).toContain('rev=1'));
    load(hidden());

    build.mockResolvedValue({ ok: false, rev: 2, error: 'App.tsx:3 unexpected token' });
    rerender(<PrototypeFrame session={session(2)} />);
    expect(await screen.findByText(/build failed/i)).toBeInTheDocument();
    expect(client.post).toHaveBeenCalledWith('/v1/design/session/build-error', {
      rev: 2,
      message: 'App.tsx:3 unexpected token',
    });
    expect(visible().getAttribute('src')).toContain('rev=1');

    // A re-render with the same rev (e.g. a new snapshot) doesn't report again.
    rerender(<PrototypeFrame session={session(2, { ui: { state: 'active', rev: 2, running: true } })} />);
    await act(async () => {});
    expect(
      vi.mocked(client.post).mock.calls.filter(([p]) => p === '/v1/design/session/build-error'),
    ).toHaveLength(1);
  });

  it('shows an updating chip while a run is in flight', async () => {
    render(<PrototypeFrame session={session(1, { ui: { state: 'active', rev: 1, running: true } })} />);
    expect(screen.getByText(/updating/i)).toBeInTheDocument();
  });

  describe('worktree mode', () => {
    const WT = '/code/web-app-poltergeist-2026-10-10-login';
    const codebase: CodebaseInfo = {
      repo: '/code/web-app',
      name: 'web-app',
      app_dir: `${WT}/apps/web`,
      worktree: WT,
      branch: 'poltergeist/2026-10-10-login',
      base: 'origin/main',
    };
    const originalDevserver = window.gb.design.devserver;
    let ensure: ReturnType<typeof vi.fn<(wt: string, app: string) => Promise<DevServerResult>>>;
    let release: ReturnType<typeof vi.fn<(wt: string) => Promise<{ ok: true }>>>;

    beforeEach(() => {
      ensure = vi.fn(async () => ({ ok: true as const, url: 'http://127.0.0.1:5555/', errors: [] }));
      release = vi.fn(async () => ({ ok: true as const }));
      window.gb.design.devserver = { ensure, release };
    });
    afterEach(() => {
      window.gb.design.devserver = originalDevserver;
    });

    const wtSession = (rev: number) =>
      session(rev, { ui_kind: 'worktree', codebase, artefact_rel: '20-contexts/work/artefacts/x' });

    it('loads the dev server instead of bundling, swapping on load per revision', async () => {
      const { rerender } = render(<PrototypeFrame session={wtSession(1)} />);
      await waitFor(() => expect(ensure).toHaveBeenCalledWith(WT, `${WT}/apps/web`));
      expect(build).not.toHaveBeenCalled();
      await waitFor(() => expect(hidden().getAttribute('src')).toBe('http://127.0.0.1:5555/?gbrev=1'));
      expect(hidden().getAttribute('sandbox')).toBe('allow-scripts allow-same-origin allow-forms');
      load(hidden());
      expect(visible().getAttribute('src')).toBe('http://127.0.0.1:5555/?gbrev=1');

      ensure.mockResolvedValue({ ok: true, url: 'http://127.0.0.1:5555/?mode=demo', errors: [] });
      rerender(<PrototypeFrame session={wtSession(2)} />);
      await waitFor(() =>
        expect(hidden().getAttribute('src')).toBe('http://127.0.0.1:5555/?mode=demo&gbrev=2'),
      );
      expect(visible().getAttribute('src')).toBe('http://127.0.0.1:5555/?gbrev=1');
    });

    it('keeps the route across swaps', async () => {
      const { rerender } = render(<PrototypeFrame session={wtSession(1)} />);
      await waitFor(() => expect(hidden().getAttribute('src')).toContain('gbrev=1'));
      load(hidden());
      act(() => {
        window.dispatchEvent(
          new MessageEvent('message', {
            data: { type: 'gb-proto:route', hash: '#/orders' },
            source: visible().contentWindow,
          }),
        );
      });
      rerender(<PrototypeFrame session={wtSession(2)} />);
      await waitFor(() =>
        expect(hidden().getAttribute('src')).toBe('http://127.0.0.1:5555/?gbrev=2#/orders'),
      );
    });

    it('says the dev server is starting until the first url arrives', async () => {
      let resolve!: (r: DevServerResult) => void;
      ensure.mockReturnValue(new Promise((r) => (resolve = r)));
      render(<PrototypeFrame session={wtSession(1)} />);
      expect(await screen.findByText(/starting dev server/i)).toBeInTheDocument();
      await act(async () => resolve({ ok: true, url: 'http://127.0.0.1:5555/', errors: [] }));
      expect(screen.queryByText(/starting dev server/i)).not.toBeInTheDocument();
    });

    it('reports compile errors once per revision', async () => {
      ensure.mockResolvedValue({ ok: true, url: 'http://127.0.0.1:5555/', errors: ['src/App.tsx: error A', 'error B'] });
      const { rerender } = render(<PrototypeFrame session={wtSession(3)} />);
      await waitFor(() =>
        expect(client.post).toHaveBeenCalledWith('/v1/design/session/build-error', {
          rev: 3,
          message: 'src/App.tsx: error A\nerror B',
        }),
      );
      rerender(<PrototypeFrame session={wtSession(3)} />);
      await act(async () => {});
      expect(
        vi.mocked(client.post).mock.calls.filter(([p]) => p === '/v1/design/session/build-error'),
      ).toHaveLength(1);
    });

    it('shows a failed dev server as a build problem and reports it', async () => {
      ensure.mockResolvedValue({ ok: false, error: 'Dev server did not start within 120s: boom' });
      render(<PrototypeFrame session={wtSession(1)} />);
      expect(await screen.findByText(/build failed/i)).toBeInTheDocument();
      expect(client.post).toHaveBeenCalledWith('/v1/design/session/build-error', {
        rev: 1,
        message: 'Dev server did not start within 120s: boom',
      });
    });

    it('starts nothing while the spoken repo is unconfirmed', async () => {
      render(<PrototypeFrame session={{ ...wtSession(1), codebase_confirmed: false }} />);
      await act(async () => {});
      expect(ensure).not.toHaveBeenCalled();
      expect(build).not.toHaveBeenCalled();
    });

    it('releases the dev server on unmount', async () => {
      const { unmount } = render(<PrototypeFrame session={wtSession(1)} />);
      await waitFor(() => expect(ensure).toHaveBeenCalled());
      unmount();
      expect(release).toHaveBeenCalledWith(WT);
    });

    it('does not report errors from the pop-out', async () => {
      ensure.mockResolvedValue({ ok: false, error: 'boom' });
      render(<PrototypeFrame session={wtSession(1)} reportErrors={false} />);
      expect(await screen.findByText(/build failed/i)).toBeInTheDocument();
      expect(client.post).not.toHaveBeenCalled();
    });
  });
});
