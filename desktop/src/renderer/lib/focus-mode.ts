import { useEffect } from 'react';
import { create } from 'zustand';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import { matchesShortcut } from './editor-shortcuts';
import { isMac } from './platform';

/** Number of mounted views that show an editable page (the jots editor, the
 * note viewer). Focus mode only takes effect while at least one is up, so a
 * persisted `focusMode: true` never hides the sidebar on Today or Settings. */
interface FocusSurfaceState {
  count: number;
  register: () => () => void;
}

export const useFocusSurfaces = create<FocusSurfaceState>((set) => ({
  count: 0,
  register: () => {
    set((s) => ({ count: s.count + 1 }));
    let released = false;
    return () => {
      if (released) return;
      released = true;
      set((s) => ({ count: Math.max(0, s.count - 1) }));
    };
  },
}));

/** Register the calling view as an editor surface while `enabled`. */
export function useFocusSurface(enabled: boolean): void {
  useEffect(() => {
    if (!enabled) return;
    return useFocusSurfaces.getState().register();
  }, [enabled]);
}

export function useFocusActive(): boolean {
  const on = useSettings((s) => s.focusMode);
  const surfaces = useFocusSurfaces((s) => s.count);
  return on && surfaces > 0;
}

/** Non-hook read for event handlers. */
export function focusActiveNow(): boolean {
  return useSettings.getState().focusMode && useFocusSurfaces.getState().count > 0;
}

export async function setFocusMode(on: boolean): Promise<void> {
  const r = await useSettings.getState().set('focusMode', on);
  if (!r.ok) toast.error(r.error);
}

/** App-level keyboard handling: ⌘. / Ctrl+. toggles (only with an editor on
 * screen); Esc leaves focus mode unless something (a ProseMirror menu)
 * already consumed it. Marks the Esc as handled so the note viewer, which
 * also listens for Esc, does not close in the same keystroke. */
export function useFocusModeShortcuts(): void {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (matchesShortcut(e, 'focus', isMac)) {
        if (useFocusSurfaces.getState().count === 0) return;
        e.preventDefault();
        void setFocusMode(!useSettings.getState().focusMode);
        return;
      }
      if (e.key === 'Escape' && !e.defaultPrevented && focusActiveNow()) {
        e.preventDefault();
        void setFocusMode(false);
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);
}
