import { create } from 'zustand';
import type { NoteKind } from '../../shared/api-types';
import { useNavigation } from './navigation';

export type VaultTab = 'constellation' | 'graph';
export type GraphDepth = 1 | 2 | 3;
export const GRAPH_HISTORY_LIMIT = 50;

interface GraphViewData {
  tab: VaultTab;
  focus: string | null;
  back: string[];
  depth: GraphDepth;
  wholeVault: boolean;
  hiddenKinds: NoteKind[];
}

interface GraphViewState extends GraphViewData {
  setTab: (tab: VaultTab) => void;
  recenter: (path: string) => void;
  goBack: () => void;
  setDepth: (depth: GraphDepth) => void;
  setWholeVault: (on: boolean) => void;
  toggleKind: (kind: NoteKind) => void;
  showInGraph: (path: string) => void;
  reset: () => void;
}

const initial = (): GraphViewData => ({
  tab: 'constellation',
  focus: null,
  back: [],
  depth: 2,
  wholeVault: false,
  hiddenKinds: [],
});

export const useGraphView = create<GraphViewState>((set, get) => ({
  ...initial(),
  setTab: (tab) => set({ tab }),
  recenter: (path) => {
    const { focus, back, wholeVault } = get();
    if (path === focus) {
      if (wholeVault) set({ wholeVault: false });
      return;
    }
    const nextBack = focus === null ? back : [...back, focus].slice(-GRAPH_HISTORY_LIMIT);
    set({ focus: path, back: nextBack, wholeVault: false });
  },
  goBack: () => {
    const { back } = get();
    const previous = back[back.length - 1];
    if (previous === undefined) return;
    set({ focus: previous, back: back.slice(0, -1), wholeVault: false });
  },
  setDepth: (depth) => set({ depth }),
  setWholeVault: (wholeVault) => set({ wholeVault }),
  toggleKind: (kind) =>
    set((s) => ({
      hiddenKinds: s.hiddenKinds.includes(kind)
        ? s.hiddenKinds.filter((k) => k !== kind)
        : [...s.hiddenKinds, kind],
    })),
  showInGraph: (path) => {
    get().recenter(path);
    set({ tab: 'graph' });
    useNavigation.getState().setActive('vault');
  },
  reset: () => set(initial()),
}));
