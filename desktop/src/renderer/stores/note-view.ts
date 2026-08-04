import { create } from 'zustand';

interface NoteViewState {
  path: string | null;
  open: (path: string) => void;
  close: () => void;
}

export const useNoteView = create<NoteViewState>((set) => ({
  path: null,
  open: (path) => set({ path }),
  close: () => set({ path: null }),
}));
