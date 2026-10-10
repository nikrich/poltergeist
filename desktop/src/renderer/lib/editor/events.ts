import type { Editor } from '@tiptap/core';

/**
 * Custom editor events. Tiptap's EditorEvents is closed (see slash.ts
 * gb:slash:photo), so these go through a loose emitter cast — this module is
 * the only place that cast lives.
 */
export interface GbEditorEvents {
  'gb:status:edit': { pos: number };
  'gb:diagram:open': { source: string };
  'gb:query:open': { path: string };
}

type GbEventName = keyof GbEditorEvents;

interface LooseEmitter {
  emit(event: string, payload: unknown): unknown;
  on(event: string, fn: (payload: unknown) => void): unknown;
  off(event: string, fn: (payload: unknown) => void): unknown;
}

export function emitGb<K extends GbEventName>(editor: Editor, event: K, payload: GbEditorEvents[K]): void {
  (editor as unknown as LooseEmitter).emit(event, payload);
}

export function onGb<K extends GbEventName>(
  editor: Editor,
  event: K,
  handler: (payload: GbEditorEvents[K]) => void,
): () => void {
  const emitter = editor as unknown as LooseEmitter;
  const fn = (p: unknown): void => handler(p as GbEditorEvents[K]);
  emitter.on(event, fn);
  return () => {
    emitter.off(event, fn);
  };
}
