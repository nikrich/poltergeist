import { useEffect } from 'react';
import { create } from 'zustand';
import type {
  LiveTranscriptEvent,
  LiveTranscriptSegment,
  LiveTranscriptState,
} from '../../shared/api-types';

interface LiveTranscriptStore {
  segments: LiveTranscriptSegment[];
  /** null until the sidecar reports a status (no session = live is off). */
  state: LiveTranscriptState | null;
  reason: string | null;
  lagS: number;
  ended: boolean;
  apply: (event: LiveTranscriptEvent) => void;
  reset: () => void;
}

const initial = { segments: [], state: null, reason: null, lagS: 0, ended: false };

export const useLiveTranscript = create<LiveTranscriptStore>((set) => ({
  ...initial,
  apply: (event) =>
    set((s) => {
      switch (event.type) {
        case 'segment': {
          // A re-subscribe replays everything already on disk; keep seq order.
          const last = s.segments[s.segments.length - 1];
          if (last && event.seq <= last.seq) return s;
          return { segments: [...s.segments, event] };
        }
        case 'status':
          return { state: event.state, reason: event.reason, lagS: event.lag_s };
        case 'end':
          return { ended: true };
        default:
          return s;
      }
    }),
  reset: () => set(initial),
}));

const RESUBSCRIBE_DELAY_MS = 2000;
const MAX_RESUBSCRIBES = 3;

/** Follow the sidecar's live transcript while `active` (recording or
 *  finalising). Starts fresh on each activation. */
export function useLiveTranscriptStream(active: boolean): void {
  useEffect(() => {
    if (!active) return;
    const store = useLiveTranscript.getState();
    store.reset();
    const off = window.gb.on('recorder:live:event', (event) => store.apply(event));

    let cancelled = false;
    let attempts = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const subscribe = () => {
      attempts += 1;
      void window.gb.recorder.liveSubscribe().then((res) => {
        if (cancelled) return;
        if (!res.ok) {
          store.apply({ type: 'status', state: 'unavailable', reason: res.error, lag_s: 0 });
          return;
        }
        // The stream closed without `end` (sidecar restart, dropped
        // connection): pick it up again; the replay fills any gap.
        if (!useLiveTranscript.getState().ended && attempts <= MAX_RESUBSCRIBES) {
          timer = setTimeout(subscribe, RESUBSCRIBE_DELAY_MS);
        }
      });
    };
    subscribe();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      off();
      void window.gb.recorder.liveUnsubscribe();
    };
  }, [active]);
}
