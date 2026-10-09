import { useState } from 'react';
import { useGuardedSave, type SaveTarget } from '../lib/use-guarded-save';
import { ConflictBanner } from './ConflictBanner';
import { RichMarkdownEditor, type RichMarkdownEditorProps } from './RichMarkdownEditor';

export interface GuardHandle {
  adopt: (etag: string | null, body: string) => void;
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
  if (guardRef) guardRef.current = { adopt: guard.adopt };

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
