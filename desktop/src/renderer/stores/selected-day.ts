import { create } from 'zustand';

interface SelectedDayState {
  /** ISO date (YYYY-MM-DD) preselected for the activity screen; null = today. */
  selectedDate: string | null;
  setSelectedDate: (date: string | null) => void;
}

export const useSelectedDay = create<SelectedDayState>((set) => ({
  selectedDate: null,
  setSelectedDate: (selectedDate) => set({ selectedDate }),
}));
