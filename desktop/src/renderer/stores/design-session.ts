import { useEffect } from 'react';
import { create } from 'zustand';
import { get, post } from '../lib/api/client';
import { toast } from './toast';
import type {
  DesignCanvas,
  DesignLiveEvent,
  DesignSessionSnapshot,
} from '../../shared/design-types';

/** Every session POST answers with the command it caused and the updated
 *  snapshot; applying it right away makes buttons feel instant (the stream
 *  sends the same snapshot shortly after). */
interface SessionReply {
  event: DesignLiveEvent | null;
  session: DesignSessionSnapshot;
}

function command(path: string, body?: unknown): Promise<SessionReply> {
  return post<SessionReply>(`/v1/design/session/${path}`, body).then((reply) => {
    if (reply?.session) useDesignSession.getState().apply({ type: 'snapshot', session: reply.session });
    return reply;
  });
}

/** REST calls on the current session (`/v1/design/session/*`). */
export const designSession = {
  start: (canvas: DesignCanvas) => command('start', { canvas }),
  pause: (canvas: DesignCanvas | 'both') => command('pause', { canvas }),
  resume: (canvas: DesignCanvas | 'both') => command('resume', { canvas }),
  nudge: (text: string, canvas?: DesignCanvas) => command('nudge', { canvas, text }),
  update: (canvas?: DesignCanvas) => command('update', { canvas }),
  undo: (token: string) => command('undo', { token }),
  config: (body: { project_id?: string | null; pack_id?: string }) => command('config', body),
  buildError: (rev: number, message: string) => command('build-error', { rev, message }),
  revert: (canvas: DesignCanvas, rev: number) => command('revert', { canvas, rev }),
  eject: () => post<{ path: string }>('/v1/design/session/eject'),
  /** Build the UI on a repo (absolute path of its main checkout), or null for
   *  a scratch prototype. Only before the first UI revision. */
  codebase: (path: string | null) => command('codebase', { path }),
};

interface DesignSessionStore {
  /** null when no recording has a design session. */
  session: DesignSessionSnapshot | null;
  /** The sidecar reported no recording in progress. */
  idle: boolean;
  ended: boolean;
  lastRevision: { canvas: DesignCanvas; rev: number; summary: string } | null;
  /** The panel's codebase picker is open (also opened from a toast). */
  pickerOpen: boolean;
  setPickerOpen: (open: boolean) => void;
  apply: (event: DesignLiveEvent) => void;
  reset: () => void;
}

const initial = { session: null, idle: false, ended: false, lastRevision: null, pickerOpen: false };

const NOT_FOUND_PREFIX = "Couldn't find";
const CONFIRM_PREFIX = 'Use ';

/** Accept the repo the session is waiting on (picked by voice). */
export function confirmCodebase(): void {
  const repo = useDesignSession.getState().session?.codebase?.repo;
  if (!repo) return;
  designSession.codebase(repo).catch((e: unknown) => {
    toast.error(`Codebase change failed: ${errorMessage(e)}`);
  });
}

function errorMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export const useDesignSession = create<DesignSessionStore>((set) => ({
  ...initial,
  setPickerOpen: (open) => set({ pickerOpen: open }),
  apply: (event) => {
    switch (event.type) {
      case 'snapshot':
        set({ session: event.session, idle: false });
        return;
      case 'command': {
        // Buttons already show their effect; only spoken commands need the
        // "here's what I heard" toast with a way back.
        if (!event.spoken) return;
        // A spoken codebase that matched no repo: let the user pick one.
        if (event.command === 'codebase' && event.label.startsWith(NOT_FOUND_PREFIX)) {
          toast.info(event.label, { label: 'Choose repo', onClick: () => set({ pickerOpen: true }) });
          return;
        }
        // A spoken repo runs nothing until confirmed.
        if (event.command === 'codebase' && event.label.startsWith(CONFIRM_PREFIX)) {
          toast.info(event.label, { label: 'Confirm', onClick: confirmCodebase });
          return;
        }
        const token = event.undo_token;
        toast.info(
          event.label,
          token
            ? {
                label: 'Undo',
                onClick: () => {
                  designSession.undo(token).catch((e: unknown) => {
                    toast.error(`Undo failed: ${errorMessage(e)}`);
                  });
                },
              }
            : undefined,
        );
        return;
      }
      case 'revision':
        set({ lastRevision: { canvas: event.canvas, rev: event.rev, summary: event.summary } });
        return;
      case 'error':
        toast.error(`Live design: ${event.message}`);
        return;
      case 'idle':
        set({ session: null, idle: true });
        return;
      case 'end':
        set({ ended: true });
        return;
    }
  },
  reset: () => set(initial),
}));

/** Some canvas has started — the panel is worth a full column. */
export function isDesignOpen(session: DesignSessionSnapshot | null): boolean {
  return (
    session !== null &&
    (session.canvases.ui.state !== 'off' || session.canvases.board.state !== 'off')
  );
}

const RESUBSCRIBE_DELAY_MS = 2000;
const MAX_RESUBSCRIBES = 3;

/** Follow the sidecar's live design session while `active`. Mirrors
 *  useLiveTranscriptStream: fresh on each activation, re-subscribes when the
 *  stream drops without `end`. */
export function useDesignSessionStream(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    const store = useDesignSession.getState();
    store.reset();
    const off = window.gb.on('design:live:event', (event) => store.apply(event));

    let cancelled = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;

    // The stream sends a snapshot on connect; this covers a slow first event.
    get<DesignSessionSnapshot>('/v1/design/session')
      .then((session) => {
        if (!cancelled && useDesignSession.getState().session === null) {
          store.apply({ type: 'snapshot', session });
        }
      })
      .catch(() => {
        /* 404 = no session yet; the stream reports when one starts */
      });

    const subscribe = () => {
      attempts += 1;
      void window.gb.design.liveSubscribe().then((res) => {
        if (cancelled || !res.ok) return;
        if (!useDesignSession.getState().ended && attempts <= MAX_RESUBSCRIBES) {
          timer = setTimeout(subscribe, RESUBSCRIBE_DELAY_MS);
        }
      });
    };
    subscribe();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      off();
      void window.gb.design.liveUnsubscribe();
    };
  }, [active]);
}
