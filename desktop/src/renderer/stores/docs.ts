import { create } from 'zustand';
import type { FolderRef } from '../../shared/api-types';

export type DocSelection =
  | { type: 'folder'; ref: FolderRef }
  | { type: 'doc'; docId: string }
  | { type: 'attention' }
  | null;

export interface UploadGhost {
  id: string;
  name: string;
  size: number;
  key: string;
  status: 'uploading' | 'error';
  error?: string;
}

type ViewMode = 'list' | 'grid';
const VIEW_KEY = 'gb.docs.viewModes';

function loadViewModes(): Record<string, ViewMode> {
  try {
    return JSON.parse(localStorage.getItem(VIEW_KEY) ?? '{}') as Record<string, ViewMode>;
  } catch {
    return {};
  }
}

interface DocsState {
  selection: DocSelection;
  select: (s: DocSelection) => void;
  viewModes: Record<string, ViewMode>;
  viewMode: (key: string) => ViewMode;
  setViewMode: (key: string, mode: ViewMode) => void;
  uploads: UploadGhost[];
  addUpload: (g: Omit<UploadGhost, 'status'>) => void;
  failUpload: (id: string, error: string) => void;
  removeUpload: (id: string) => void;
  quickOpen: boolean;
  setQuickOpen: (b: boolean) => void;
}

export const useDocs = create<DocsState>((set, get) => ({
  selection: null,
  select: (selection) => set({ selection }),
  viewModes: loadViewModes(),
  viewMode: (key) => get().viewModes[key] ?? 'list',
  setViewMode: (key, mode) => {
    const viewModes = { ...get().viewModes, [key]: mode };
    set({ viewModes });
    try {
      localStorage.setItem(VIEW_KEY, JSON.stringify(viewModes));
    } catch {
      // per-viewer convenience only
    }
  },
  uploads: [],
  addUpload: (g) => set({ uploads: [...get().uploads, { ...g, status: 'uploading' }] }),
  failUpload: (id, error) =>
    set({ uploads: get().uploads.map((u) => (u.id === id ? { ...u, status: 'error', error } : u)) }),
  removeUpload: (id) => set({ uploads: get().uploads.filter((u) => u.id !== id) }),
  quickOpen: false,
  setQuickOpen: (quickOpen) => set({ quickOpen }),
}));
