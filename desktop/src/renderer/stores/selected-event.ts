import { create } from 'zustand';

interface SelectedEventState {
  selectedEventId: string | null;
  setSelectedEventId: (id: string | null) => void;
}

export const useSelectedEvent = create<SelectedEventState>((set) => ({
  selectedEventId: null,
  setSelectedEventId: (selectedEventId) => set({ selectedEventId }),
}));
