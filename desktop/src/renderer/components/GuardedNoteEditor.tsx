import { useEffect, useRef, useState } from 'react';
import { useGuardedSave, type SaveTarget } from '../lib/use-guarded-save';
import { ConflictBanner } from './ConflictBanner';
import { RichMarkdownEditor, type RichMarkdownEditorProps } from './RichMarkdownEditor';
import { registerNavigationGuard, type NavigationScope } from '../stores/navigation';

export interface GuardHandle {
  adopt: (etag: string | null, body: string) => void;
  /** True while the conflict banner is up (autosave paused, text unsaved). */
  hasConflict: () => boolean;
  /** Replace the note through `perform` (history restore) between autosaves,
   * then reload the editor with the result. Rejects under a conflict. */
  restore: (perform: () => Promise<{ body: string; etag?: string | null }>) => Promise<void>;
}

const DISCARD_PROMPT =
  'This note changed outside the editor and your text is not saved. Discard your text?';

/** Call before navigating away from a guarded editor: true when it is safe to
 * leave (no conflict, or the user agreed to discard their unsaved text). */
export function confirmLeave(guardRef: React.MutableRefObject<GuardHandle | null>): boolean {
  return confirmDiscard(guardRef.current);
}

function confirmDiscard(handle: GuardHandle | null): boolean {
  return !handle?.hasConflict() || window.confirm(DISCARD_PROMPT);
}

export interface GuardedNoteEditorProps {
  initialBody: string;
  initialEtag: string | null;
  send: SaveTarget['send'];
  fetchLatest: SaveTarget['fetchLatest'];
  onSaveError?: (err: Error) => void;
  /** Lets the parent hand over an etag produced outside the editor (extract-photo). */
  guardRef?: React.MutableRefObject<GuardHandle | null>;
  /** App navigation that would unmount this editor; guarded (same prompt)
   * while the conflict banner is up. */
  navigationScope?: NavigationScope;
  editorProps: Omit<RichMarkdownEditorProps, 'markdown' | 'onSave'>;
}

/** RichMarkdownEditor with If-Match autosave and the conflict banner.
 * Parents remount it per note (key=…); initial body/etag are read once. */
export function GuardedNoteEditor({
  initialBody,
  initialEtag,
  send,
  fetchLatest,
  onSaveError,
  guardRef,
  navigationScope,
  editorProps,
}: GuardedNoteEditorProps) {
  const [doc, setDoc] = useState({ body: initialBody, nonce: 0 });
  // Bumped synchronously on every reload, so a debounced save from the
  // replaced editor instance (scheduled before a restore) is dropped.
  const liveNonce = useRef(0);
  const remount = (body: string) => {
    liveNonce.current += 1;
    setDoc({ body, nonce: liveNonce.current });
  };
  const guard = useGuardedSave(
    { body: initialBody, etag: initialEtag },
    { send, fetchLatest },
    onSaveError,
  );
  const guardLatest = useRef(guard);
  guardLatest.current = guard;
  // One stable handle per mount, so unmount only clears its own registration
  // (a key remount mounts the next editor's handle in the same commit).
  const [handle] = useState<GuardHandle>(() => ({
    adopt: (etag, body) => guardLatest.current.adopt(etag, body),
    hasConflict: () => guardLatest.current.hasConflict(),
    restore: async (perform) => {
      const res = await guardLatest.current.runExclusive(perform);
      remount(res.body);
    },
  }));
  useEffect(() => {
    if (!guardRef) return;
    guardRef.current = handle;
    return () => {
      if (guardRef.current === handle) guardRef.current = null;
    };
  }, [guardRef, handle]);
  const conflictPending = guard.conflict !== null;
  useEffect(() => {
    if (!navigationScope || !conflictPending) return;
    return registerNavigationGuard(navigationScope, () => confirmDiscard(handle));
  }, [navigationScope, conflictPending, handle]);

  const keepTheirs = () => {
    const c = guard.keepTheirs();
    if (c) remount(c.theirs);
  };

  const mountNonce = doc.nonce;
  return (
    <>
      {guard.conflict && (
        <ConflictBanner
          conflict={guard.conflict}
          resolving={guard.resolving}
          onKeepMine={() => void guard.keepMine()}
          onKeepTheirs={keepTheirs}
        />
      )}
      <RichMarkdownEditor
        key={doc.nonce}
        markdown={doc.body}
        onSave={(body) => {
          if (liveNonce.current === mountNonce) guard.save(body);
        }}
        {...editorProps}
      />
    </>
  );
}
