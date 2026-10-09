import { useEffect, useRef, useState } from 'react';
import { useGuardedSave, type SaveTarget } from '../lib/use-guarded-save';
import { ConflictBanner } from './ConflictBanner';
import { RichMarkdownEditor, type RichMarkdownEditorProps } from './RichMarkdownEditor';

export interface GuardHandle {
  adopt: (etag: string | null, body: string) => void;
  /** True while the conflict banner is up (autosave paused, text unsaved). */
  hasConflict: () => boolean;
}

const DISCARD_PROMPT =
  'This note changed outside the editor and your text is not saved. Discard your text?';

/** Call before navigating away from a guarded editor: true when it is safe to
 * leave (no conflict, or the user agreed to discard their unsaved text). */
export function confirmLeave(guardRef: React.MutableRefObject<GuardHandle | null>): boolean {
  return !guardRef.current?.hasConflict() || window.confirm(DISCARD_PROMPT);
}

export interface GuardedNoteEditorProps {
  initialBody: string;
  initialEtag: string | null;
  send: SaveTarget['send'];
  fetchLatest: SaveTarget['fetchLatest'];
  onSaveError?: (err: Error) => void;
  /** Lets the parent hand over an etag produced outside the editor (extract-photo). */
  guardRef?: React.MutableRefObject<GuardHandle | null>;
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
  editorProps,
}: GuardedNoteEditorProps) {
  const [doc, setDoc] = useState({ body: initialBody, nonce: 0 });
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
  }));
  useEffect(() => {
    if (!guardRef) return;
    guardRef.current = handle;
    return () => {
      if (guardRef.current === handle) guardRef.current = null;
    };
  }, [guardRef, handle]);

  const keepTheirs = () => {
    const c = guard.keepTheirs();
    if (c) setDoc((d) => ({ body: c.theirs, nonce: d.nonce + 1 }));
  };

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
      <RichMarkdownEditor key={doc.nonce} markdown={doc.body} onSave={guard.save} {...editorProps} />
    </>
  );
}
