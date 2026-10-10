import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import * as client from '../lib/api/client';
import { ArtefactsScreen } from '../screens/artefacts';
import { useNoteView } from '../stores/note-view';
import { useToasts } from '../stores/toast';
import { makeArtefact, makeArtefactDetail, sampleBoard } from './fixtures/design';
import type { ArtefactDetail, ArtefactSummary, DevServerResult } from '../../shared/design-types';

vi.mock('../lib/api/client', () => ({
  get: vi.fn(),
  post: vi.fn(),
  patch: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
}));

function localDay(offsetDays: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

const TODAY = localDay(0);
const YESTERDAY = localDay(-1);
const WT = '/code/web-app-poltergeist-2026-10-10-orders';

const prototype = makeArtefact({
  id: '20-contexts/work/prototypes/checkout',
  title: 'Checkout redesign',
  date: TODAY,
});
const worktree = makeArtefact({
  id: '20-contexts/work/artefacts/orders',
  title: 'Orders list',
  kind: 'worktree',
  date: YESTERDAY,
  meeting: 'Orders review',
  ui_rev: 5,
  codebase: {
    repo: '/code/web-app',
    name: 'web-app',
    app_dir: WT,
    worktree: WT,
    branch: 'poltergeist/2026-10-10-orders',
    base: 'origin/main',
    missing: false,
  },
});
const board = makeArtefact({
  id: '20-contexts/personal/prototypes/domain',
  title: 'Domain map',
  kind: 'board',
  board: true,
  date: '2026-09-01',
  context: 'personal',
  meeting: null,
  meeting_path: null,
  ui_rev: 0,
  board_rev: 2,
});

let list: ArtefactSummary[];
let details: Record<string, ArtefactDetail>;
const originalBuild = window.gb.design.build;
const originalDevserver = window.gb.design.devserver;
const originalOpenPath = window.gb.design.openPath;
let ensure: ReturnType<typeof vi.fn<(wt: string, app: string) => Promise<DevServerResult>>>;
let release: ReturnType<typeof vi.fn<(wt: string) => Promise<{ ok: true }>>>;
let openPath: ReturnType<typeof vi.fn<(p: string, how: 'editor' | 'finder') => Promise<{ ok: boolean }>>>;

beforeEach(() => {
  vi.clearAllMocks();
  useToasts.setState({ toasts: [] });
  useNoteView.setState({ path: null });
  list = [prototype, worktree, board];
  details = {
    [prototype.id]: makeArtefactDetail(prototype),
    [worktree.id]: makeArtefactDetail({ ...worktree, revs: [{ rev: 5, at: '', summary: 'filters' }] }),
    [board.id]: makeArtefactDetail({ ...board, revs: [], board_model: sampleBoard }),
  };
  vi.mocked(client.get).mockImplementation(((path: string) => {
    if (path === '/v1/design/artefacts') return Promise.resolve(list);
    const m = path.match(/^\/v1\/design\/artefact\?id=(.*)$/);
    if (m) return Promise.resolve(details[decodeURIComponent(m[1]!)]);
    return Promise.reject(new Error(`unexpected GET ${path}`));
  }) as never);
  vi.mocked(client.post).mockResolvedValue({} as never);
  window.gb.design.build = vi.fn(async (_dir: string, rev: number) => ({
    ok: true as const,
    rev,
    url: `gbproto://prototype/index.html?rev=${rev}`,
  }));
  ensure = vi.fn(async () => ({ ok: true as const, url: 'http://127.0.0.1:5555/', errors: [] }));
  release = vi.fn(async () => ({ ok: true as const }));
  window.gb.design.devserver = { ensure, release };
  openPath = vi.fn(async () => ({ ok: true }));
  window.gb.design.openPath = openPath;
});

afterEach(() => {
  window.gb.design.build = originalBuild;
  window.gb.design.devserver = originalDevserver;
  window.gb.design.openPath = originalOpenPath;
  vi.restoreAllMocks();
});

function renderScreen() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ArtefactsScreen />
    </QueryClientProvider>,
  );
}

const listEl = () => screen.getByRole('list', { name: /artefacts/i });
const row = (title: string) => within(listEl()).getByRole('button', { name: new RegExp(title, 'i') });

async function select(title: string) {
  fireEvent.click(await within(await screen.findByRole('list', { name: /artefacts/i })).findByRole('button', { name: new RegExp(title, 'i') }));
  return screen.findByRole('heading', { name: title });
}

describe('ArtefactsScreen', () => {
  it('shows an empty state with how to make one', async () => {
    list = [];
    renderScreen();
    expect(await screen.findByText(/no artefacts yet/i)).toBeInTheDocument();
    expect(screen.getByText(/let's kick off a frontend prototype/i)).toBeInTheDocument();
  });

  it('groups by day and shows kind, meeting, repo and rev', async () => {
    renderScreen();
    await screen.findByRole('list', { name: /artefacts/i });
    const groups = within(listEl()).getAllByRole('heading').map((h) => h.textContent);
    expect(groups).toEqual(['Today', 'Yesterday', '2026-09-01']);
    expect(row('orders list')).toHaveTextContent('Orders review');
    expect(row('orders list')).toHaveTextContent('web-app · poltergeist/2026-10-10-orders');
    expect(row('orders list')).toHaveTextContent('rev 5');
    expect(row('domain map')).toHaveTextContent('rev 2');
    expect(within(listEl()).queryByText(/worktree missing/i)).not.toBeInTheDocument();
  });

  it('filters by kind and context', async () => {
    renderScreen();
    await screen.findByRole('list', { name: /artefacts/i });
    fireEvent.click(screen.getByRole('button', { name: 'Worktrees' }));
    expect(within(listEl()).queryByText('Checkout redesign')).not.toBeInTheDocument();
    expect(within(listEl()).getByText('Orders list')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'All' }));
    fireEvent.change(screen.getByLabelText('Context'), { target: { value: 'personal' } });
    expect(within(listEl()).getByText('Domain map')).toBeInTheDocument();
    expect(within(listEl()).queryByText('Orders list')).not.toBeInTheDocument();
  });

  it('marks a missing worktree and disables its preview', async () => {
    list = [{ ...worktree, codebase: { ...worktree.codebase!, missing: true } }];
    details[worktree.id] = makeArtefactDetail(list[0]);
    renderScreen();
    expect(await within(await screen.findByRole('list', { name: /artefacts/i })).findByText(/worktree missing/i)).toBeInTheDocument();
    await screen.findByRole('heading', { name: 'Orders list' });
    expect(screen.getByText(/the worktree was removed/i)).toBeInTheDocument();
    expect(ensure).not.toHaveBeenCalled();
  });

  it('opens the meeting note from the detail header', async () => {
    renderScreen();
    await select('Checkout redesign');
    fireEvent.click(screen.getByRole('button', { name: /open meeting note: checkout sync/i }));
    expect(useNoteView.getState().path).toBe(prototype.meeting_path);
  });

  it('previews a scratch prototype through the bundler', async () => {
    renderScreen();
    await select('Checkout redesign');
    await waitFor(() =>
      expect(window.gb.design.build).toHaveBeenCalledWith(`/vault/${prototype.id}`, 3),
    );
    await waitFor(() =>
      expect(screen.getByTitle('Checkout redesign preview')).toHaveAttribute(
        'src',
        'gbproto://prototype/index.html?rev=3',
      ),
    );
  });

  it('starts the dev server for a worktree and releases it when leaving', async () => {
    let resolve!: (r: DevServerResult) => void;
    ensure.mockReturnValue(new Promise((r) => (resolve = r)));
    renderScreen();
    await select('Orders list');
    expect(await screen.findByText(/starting dev server/i)).toBeInTheDocument();
    expect(ensure).toHaveBeenCalledWith(WT, WT);
    await act(async () => resolve({ ok: true, url: 'http://127.0.0.1:5555/', errors: [] }));
    expect(screen.getByTitle('Orders list preview')).toHaveAttribute('src', 'http://127.0.0.1:5555/');

    fireEvent.click(row('checkout redesign'));
    await screen.findByRole('heading', { name: 'Checkout redesign' });
    expect(release).toHaveBeenCalledWith(WT);
  });

  it('shows a dev server failure', async () => {
    ensure.mockResolvedValue({ ok: false, error: 'Dev server exited: boom' });
    renderScreen();
    await select('Orders list');
    expect(await screen.findByText(/dev server exited: boom/i)).toBeInTheDocument();
  });

  it('opens the folder or worktree in the editor and Finder', async () => {
    renderScreen();
    await select('Checkout redesign');
    fireEvent.click(screen.getByRole('button', { name: /open in editor/i }));
    expect(openPath).toHaveBeenCalledWith(`/vault/${prototype.id}`, 'editor');
    await select('Orders list');
    fireEvent.click(screen.getByRole('button', { name: /reveal in finder/i }));
    expect(openPath).toHaveBeenCalledWith(WT, 'finder');
  });

  it('ejects a scratch prototype', async () => {
    vi.mocked(client.post).mockResolvedValue({ path: '/code/checkout-redesign' } as never);
    renderScreen();
    await select('Checkout redesign');
    fireEvent.click(screen.getByRole('button', { name: /eject/i }));
    await waitFor(() =>
      expect(client.post).toHaveBeenCalledWith('/v1/design/artefacts/eject', { id: prototype.id }),
    );
    await waitFor(() =>
      expect(useToasts.getState().toasts.some((t) => t.message.includes('/code/checkout-redesign'))).toBe(true),
    );
  });

  it('removes a worktree after confirming and says when the branch was kept', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    vi.mocked(client.post).mockResolvedValue({
      removed: true,
      branch_kept: true,
      reason: 'unmerged commits on poltergeist/2026-10-10-orders',
    } as never);
    renderScreen();
    await select('Orders list');
    expect(screen.queryByRole('button', { name: /eject/i })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /remove worktree/i }));
    expect(confirm).toHaveBeenCalled();
    expect(client.post).not.toHaveBeenCalled();

    confirm.mockReturnValue(true);
    fireEvent.click(screen.getByRole('button', { name: /remove worktree/i }));
    await waitFor(() =>
      expect(client.post).toHaveBeenCalledWith('/v1/design/artefacts/remove-worktree', {
        id: worktree.id,
      }),
    );
    await waitFor(() =>
      expect(
        useToasts.getState().toasts.some((t) => /kept branch poltergeist\/2026-10-10-orders/i.test(t.message)),
      ).toBe(true),
    );
  });

  it('shows the board and the revisions newest first', async () => {
    renderScreen();
    await select('Domain map');
    expect(screen.getByRole('tab', { name: 'Board' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByRole('tab', { name: 'Preview' })).not.toBeInTheDocument();
    expect(screen.getByText('Order placed')).toBeInTheDocument();

    await select('Checkout redesign');
    fireEvent.click(screen.getByRole('tab', { name: 'Revisions' }));
    const revs = screen.getAllByTestId('artefact-rev').map((el) => el.textContent);
    expect(revs[0]).toMatch(/rev 3.*payment step/);
    expect(revs[2]).toMatch(/rev 1.*first screen/);
  });
});
