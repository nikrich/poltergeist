import { create } from 'zustand';

type Tab = 'backlog' | 'graph';

interface OntologyViewState {
  project: string | null;
  tab: Tab;
  focus: string | null;
  selected: string | null;
  depth: 1 | 2 | 3;
  setProject: (project: string | null) => void;
  setTab: (tab: Tab) => void;
  setFocus: (focus: string | null) => void;
  setSelected: (selected: string | null) => void;
  setDepth: (depth: 1 | 2 | 3) => void;
  reset: () => void;
}

const initial = { project: null, tab: 'backlog' as Tab, focus: null, selected: null, depth: 2 as const };

export const useOntologyView = create<OntologyViewState>((set) => ({
  ...initial,
  setProject: (project) => set({ project, focus: null, selected: null }),
  setTab: (tab) => set({ tab }),
  setFocus: (focus) => set({ focus }),
  setSelected: (selected) => set({ selected }),
  setDepth: (depth) => set({ depth }),
  reset: () => set(initial),
}));
