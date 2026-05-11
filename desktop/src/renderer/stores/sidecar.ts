import { create } from 'zustand';

type Status = 'connecting' | 'ready' | 'failed';

interface SidecarState {
  status: Status;
  failure: string | null;
  setReady: () => void;
  setFailed: (reason: string) => void;
  retry: () => Promise<void>;
}

export const useSidecar = create<SidecarState>((set) => ({
  status: 'connecting',
  failure: null,
  setReady: () => set({ status: 'ready', failure: null }),
  setFailed: (reason) => set({ status: 'failed', failure: reason }),
  retry: async () => {
    set({ status: 'connecting', failure: null });
    const result = await window.gb.sidecar.retry();
    if (!result.ok) {
      set({ status: 'failed', failure: result.error });
    }
    // 'ready' will come via the bridge 'sidecar:ready' event subscription in App.
  },
}));
