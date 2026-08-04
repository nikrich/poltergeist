import { create } from 'zustand';
import type { DocsAssistMode } from '../../shared/api-types';

export type AssistTarget = 'selection' | 'doc';
export type AssistPhase = 'idle' | 'streaming' | 'proposal' | 'error';

interface DocsAssistState {
  open: boolean;
  phase: AssistPhase;
  jotId: string | null;
  target: AssistTarget;
  mode: DocsAssistMode;
  /** Original selection text the proposal replaces (for preview). */
  selection: string;
  streamed: string;
  error: string | null;
  toggleOpen: () => void;
  start: (p: {
    jotId: string;
    mode: DocsAssistMode;
    target: AssistTarget;
    selection: string;
  }) => void;
  appendDelta: (text: string) => void;
  finish: (fullText: string) => void;
  fail: (message: string) => void;
  reset: () => void;
}

export const useDocsAssist = create<DocsAssistState>((set) => ({
  open: false,
  phase: 'idle',
  jotId: null,
  target: 'doc',
  mode: 'polish',
  selection: '',
  streamed: '',
  error: null,
  toggleOpen: () => set((s) => ({ open: !s.open })),
  start: ({ jotId, mode, target, selection }) =>
    set({ phase: 'streaming', jotId, mode, target, selection, streamed: '', error: null }),
  appendDelta: (text) => set((s) => ({ streamed: s.streamed + text })),
  // When fullText is empty the sidecar sent a done event without a final text
  // payload — keep the accumulated deltas so the proposal view has content.
  finish: (fullText) => set((s) => ({ phase: 'proposal', streamed: fullText || s.streamed })),
  fail: (message) => set({ phase: 'error', error: message }),
  reset: () => set({ phase: 'idle', streamed: '', error: null, selection: '' }),
}));
