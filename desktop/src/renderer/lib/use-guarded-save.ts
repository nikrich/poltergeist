import { useCallback, useRef, useState } from 'react';
import { ApiError } from './api/client';

export interface SaveTarget {
  /** Persist `body`; `ifMatch` is the etag the save is based on (null = unconditional). */
  send: (body: string, ifMatch: string | null) => Promise<{ etag?: string | null }>;
  /** Re-read the note as it is on disk now. */
  fetchLatest: () => Promise<{ body: string; etag?: string | null }>;
}

export interface Conflict {
  /** The user's latest text — keeps updating while autosave is paused. */
  mine: string;
  theirs: string;
  theirsEtag: string | null;
  /** theirs could not be re-read; keep theirs / view changes unavailable. */
  unread?: boolean;
}

export interface GuardedSave {
  save: (body: string) => void;
  conflict: Conflict | null;
  resolving: boolean;
  keepMine: () => Promise<void>;
  keepTheirs: () => Conflict | null;
  adopt: (etag: string | null, body: string) => void;
}

/** GET bodies come back trimmed (both ends) by the server and keep the file's
 * CRLFs; editor output is LF and may carry a trailing newline. Compare
 * EOL-normalised and trimmed. */
const normBody = (s: string): string => s.replace(/\r\n/g, '\n').trim();
export function sameBody(a: string, b: string): boolean {
  return normBody(a) === normBody(b);
}

const isConflict = (err: unknown): boolean => err instanceof ApiError && err.status === 409;
const asError = (err: unknown): Error => (err instanceof Error ? err : new Error(String(err)));

/**
 * Etag-chained autosave (spec B §7). Saves are serialised so a save never
 * 409s against our own previous write. On 409 the note is re-read: if only
 * its frontmatter changed (re-route, export stamp), the save is resent once
 * on the fresh etag; otherwise autosave pauses and `conflict` is set. While
 * paused, `save()` only records the latest text as `mine` — nothing is lost.
 */
export function useGuardedSave(
  initial: { body: string; etag: string | null },
  target: SaveTarget,
  onError?: (err: Error) => void,
): GuardedSave {
  const etagRef = useRef<string | null>(initial.etag);
  const baseBodyRef = useRef(initial.body);
  const inFlightRef = useRef(false);
  const queuedRef = useRef<string | null>(null);
  const conflictRef = useRef<Conflict | null>(null);
  const [conflict, setConflictState] = useState<Conflict | null>(null);
  const [resolving, setResolving] = useState(false);
  const targetRef = useRef(target);
  targetRef.current = target;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;

  const setConflict = useCallback((c: Conflict | null) => {
    conflictRef.current = c;
    setConflictState(c);
  }, []);

  const markSaved = (body: string, etag: string | null | undefined) => {
    etagRef.current = etag ?? null;
    baseBodyRef.current = body;
  };

  const handleConflict = async (mine: string, allowAutoResolve: boolean): Promise<void> => {
    let latest: { body: string; etag?: string | null };
    try {
      latest = await targetRef.current.fetchLatest();
    } catch (err) {
      onErrorRef.current?.(asError(err));
      // Keystrokes may have landed in the conflict while we awaited.
      setConflict({ mine: conflictRef.current?.mine ?? mine, theirs: '', theirsEtag: null, unread: true });
      return;
    }
    if (allowAutoResolve && sameBody(latest.body, baseBodyRef.current)) {
      try {
        const res = await targetRef.current.send(mine, latest.etag ?? null);
        markSaved(mine, res.etag);
      } catch (err) {
        if (isConflict(err)) await handleConflict(mine, false);
        else onErrorRef.current?.(asError(err));
      }
      return;
    }
    setConflict({
      mine: conflictRef.current?.mine ?? mine,
      theirs: latest.body,
      theirsEtag: latest.etag ?? null,
    });
  };

  const run = async (body: string): Promise<void> => {
    inFlightRef.current = true;
    try {
      const res = await targetRef.current.send(body, etagRef.current);
      markSaved(body, res.etag);
    } catch (err) {
      if (isConflict(err)) await handleConflict(body, true);
      else onErrorRef.current?.(asError(err));
    } finally {
      inFlightRef.current = false;
    }
    const next = queuedRef.current;
    queuedRef.current = null;
    if (next === null) return;
    if (conflictRef.current) setConflict({ ...conflictRef.current, mine: next });
    else await run(next);
  };

  const save = (body: string) => {
    if (conflictRef.current) {
      setConflict({ ...conflictRef.current, mine: body });
      return;
    }
    if (inFlightRef.current) {
      queuedRef.current = body;
      return;
    }
    void run(body);
  };

  const keepMine = async (): Promise<void> => {
    const start = conflictRef.current;
    if (!start) return;
    setResolving(true);
    inFlightRef.current = true;
    let followUp: string | null = null;
    try {
      const latest = await targetRef.current.fetchLatest();
      const mine = conflictRef.current?.mine ?? start.mine;
      const res = await targetRef.current.send(mine, latest.etag ?? null);
      markSaved(mine, res.etag);
      const newest = conflictRef.current?.mine;
      setConflict(null);
      if (newest !== undefined && newest !== mine) followUp = newest;
    } catch (err) {
      if (isConflict(err)) await handleConflict(conflictRef.current?.mine ?? start.mine, false);
      else onErrorRef.current?.(asError(err));
    } finally {
      inFlightRef.current = false;
      setResolving(false);
    }
    if (followUp !== null) await run(followUp);
  };

  const keepTheirs = (): Conflict | null => {
    const c = conflictRef.current;
    if (!c || c.unread) return null;
    markSaved(c.theirs, c.theirsEtag);
    setConflict(null);
    return c;
  };

  const adopt = (etag: string | null, body: string) => markSaved(body, etag);

  return { save, conflict, resolving, keepMine, keepTheirs, adopt };
}
