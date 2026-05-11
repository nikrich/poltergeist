import { create } from 'zustand';

export type ScreenId =
  | 'today'
  | 'connectors'
  | 'meetings'
  | 'capture'
  | 'vault'
  | 'daily'
  | 'settings';

interface NavState {
  active: ScreenId;
  setActive: (id: ScreenId) => void;
}

export const useNavigation = create<NavState>((set) => ({
  active: 'today',
  setActive: (id) => set({ active: id }),
}));
