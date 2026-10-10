import { useSyncExternalStore } from 'react';

// Mock data for the prototype. Add typed collections to MockData and seed
// them in initialData. State persists to sessionStorage so it survives the
// host swapping in a new bundle; changing initialData resets it.

// eslint-disable-next-line @typescript-eslint/no-empty-interface
export interface MockData {}

export const initialData: MockData = {};

const KEY = 'prototype-store';
const SEED = JSON.stringify(initialData);

function load(): MockData {
  try {
    const raw = sessionStorage.getItem(KEY);
    if (raw) {
      const saved = JSON.parse(raw) as { seed: string; state: MockData };
      if (saved.seed === SEED) return saved.state;
    }
  } catch {
    // storage unavailable or corrupt: start from the seed
  }
  return initialData;
}

let state: MockData = load();
const listeners = new Set<() => void>();

function persist(): void {
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ seed: SEED, state }));
  } catch {
    // storage unavailable: keep in memory only
  }
}

export function getStore(): MockData {
  return state;
}

export function setStore(update: Partial<MockData> | ((prev: MockData) => MockData)): void {
  state =
    typeof update === 'function'
      ? (update as (prev: MockData) => MockData)(state)
      : { ...state, ...update };
  persist();
  listeners.forEach((listener) => listener());
}

export function resetStore(): void {
  setStore(() => initialData);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useStore(): [MockData, typeof setStore] {
  const snapshot = useSyncExternalStore(subscribe, getStore, getStore);
  return [snapshot, setStore];
}
