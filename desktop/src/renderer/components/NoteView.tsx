import { useEffect, useRef } from 'react';
import type { Editor } from '@tiptap/core';

import { get } from '../lib/api/client';
import { useNote, useUpdateNoteByPath } from '../lib/api/hooks';
import type { Note } from '../../shared/api-types';
import { useNoteView } from '../stores/note-view';
import { useGraphView } from '../stores/graph-view';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import { Lucide } from './Lucide';
import { Btn } from './Btn';
import { Pill } from './Pill';
import { GuardedNoteEditor, confirmLeave, type GuardHandle } from './GuardedNoteEditor';
import { SkeletonRows } from './SkeletonRows';
import { PanelError } from './PanelError';
import { openWikilink } from '../lib/open-wikilink';
import { BacklinksPanel } from './BacklinksPanel';
import { NoteHistoryButton } from './NoteHistory';
import { FocusBar } from './FocusBar';
import { focusActiveNow, setFocusMode, useFocusActive, useFocusSurface } from '../lib/focus-mode';
import { shortcutLabel } from '../lib/editor-shortcuts';

interface Props {
  /** Test hook: receives the TipTap Editor instance once created. */
  onEditorReady?: (editor: Editor) => void;
}

export function NoteView({ onEditorReady }: Props = {}) {
  const path = useNoteView((s) => s.path);
  const closeView = useNoteView((s) => s.close);
  const openView = useNoteView((s) => s.open);
  // Leaving under the conflict banner would drop the unsaved text: ask first.
  // Opening another note is guarded in the store (navigationScope="note"),
  // which covers links from inside this view and from anywhere else.
  const guardRef = useRef<GuardHandle | null>(null);
  const close = () => {
    if (confirmLeave(guardRef)) closeView();
  };
  const closeRef = useRef(close);
  closeRef.current = close;
  const note = useNote(path);
  const vaultPath = useSettings((s) => s.vaultPath);
  const updateNote = useUpdateNoteByPath();
  const showInGraph = useGraphView((s) => s.showInGraph);

  useEffect(() => {
    if (path === null) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return;
      // In focus mode the first Esc belongs to focus mode (App's hook leaves
      // it); only a later Esc closes the viewer.
      if (focusActiveNow()) return;
      closeRef.current();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [path]);

  // Freeze the FIRST fetched body + etag per path (same pattern as JotsScreen):
  // useUpdateNoteByPath invalidates ['note'] after every autosave, and a
  // refetched body flowing back into the editor would reset it mid-typing.
  // The etag is frozen with it: GuardedNoteEditor chains etags itself.
  const initialBodyRef = useRef<{ path: string; body: string; etag: string | null } | null>(null);
  if (
    note.data &&
    path &&
    (initialBodyRef.current === null || initialBodyRef.current.path !== path)
  ) {
    initialBodyRef.current = { path, body: note.data.body, etag: note.data.etag ?? null };
  }
  if (path === null && initialBodyRef.current !== null) {
    initialBodyRef.current = null;
  }
  const initial = initialBodyRef.current?.path === path ? initialBodyRef.current : undefined;
  useFocusSurface(initial !== undefined);
  const focusActive = useFocusActive();

  if (path === null) return null;

  // Connector-managed warning (spec): frontmatter `source` present and not
  // "manual" → best-effort edits, may be overwritten by the next sync.
  const source = note.data?.frontmatter?.source;
  const isSynced = typeof source === 'string' && source !== 'manual';

  const openInEditor = async () => {
    const target = `${vaultPath}/${path}`;
    const result = await window.gb.shell.openPath(target);
    if (!result.ok) toast.error(result.error);
  };

  const openInGraph = () => {
    if (!path || !confirmLeave(guardRef)) return;
    closeView();
    showInGraph(path);
  };

  // Closing the dialog mid-debounce cancels the pending save (editor unmount
  // clears its timer) — deliberate: a flush-on-close could write a half-edited
  // doc. Edits within the last ~1s of closing are lost.

  return (
    <div
      role="dialog"
      aria-label="note viewer"
      className="fixed inset-0 z-40 flex justify-end bg-[rgba(14,15,18,0.55)] backdrop-blur-sm"
      onClick={close}
    >
      <div
        className={
          focusActive
            ? 'flex h-full w-full flex-col bg-paper'
            : 'flex h-full w-[820px] max-w-[92vw] flex-col border-l border-hairline bg-paper shadow-xl'
        }
        onClick={(e) => e.stopPropagation()}
      >
        {focusActive ? (
          <FocusBar />
        ) : (
          <header className="flex items-center gap-3 border-b border-hairline px-6 py-4">
            <Lucide name="file-text" size={14} color="var(--ink-2)" />
            <div className="min-w-0 flex-1 leading-[1.2]">
              <div className="truncate text-13 font-medium text-ink-0">
                {note.data?.title ?? path.split('/').pop()}
              </div>
              <div className="truncate font-mono text-10 text-ink-3">{path}</div>
            </div>
            {isSynced && (
              <Pill tone="oxblood">
                synced note — edits may be overwritten by the next sync
              </Pill>
            )}
            <NoteHistoryButton key={path} path={path} guardRef={guardRef} />
            <Btn
              variant="ghost"
              size="sm"
              icon={<Lucide name="maximize-2" size={13} />}
              onClick={() => void setFocusMode(true)}
              ariaLabel={`focus mode (${shortcutLabel('focus')})`}
            />
            <Btn
              variant="ghost"
              size="sm"
              icon={<Lucide name="network" size={13} />}
              onClick={openInGraph}
            >
              show in graph
            </Btn>
            <Btn
              variant="ghost"
              size="sm"
              icon={<Lucide name="external-link" size={13} />}
              onClick={openInEditor}
            >
              open in editor
            </Btn>
            <Btn
              variant="ghost"
              size="sm"
              icon={<Lucide name="x" size={14} />}
              onClick={close}
              ariaLabel="close"
            />
          </header>
        )}

        <div className="flex flex-1 flex-col overflow-hidden">
          {note.isLoading && (
            <div className="p-6">
              <SkeletonRows count={6} />
            </div>
          )}
          {note.isError && (
            <div className="p-6">
              <PanelError
                message={
                  note.error instanceof Error ? note.error.message : 'failed to load note'
                }
                onRetry={() => note.refetch()}
              />
            </div>
          )}
          {initial !== undefined && (
            <>
              <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
                <GuardedNoteEditor
                  key={path}
                  initialBody={initial.body}
                  initialEtag={initial.etag}
                  send={(body, ifMatch) => updateNote.mutateAsync({ path, body, ifMatch })}
                  fetchLatest={() => get<Note>(`/v1/notes?path=${encodeURIComponent(path)}`)}
                  onSaveError={(err) => toast.error(`save failed: ${err.message}`)}
                  guardRef={guardRef}
                  navigationScope="note"
                  editorProps={{
                    focus: focusActive,
                    jotId: path,
                    onEditorReady,
                    onWikilinkClick: (target) => openWikilink(target, openView),
                  }}
                />
              </div>
              {!focusActive && <BacklinksPanel path={path} onOpen={openView} />}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
