import { useEffect, useRef, useState } from 'react';
import type { Editor } from '@tiptap/core';
import { useGuardedSave, type SaveTarget } from '../lib/use-guarded-save';
import {
  joinPageTitle,
  retitlePage,
  splitPageTitle,
  type PageTitleSplit,
  type TitleRule,
} from '../lib/editor/page-title';
import { ConflictBanner } from './ConflictBanner';
import {
  RichMarkdownEditor,
  type EditorHandle,
  type RichMarkdownEditorProps,
} from './RichMarkdownEditor';
import { PageHeader } from './page/PageHeader';
import { PageTitle } from './page/PageTitle';
import { registerNavigationGuard, type NavigationScope } from '../stores/navigation';
import type { WriteActor } from '../../shared/types';

export interface GuardHandle {
  adopt: (etag: string | null, body: string) => void;
  /** True while the conflict banner is up (autosave paused, text unsaved). */
  hasConflict: () => boolean;
  /** Replace the note through `perform` (history restore) between autosaves,
   * then reload the editor with the result. Rejects under a conflict. */
  restore: (perform: () => Promise<{ body: string; etag?: string | null }>) => Promise<void>;
  /** The next autosave is `actor`'s write (docs panel Accept, spec B §2). */
  attributeNext: (actor: WriteActor) => void;
  /** Take a body + etag written outside the editor (extract-photo) and
   * reload the page with it, so the page title is re-read from the body. */
  reload: (etag: string | null, body: string) => void;
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

/** A7: render the note as a page. The title is a line of the body. */
export interface PageChrome {
  /** How the body holds its title (lib/editor/page-title). */
  titleRule: TitleRule;
  /** Shown when the body owns no title (a note's frontmatter title or file
   * name); '' shows the "Untitled" placeholder. */
  fallbackTitle: string;
  /** Ancestors shown above the title. */
  breadcrumb: string[];
  byline?: React.ReactNode;
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
  /** A7 page mode: breadcrumb, editable title, byline. */
  page?: PageChrome;
  editorProps: Omit<RichMarkdownEditorProps, 'markdown' | 'onSave' | 'pageHeader'>;
}

/** Per-mount title/body halves. Saves from either half rejoin them. */
interface LiveDoc {
  nonce: number;
  split: PageTitleSplit | null;
  /** Latest body half handed to the guard (the editor's last save). */
  rest: string;
  /** What the editor was mounted with (stable: a changing prop would resync it). */
  mountRest: string;
  /** Last whole note handed to guard.save (page mode); dedupes the
   * title-only save a doc replace schedules. */
  submitted: string;
}

const escapeHtml = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

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
  page,
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
    attributeNext: (actor) => guardLatest.current.attributeNext(actor),
    reload: (etag, body) => {
      guardLatest.current.adopt(etag, body);
      remount(body);
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

  // Split once per mount (initial body, restore, keep theirs, reload).
  const titleRule = page?.titleRule ?? null;
  const live = useRef<LiveDoc | null>(null);
  if (live.current === null || live.current.nonce !== doc.nonce) {
    const split = titleRule ? splitPageTitle(doc.body, titleRule) : null;
    const mountRest = split ? split.rest : doc.body;
    live.current = { nonce: doc.nonce, split, rest: mountRest, mountRest, submitted: doc.body };
  }
  const current = live.current;
  const editorRef = useRef<Editor | null>(null);
  // Bumped when a doc replace (docs panel) changes the split: remounts the
  // title field alone so it shows the new title.
  const [titleVersion, setTitleVersion] = useState(0);

  const mountNonce = doc.nonce;
  const submit = (whole: string) => {
    current.submitted = whole;
    guard.save(whole);
  };
  const commitTitle = (title: string) => {
    if (liveNonce.current !== mountNonce || !current.split) return;
    const next = retitlePage(current.split, title);
    if (!next) return;
    current.split = next;
    submit(joinPageTitle(next, current.rest));
  };
  const shownTitle = (): string =>
    current.split?.kind ? current.split.title : (page?.fallbackTitle ?? '');

  // Page mode hands the parent a handle over the whole note: the editor only
  // holds the body below the title (docs panel, PDF export).
  const outerHandleRef = page ? editorProps.handleRef : undefined;
  const innerHandle = useRef<EditorHandle | null>(null);
  const titleSaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (titleSaveTimer.current) clearTimeout(titleSaveTimer.current);
    },
    [],
  );
  const pageOps = useRef<{
    getMarkdown: () => string;
    replaceDoc: (md: string) => void;
    title: () => string;
  } | null>(null);
  pageOps.current = {
    getMarkdown: () => {
      const rest = innerHandle.current?.getMarkdown() ?? current.rest;
      return current.split ? joinPageTitle(current.split, rest) : rest;
    },
    replaceDoc: (md: string) => {
      const inner = innerHandle.current;
      if (!inner || !titleRule || liveNonce.current !== mountNonce) return;
      const next = splitPageTitle(md, titleRule);
      let rest = md;
      if (next.kind !== null) {
        rest = next.rest;
        if (current.split?.head !== next.head) {
          current.split = next;
          setTitleVersion((v) => v + 1);
        }
      }
      // When the body changed, the editor's own debounced save carries the
      // new title (and the assistant's body) in one write. Only a title-only
      // change needs its own save: arming it otherwise could send the new
      // title with the pre-Accept body under 'assistant' while the user's
      // typing holds the editor's timer back. Both saves are deferred, so a
      // synchronous attributeNext right after replaceWith still applies.
      const before = inner.getMarkdown();
      inner.replaceWith(rest, 'doc');
      if (titleSaveTimer.current) clearTimeout(titleSaveTimer.current);
      titleSaveTimer.current = null;
      if (inner.getMarkdown() !== before) return;
      const delay = editorProps.debounceMs ?? 1000;
      titleSaveTimer.current = setTimeout(() => {
        titleSaveTimer.current = null;
        if (liveNonce.current !== mountNonce || !current.split) return;
        const whole = joinPageTitle(current.split, current.rest);
        if (whole !== current.submitted) submit(whole);
      }, delay);
    },
    title: shownTitle,
  };
  const [pageHandle] = useState<EditorHandle>(() => ({
    getSelectionMarkdown: () => innerHandle.current?.getSelectionMarkdown() ?? '',
    replaceWith: (md, target) => {
      if (target === 'doc') pageOps.current?.replaceDoc(md);
      else innerHandle.current?.replaceWith(md, target);
    },
    getHTML: () => {
      const html = innerHandle.current?.getHTML() ?? '';
      const t = pageOps.current?.title() ?? '';
      return html && t ? `<h1>${escapeHtml(t)}</h1>${html}` : html;
    },
    getMarkdown: () => pageOps.current?.getMarkdown() ?? '',
  }));
  useEffect(() => {
    if (!outerHandleRef) return;
    outerHandleRef.current = pageHandle;
    return () => {
      if (outerHandleRef.current === pageHandle) outerHandleRef.current = null;
    };
  }, [outerHandleRef, pageHandle]);

  const header =
    page && current.split ? (
      <PageHeader
        breadcrumb={page.breadcrumb}
        byline={page.byline}
        focus={editorProps.focus === true}
        title={
          <PageTitle
            key={titleVersion}
            value={shownTitle()}
            readOnly={editorProps.readOnly}
            debounceMs={editorProps.debounceMs}
            onCommit={commitTitle}
            onEnter={() => editorRef.current?.commands.focus('start')}
          />
        }
      />
    ) : undefined;

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
        markdown={current.mountRest}
        onSave={(md) => {
          if (liveNonce.current !== mountNonce) return;
          if (!current.split) {
            guard.save(md);
            return;
          }
          current.rest = md;
          submit(joinPageTitle(current.split, md));
        }}
        {...editorProps}
        handleRef={page ? innerHandle : editorProps.handleRef}
        onEditorReady={(e) => {
          editorRef.current = e;
          editorProps.onEditorReady?.(e);
        }}
        pageHeader={header}
      />
    </>
  );
}
