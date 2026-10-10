import { useCallback, useRef, useState } from 'react';
import { ApiError } from './api/client';
import type { WriteActor } from '../../shared/types';

export interface SaveTarget {
  /** Persist `body`; `ifMatch` is the etag the save is based on (null = unconditional).
   * `actor` is passed only for an attributed save (spec B §2: docs Accept). */
  send: (
    body: string,
    ifMatch: string | null,
    actor?: WriteActor,
  ) => Promise<{ etag?: string | null; status?: 'applied' | 'pending' }>;
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
  /** `mine` holds an attributed write (docs Accept). Sticky until resolved, so
   * keep mine is sent as that actor and the risk rules still apply (B3). */
  actor?: WriteActor;
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
   * keystroke. Rides with that body through the queue, the auto-resolve
   * resend and a conflict (keep mine is sent as `actor`). */
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
  /** A save came back held for approval (B3): nothing was written. Called
   * with the last saved body, which is what is on disk. */
  onHeld?: (diskBody: string) => void,
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
  const onHeldRef = useRef(onHeld);
  onHeldRef.current = onHeld;

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

  /** Resolves true when the resent change was held for approval (B3). */
  const handleConflict = async (
    mine: string,
    allowAutoResolve: boolean,
    actor?: WriteActor,
  ): Promise<boolean> => {
    let latest: { body: string; etag?: string | null };
    try {
      latest = await targetRef.current.fetchLatest();
    } catch (err) {
      onErrorRef.current?.(asError(err));
      // Keystrokes may have landed in the conflict while we awaited.
      setConflict({
        mine: conflictRef.current?.mine ?? mine,
        theirs: '',
        theirsEtag: null,
        unread: true,
        actor: conflictRef.current?.actor ?? actor,
      });
      return false;
    }
    if (sameBody(latest.body, mine)) {
      // Disk already holds my text: nothing to resolve, just take its etag.
      markSaved(mine, latest.etag);
      const c = conflictRef.current;
      if (c && sameBody(c.mine, mine)) setConflict(null);
      return false;
    }
    if (allowAutoResolve && sameBody(latest.body, baseBodyRef.current)) {
      try {
        const res = await sendAs(mine, latest.etag ?? null, actor);
        if (res.status === 'pending') {
          markSaved(baseBodyRef.current, latest.etag);
          return true;
        }
        markSaved(mine, res.etag);
      } catch (err) {
        if (isConflict(err)) return handleConflict(mine, false, actor);
        onErrorRef.current?.(asError(err));
      }
      return false;
    }
    setConflict({
      mine: conflictRef.current?.mine ?? mine,
      theirs: latest.body,
      theirsEtag: latest.etag ?? null,
      actor: conflictRef.current?.actor ?? actor,
    });
    return false;
  };

  const run = async (body: string, actor?: WriteActor): Promise<void> => {
    inFlightRef.current = true;
    let held = false;
    try {
      const res = await sendAs(body, etagRef.current, actor);
      // B3: a held change wrote nothing; the disk still matches the last save.
      if (res.status === 'pending') held = true;
      else markSaved(body, res.etag);
    } catch (err) {
      if (isConflict(err)) held = await handleConflict(body, true, actor);
      else onErrorRef.current?.(asError(err));
    } finally {
      inFlightRef.current = false;
    }
    const next = queuedRef.current;
    const nextActor = queuedActorRef.current ?? undefined;
    queuedRef.current = null;
    queuedActorRef.current = null;
    if (held) {
      // Text queued behind a held change still contains it. Saving that as a
      // keystroke would write the change without approval, so drop it and
      // put the editor back on what is on disk.
      nextActorRef.current = null;
      onHeldRef.current?.(baseBodyRef.current);
      return;
    }
    if (next === null) return;
    const c = conflictRef.current;
    if (c) setConflict({ ...c, mine: next, actor: c.actor ?? nextActor });
    else await run(next, nextActor);
  };

  const save = (body: string) => {
    const actor = nextActorRef.current ?? undefined;
    nextActorRef.current = null;
    const c = conflictRef.current;
    if (c) {
      // Once assistant text is in mine, it stays there until resolved.
      setConflict({ ...c, mine: body, actor: c.actor ?? actor });
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
    let followUpActor: WriteActor | undefined;
    let held = false;
    let actor: WriteActor | undefined;
    try {
      const latest = await targetRef.current.fetchLatest();
      const mine = conflictRef.current?.mine ?? start.mine;
      actor = conflictRef.current?.actor ?? start.actor;
      const res = await sendAs(mine, latest.etag ?? null, actor);
      const end = conflictRef.current;
      setConflict(null);
      if (res.status === 'pending') {
        // B3: held; nothing was written, so the disk still holds theirs. Text
        // typed meanwhile still contains the held change: drop it.
        markSaved(latest.body, latest.etag);
        held = true;
      } else {
        markSaved(mine, res.etag);
        if (end && end.mine !== mine) {
          followUp = end.mine;
          // Over-attributing never bypasses approval; under-attributing would.
          followUpActor = end.actor;
        }
      }
    } catch (err) {
      if (isConflict(err)) await handleConflict(conflictRef.current?.mine ?? start.mine, false, actor);
      else onErrorRef.current?.(asError(err));
    } finally {
      inFlightRef.current = false;
      setResolving(false);
    }
    if (held) {
      queuedRef.current = null;
      queuedActorRef.current = null;
      nextActorRef.current = null;
      onHeldRef.current?.(baseBodyRef.current);
      return;
    }
    if (followUp !== null) await run(followUp, followUpActor);
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
      // The restored text replaces whatever an assistant mark covered.
      nextActorRef.current = null;
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
