import { afterEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import * as client from '../lib/api/client';
import { HistoryDrawer, actorLabel } from '../components/HistoryDrawer';
import { NoteHistoryButton } from '../components/NoteHistory';
import type { GuardHandle } from '../components/GuardedNoteEditor';
import { RESTORE_BLOCKED } from '../lib/use-guarded-save';
import { useToasts } from '../stores/toast';
import type {
  HistoryBlobResponse,
  NoteHistoryResponse,
  RestoreHistoryResponse,
} from '../../shared/api-types';

vi.mock('../lib/api/client', async () => {
  const actual = await vi.importActual<typeof import('../lib/api/client')>('../lib/api/client');
  return { ApiError: actual.ApiError, get: vi.fn(), post: vi.fn(), patch: vi.fn(), del: vi.fn(), put: vi.fn() };
});
const getMock = vi.mocked(client.get);
const postMock = vi.mocked(client.post);

const PATH = '20-contexts/work/notes/plan.md';
const B1 = 'a'.repeat(64);
const B2 = 'b'.repeat(64);
const HISTORY: NoteHistoryResponse = {
  path: PATH,
  items: [
    { ts: '2026-10-09T10:05:00+00:00', path: PATH, blob: B2, actor: 'assistant', reason: 'polished intro', size: 40 },
    { ts: '2026-10-09T10:00:00+00:00', path: PATH, blob: B1, actor: 'user', reason: 'edited in the editor', size: 30 },
  ],
};
const VERSIONS: Record<string, HistoryBlobResponse> = {
  [B2]: { path: PATH, blob: B2, content: 'keep\nold intro', current: 'keep\nnew intro' },
  [B1]: { path: PATH, blob: B1, content: 'keep\nnew intro', current: 'keep\nnew intro' },
};

function routeGets(history: NoteHistoryResponse = HISTORY) {
  getMock.mockImplementation((async (url: string) => {
    if (url.startsWith('/v1/notes/history/blob')) {
      const blob = new URLSearchParams(url.split('?')[1]).get('blob')!;
      return VERSIONS[blob];
    }
    if (url.startsWith('/v1/notes/history')) return history;
    throw new Error(`unexpected GET ${url}`);
  }) as unknown as typeof client.get);
}

function withQuery(children: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

afterEach(() => {
  getMock.mockReset();
  postMock.mockReset();
  useToasts.setState({ toasts: [] });
});

describe('actorLabel', () => {
  it('labels every actor kind', () => {
    expect(actorLabel('user')).toBe('you');
    expect(actorLabel('assistant')).toBe('✦ assistant');
    expect(actorLabel('mcp')).toBe('⌁ mcp');
    expect(actorLabel('restore')).toBe('↺ restore');
    expect(actorLabel('plugin:familiar')).toBe('⧉ familiar');
    expect(actorLabel('worker:reversal')).toBe('⚙ reversal');
  });
});

describe('HistoryDrawer', () => {
  it('lists versions with actor badges and diffs the newest against current', async () => {
    routeGets();
    render(withQuery(<HistoryDrawer path={PATH} onClose={() => {}} onRestore={vi.fn()} />));
    expect(await screen.findByText('polished intro')).toBeInTheDocument();
    expect(screen.getAllByTestId('actor-badge').map((b) => b.textContent)).toEqual(['✦ assistant', 'you']);
    const diff = await screen.findByTestId('history-diff');
    expect(diff).toHaveTextContent('- old intro');
    expect(diff).toHaveTextContent('+ new intro');
  });

  it('loads another version when it is picked', async () => {
    routeGets();
    render(withQuery(<HistoryDrawer path={PATH} onClose={() => {}} onRestore={vi.fn()} />));
    fireEvent.click(await screen.findByText('edited in the editor'));
    await waitFor(() =>
      expect(getMock).toHaveBeenCalledWith(
        `/v1/notes/history/blob?path=${encodeURIComponent(PATH)}&blob=${B1}`,
      ),
    );
    expect(await screen.findByText('same as the current version')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'restore this version' })).toBeDisabled();
  });

  it('restores the selected version and closes', async () => {
    routeGets();
    const onRestore = vi.fn().mockResolvedValue(undefined);
    const onClose = vi.fn();
    render(withQuery(<HistoryDrawer path={PATH} onClose={onClose} onRestore={onRestore} />));
    await screen.findByTestId('history-diff');
    fireEvent.click(screen.getByRole('button', { name: 'restore this version' }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(onRestore).toHaveBeenCalledWith(HISTORY.items[0]);
  });

  it('keeps the drawer open and explains a refused restore', async () => {
    routeGets();
    const onRestore = vi.fn().mockRejectedValue(new Error(RESTORE_BLOCKED));
    const onClose = vi.fn();
    render(withQuery(<HistoryDrawer path={PATH} onClose={onClose} onRestore={onRestore} />));
    await screen.findByTestId('history-diff');
    fireEvent.click(screen.getByRole('button', { name: 'restore this version' }));
    await waitFor(() =>
      expect(useToasts.getState().toasts.map((t) => t.message)).toEqual([
        `restore failed: ${RESTORE_BLOCKED}`,
      ]),
    );
    expect(onClose).not.toHaveBeenCalled();
  });

  it('shows an empty state before the first edit', async () => {
    routeGets({ path: PATH, items: [] });
    render(withQuery(<HistoryDrawer path={PATH} onClose={() => {}} onRestore={vi.fn()} />));
    expect(await screen.findByText(/no earlier versions yet/)).toBeInTheDocument();
  });
});

describe('NoteHistoryButton', () => {
  it('restores through the editor guard', async () => {
    routeGets();
    const restored: RestoreHistoryResponse = {
      path: PATH, etag: 'ffffffffffffffff', body: 'old intro', restored: B2, historyOk: true,
    };
    postMock.mockResolvedValue(restored);
    const restore = vi.fn(async (perform: () => Promise<unknown>) => {
      await perform();
    });
    const guardRef = {
      current: { adopt: vi.fn(), hasConflict: () => false, restore },
    } as unknown as React.MutableRefObject<GuardHandle | null>;
    render(withQuery(<NoteHistoryButton path={PATH} guardRef={guardRef} />));
    fireEvent.click(screen.getByRole('button', { name: 'history' }));
    await screen.findByTestId('history-diff');
    fireEvent.click(screen.getByRole('button', { name: 'restore this version' }));
    await waitFor(() =>
      expect(postMock).toHaveBeenCalledWith('/v1/notes/history/restore', { path: PATH, blob: B2 }),
    );
    expect(restore).toHaveBeenCalledTimes(1);
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'page history' })).toBeNull());
  });
});
