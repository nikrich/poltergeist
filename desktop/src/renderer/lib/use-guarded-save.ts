import { useCallback, useRef, useState } from 'react';
import { ApiError } from './api/client';
import type { WriteActor } from '../../shared/types';

export interface SaveTarget {
  /** Persist `body`; `ifMatch` is the etag the save is based on (null = unconditional).
   * `actor` is passed only for an attributed save (spec B §2: docs Accept). */
  send: (body: string, ifMatch: string | null, actor?: WriteActor) => Promise<{ etag?: string | null }>;
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
  /** Reads the live conflict state (a ref), never a stale render's. */
  hasConflict: () => boolean;
  /** Run a whole-note replacement (history restore) between autosaves: waits
   * for the in-flight save and its queue, adopts the result's etag, drops text
   * queued meanwhile on success (the editor reloads) and replays it on
   * failure. Rejects with RESTORE_BLOCKED while a conflict is up. */
  runExclusive: <T extends { body: string; etag?: string | null }>(
    perform: () => Promise<T>,
  ) => Promise<T>;
  /** The next save() is `actor`'s write (the docs panel's Accept), not a
   * keystroke. Rides with that body through the queue and the auto-resolve
   * resend; dropped if the save lands in a conflict (the user decides then). */
  attributeNext: (actor: WriteActor) => void;
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
export const RESTORE_BLOCKED = 'resolve the conflict banner first (keep mine or keep theirs)';
const IDLE_POLL_MS = 20;

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
  const nextActorRef = useRef<WriteActor | null>(null);
  const queuedActorRef = useRef<WriteActor | null>(null);
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

  const sendAs = (body: string, ifMatch: string | null, actor?: WriteActor) =>
    actor ? targetRef.current.send(body, ifMatch, actor) : targetRef.current.send(body, ifMatch);

  const handleConflict = async (
    mine: string,
    allowAutoResolve: boolean,
    actor?: WriteActor,
  ): Promise<void> => {
    let latest: { body: string; etag?: string | null };
    try {
      latest = await targetRef.current.fetchLatest();
    } catch (err) {
      onErrorRef.current?.(asError(err));
      // Keystrokes may have landed in the conflict while we awaited.
      setConflict({ mine: conflictRef.current?.mine ?? mine, theirs: '', theirsEtag: null, unread: true });
      return;
    }
    if (sameBody(latest.body, mine)) {
      // Disk already holds my text: nothing to resolve, just take its etag.
      markSaved(mine, latest.etag);
      const c = conflictRef.current;
      if (c && sameBody(c.mine, mine)) setConflict(null);
      return;
    }
    if (allowAutoResolve && sameBody(latest.body, baseBodyRef.current)) {
      try {
        const res = await sendAs(mine, latest.etag ?? null, actor);
        markSaved(mine, res.etag);
      } catch (err) {
        if (isConflict(err)) await handleConflict(mine, false, actor);
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

  const run = async (body: string, actor?: WriteActor): Promise<void> => {
    inFlightRef.current = true;
    try {
      const res = await sendAs(body, etagRef.current, actor);
      markSaved(body, res.etag);
    } catch (err) {
      if (isConflict(err)) await handleConflict(body, true, actor);
      else onErrorRef.current?.(asError(err));
    } finally {
      inFlightRef.current = false;
    }
    const next = queuedRef.current;
    const nextActor = queuedActorRef.current ?? undefined;
    queuedRef.current = null;
    queuedActorRef.current = null;
    if (next === null) return;
    if (conflictRef.current) setConflict({ ...conflictRef.current, mine: next });
    else await run(next, nextActor);
  };

  const save = (body: string) => {
    const actor = nextActorRef.current ?? undefined;
    nextActorRef.current = null;
    if (conflictRef.current) {
      setConflict({ ...conflictRef.current, mine: body });
      return;
    }
    if (inFlightRef.current) {
      // A newer body replaces the queued one but still holds the AI text,
      // so an assistant mark already queued is kept.
      queuedRef.current = body;
      if (actor) queuedActorRef.current = actor;
      return;
    }
    void run(body, actor);
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

  const runExclusive = async <T extends { body: string; etag?: string | null }>(
    perform: () => Promise<T>,
  ): Promise<T> => {
    if (conflictRef.current) throw new Error(RESTORE_BLOCKED);
    while (inFlightRef.current) await new Promise((r) => setTimeout(r, IDLE_POLL_MS));
    if (conflictRef.current) throw new Error(RESTORE_BLOCKED);
    inFlightRef.current = true;
    let ok = false;
    try {
      const res = await perform();
      markSaved(res.body, res.etag);
      ok = true;
      return res;
    } finally {
      inFlightRef.current = false;
      const next = queuedRef.current;
      const nextActor = queuedActorRef.current ?? undefined;
      queuedRef.current = null;
      queuedActorRef.current = null;
      if (!ok && next !== null) void run(next, nextActor);
    }
  };

  const keepTheirs = (): Conflict | null => {
    const c = conflictRef.current;
    if (!c || c.unread) return null;
    markSaved(c.theirs, c.theirsEtag);
    setConflict(null);
    return c;
  };

  const adopt = (etag: string | null, body: string) => markSaved(body, etag);

  const hasConflict = () => conflictRef.current !== null;

  const attributeNext = (actor: WriteActor) => {
    nextActorRef.current = actor;
  };

  return {
    save,
    conflict,
    resolving,
    keepMine,
    keepTheirs,
    adopt,
    hasConflict,
    runExclusive,
    attributeNext,
  };
}
