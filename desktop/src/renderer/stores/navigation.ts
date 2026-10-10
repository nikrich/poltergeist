import { create } from 'zustand';

export type ScreenId =
  | 'today'
  | 'activity'
  | 'chat'
  | 'connectors'
  | 'meetings'
  | 'capture'
  | 'vault'
  | 'daily'
  | 'settings'
  | 'jots'
  | 'docs'
  | 'plugins'
  | 'onboarding'
  | `plugin:${string}`;

/** Which navigation would unmount the guarded editor: a screen change, or
 * NoteView switching to another note. */
export type NavigationScope = 'screen' | 'note';

/** Returns true when it is fine to navigate (false cancels the navigation). */
export type NavigationGuard = () => boolean;

const guards: Record<NavigationScope, Set<NavigationGuard>> = {
  screen: new Set(),
  note: new Set(),
};

/** Ask `guard` before every navigation in `scope`. Returns the unregister fn. */
export function registerNavigationGuard(
  scope: NavigationScope,
  guard: NavigationGuard,
): () => void {
  guards[scope].add(guard);
  return () => {
    guards[scope].delete(guard);
  };
}

/** The single check every screen change / note open goes through. */
export function navigationAllowed(scope: NavigationScope): boolean {
  return [...guards[scope]].every((guard) => guard());
}

interface NavState {
  active: ScreenId;
  setActive: (id: ScreenId) => void;
}

export const useNavigation = create<NavState>((set, get) => ({
  active: 'today',
  setActive: (id) => {
    if (id !== get().active && !navigationAllowed('screen')) return;
    set({ active: id });
  },
}));
