import { create } from 'zustand';
import { navigationAllowed } from './navigation';

interface NoteViewState {
  path: string | null;
  open: (path: string) => void;
  close: () => void;
}

export const useNoteView = create<NoteViewState>((set, get) => ({
  path: null,
  open: (path) => {
    // Every "open a note" entry point lands here, so a pending conflict in
    // the open note is guarded no matter where the click came from.
    if (path !== get().path && !navigationAllowed('note')) return;
    set({ path });
  },
  close: () => set({ path: null }),
}));
