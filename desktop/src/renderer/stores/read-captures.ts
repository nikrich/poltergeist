/**
 * Tracks which capture IDs the user has marked as read.
 *
 * The backend's ``unread`` flag is a *recency* heuristic ("captured within
 * the last 6 hours"), not actual read state. Adding persistent read-state
 * to the API would mean another endpoint, a state file, and a sync story.
 * For a single-user local app, localStorage is enough — read-state is a
 * UI affordance, not source-of-truth data.
 *
 * Storage: a JSON array of capture IDs under `gb:read-captures`. We trim
 * to MAX_TRACKED to bound localStorage size — once an ID rolls out of the
 * tracked window the backend's recency flag has long since dropped it
 * back to "read" anyway.
 */
import { create } from 'zustand';

const STORAGE_KEY = 'gb:read-captures';
const MAX_TRACKED = 2000;

function loadInitial(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((s): s is string => typeof s === 'string'));
  } catch {
    return new Set();
  }
}

function persist(set: Set<string>): void {
  // Convert + trim oldest entries by insertion order so the file stays bounded.
  let arr = Array.from(set);
  if (arr.length > MAX_TRACKED) arr = arr.slice(arr.length - MAX_TRACKED);
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(arr));
  } catch {
    // Quota/private-mode failures — read-state is ephemeral anyway.
  }
}

interface ReadCapturesState {
  read: Set<string>;
  isRead: (id: string) => boolean;
  markRead: (ids: string[]) => void;
  clear: () => void;
}

export const useReadCaptures = create<ReadCapturesState>((set, get) => {
  const initial = loadInitial();
  return {
    read: initial,
    isRead: (id) => get().read.has(id),
    markRead: (ids) => {
      if (ids.length === 0) return;
      const next = new Set(get().read);
      for (const id of ids) next.add(id);
      persist(next);
      set({ read: next });
    },
    clear: () => {
      persist(new Set());
      set({ read: new Set() });
    },
  };
});

/**
 * Hook helper: how many captures in `items` are unread AND not marked-read.
 *
 * Use this anywhere you'd otherwise duplicate the
 * `c.unread && !readSet.has(c.id)` filter — the sidebar badge and the
 * capture screen's top bar should never drift.
 */
export function unreadCount(
  items: ReadonlyArray<{ id: string; unread: boolean }>,
  readSet: ReadonlySet<string>,
): number {
  let n = 0;
  for (const c of items) {
    if (c.unread && !readSet.has(c.id)) n += 1;
  }
  return n;
}
