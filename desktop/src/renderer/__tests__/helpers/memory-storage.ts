import { vi } from 'vitest';

/** Node 25 ships a bare global localStorage that shadows jsdom's; tests use
 * this in-memory stub instead. Undo with vi.unstubAllGlobals(). */
export function stubLocalStorage(): Map<string, string> {
  const mem = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => mem.get(k) ?? null,
    setItem: (k: string, v: string) => void mem.set(k, v),
    removeItem: (k: string) => void mem.delete(k),
    clear: () => mem.clear(),
  });
  return mem;
}

/** A localStorage that throws on every call (private mode, blocked site data). */
export function stubBrokenLocalStorage(): void {
  const fail = () => {
    throw new Error('storage blocked');
  };
  vi.stubGlobal('localStorage', { getItem: fail, setItem: fail, removeItem: fail, clear: fail });
}
