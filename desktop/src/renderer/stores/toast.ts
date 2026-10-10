import { create } from 'zustand';

export type ToastKind = 'info' | 'success' | 'error';

export interface ToastAction {
  label: string;
  onClick: () => void;
}

export interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
  action?: ToastAction;
}

interface ToastState {
  toasts: Toast[];
  push: (kind: ToastKind, message: string, action?: ToastAction) => void;
  dismiss: (id: number) => void;
}

let nextId = 1;

const DURATIONS: Record<ToastKind, number> = {
  info: 3500,
  success: 3500,
  error: 6000,
};
/** Long enough to reach for the button. */
const ACTION_DURATION = 8000;

export const useToasts = create<ToastState>((set, get) => ({
  toasts: [],
  push: (kind, message, action) => {
    const id = nextId++;
    set({ toasts: [...get().toasts, { id, kind, message, ...(action ? { action } : {}) }] });
    setTimeout(() => get().dismiss(id), action ? ACTION_DURATION : DURATIONS[kind]);
  },
  dismiss: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
}));

export const toast = {
  info: (m: string, action?: ToastAction) => useToasts.getState().push('info', m, action),
  success: (m: string) => useToasts.getState().push('success', m),
  error: (m: string) => useToasts.getState().push('error', m),
};

// Backwards-compat helper used by stub buttons; will go away as Slices 2-4 wire real handlers.
export const stub = (slice: number) => toast.info(`wired in Slice ${slice}`);
