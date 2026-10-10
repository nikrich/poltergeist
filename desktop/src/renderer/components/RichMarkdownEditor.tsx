import { useCallback, useEffect, useRef, useState } from 'react';
import { Editor } from '@tiptap/core';
import { EditorContent, useEditor } from '@tiptap/react';
import { CellSelection } from '@tiptap/pm/tables';
import { buildEditorExtensions } from '../lib/editor/extensions';
import { onGb } from '../lib/editor/events';
import { clipboardPayload, getMarkdown, selectionMarkdown } from '../lib/editor/markdown';
import { insertImageFile } from '../lib/editor/insert-image';
import { noteTarget } from '../lib/editor/link-suggest';
import {
  acceptAiSuggestion,
  attachAiSuggestion,
  clearAiSuggestion,
  getAiSuggestion,
  type SuggestionKey,
} from '../lib/editor/ai-suggestion';
import {
  captureInlineContext,
  type InlineAction,
  type InlineAssistTarget,
  type InlineContext,
} from '../lib/editor/inline-assist';
import { matchesShortcut } from '../lib/editor-shortcuts';
import { isMac } from '../lib/platform';
import { toast } from '../stores/toast';
import { Btn } from './Btn';
import { DiagramModal } from './DiagramModal';
import { EditorToolbar } from './EditorToolbar';
import { InlineAssistPopover } from './InlineAssistPopover';
import { JotEditor } from './JotEditor';
import { Lucide } from './Lucide';
import { ReadAloudControls } from './ReadAloudControls';
import { StatusPopover } from './StatusPopover';
import { TableToolbar } from './TableToolbar';
import { WebcamCaptureModal } from './WebcamCaptureModal';
import { TemplateInsertDialog } from './TemplatePicker';

export interface EditorHandle {
  /** Markdown for the current selection; '' when collapsed. */
  getSelectionMarkdown: () => string;
  /** Replace current selection (or whole doc when target='doc') with markdown. */
  replaceWith: (markdown: string, target: 'selection' | 'doc') => void;
  /** Full document as HTML (for PDF export); '' in source mode. */
  getHTML: () => string;
  /** Full document as markdown. */
  getMarkdown: () => string;
  /** Open inline AI on the current selection and run `action` at once (the
   * docs panel hands selection-level actions here). False when inline AI is
   * unavailable: source mode, read-only, no target, or a cell selection.
   * This is the entry point other UI (e.g. an Insert-menu "Ask AI") calls. */
  startInlineAssist?: (action: InlineAction) => boolean;
}

// Regex matching Obsidian-style wikilinks: [[path]] or [[path|alias]]
// Paths may contain slashes and colons; `[` excluded so a malformed
// "[[a [[b]]" can never parse as one span with path "a [[b".
const WIKILINK_RE = /\[\[([^\][|]+?)(?:\|[^\]]+)?\]\]/g;

/** Given the full text of a text node and a character offset within it,
 * return the wikilink target (path portion before `|`) if the offset falls
 * inside a `[[...]]` span; otherwise return null. */
function wikilinkAtOffset(text: string, offset: number): string | null {
  WIKILINK_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = WIKILINK_RE.exec(text)) !== null) {
    const start = match.index;
    const end = start + match[0].length;
    if (offset >= start && offset < end) {
      return match[1]!.trim();
    }
  }
  return null;
}

export interface RichMarkdownEditorProps {
  markdown: string;
  onSave: (markdown: string) => void;
  readOnly?: boolean;
  /** Autosave debounce in ms. Defaults to 1000. */
  debounceMs?: number;
  /** Called once when the TipTap Editor instance is created; useful for tests. */
  onEditorReady?: (editor: Editor) => void;
  /** Called when the user clicks a [[wikilink]] in the rich view; receives the
   * path portion (before any `|` alias).  Clicks outside wikilinks are ignored. */
  onWikilinkClick?: (target: string) => void;
  /** Populated with imperative methods for the docs-assist panel and PDF export. */
  handleRef?: React.MutableRefObject<EditorHandle | null>;
  /** The jotId of the currently open note; used for asset writes on paste/drop. */
  jotId: string;
  /** Called after a photo is successfully inserted; receives the jotId and asset path. */
  onPhotoInserted?: (jotId: string, assetPath: string) => void;
  /** Increment this number to programmatically open the webcam modal. */
  openCameraSignal?: number;
  /** Focus mode (A4): hide the formatting toolbar and centre the page. */
  focus?: boolean;
  /** Enables inline AI (⌘J / ✦, spec A5): the note the assist reads, and a
   * hook called right before an accepted suggestion is saved (the caller
   * marks that save as the assistant's — B2 attributeNext). Other entry
   * points (e.g. an Insert-menu "Ask AI") go through
   * `EditorHandle.startInlineAssist`; they work only while this is set. */
  inlineAssist?: { target: InlineAssistTarget; onAccept?: () => void };
}

type Mode = 'rich' | 'source';

/** Pre-flight parse probe so markdown the rich editor cannot represent never
 * blocks opening a note (spec: automatic fallback to source mode + toast).
 * Costs one throwaway parse per mount — notes are small, acceptable. */
function parsesAsRich(markdown: string): boolean {
  try {
    const probe = new Editor({ extensions: buildEditorExtensions(), content: markdown });
    probe.destroy();
    return true;
  } catch {
    return false;
  }
}

export function RichMarkdownEditor({
  markdown,
  onSave,
  readOnly = false,
  debounceMs = 1000,
  onEditorReady,
  onWikilinkClick,
  handleRef,
  jotId,
  onPhotoInserted,
  openCameraSignal,
  focus = false,
  inlineAssist,
}: RichMarkdownEditorProps) {
  // Evaluated once per mount; parents remount per note via key={...}.
  const [parseFailed] = useState(() => !parsesAsRich(markdown));
  const [mode, setMode] = useState<Mode>(parseFailed ? 'source' : 'rich');
  const [camOpen, setCamOpen] = useState(false);
  const [templateOpen, setTemplateOpen] = useState(false);
  const [statusPos, setStatusPos] = useState<number | null>(null);
  const closeStatus = useCallback(() => setStatusPos(null), []);
  const [diagramSource, setDiagramSource] = useState<string | null>(null);
  const closeDiagram = useCallback(() => setDiagramSource(null), []);
  const [inline, setInline] = useState<{ ctx: InlineContext; initial?: InlineAction; n: number } | null>(null);
  const inlineKeyRef = useRef<((key: SuggestionKey) => boolean) | null>(null);
  // editorProps.handleKeyDown is captured once — route ⌘J through a ref.
  const openInlineRef = useRef<(initial?: InlineAction) => boolean>(() => false);
  // Track previous openCameraSignal to skip the initial mount value.
  const prevCameraSignalRef = useRef(openCameraSignal);

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSaved = useRef(markdown);
  // Latest content from either mode — handed over when toggling so no
  // keystrokes are lost.
  const current = useRef(markdown);
  // editorProps.handleKeyDown is captured once at editor creation — route the
  // shortcut through a ref so it always sees the latest closure.
  const handleCopyRef = useRef<() => void>(() => {});
  // Same pattern for wikilink click — ref keeps the callback fresh.
  const onWikilinkClickRef = useRef<((target: string) => void) | undefined>(undefined);
  // editorProps callbacks are captured once — route editor instance and jotId
  // through refs so handlePaste/handleDrop always see fresh values.
  const editorRef = useRef<Editor | null>(null);
  const jotIdRef = useRef(jotId);
  jotIdRef.current = jotId;

  useEffect(() => {
    if (parseFailed) {
      toast.error('note could not be opened in rich mode — falling back to source');
    }
    // mount-only: parseFailed is fixed for the lifetime of the component
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function scheduleSave(next: string) {
    current.current = next;
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      if (next !== lastSaved.current) {
        // Deliberate trade-off (same as JotEditor): lastSaved advances even
        // if the caller's save fails — no retry for debounced autosave.
        lastSaved.current = next;
        onSave(next);
      }
    }, debounceMs);
  }

  /** Save now instead of after the debounce. `beforeSave` runs only when a
   * save is actually sent (inline accept: attribute exactly that save). */
  function flushSave(beforeSave?: () => void): boolean {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    const next = current.current;
    if (next === lastSaved.current) return false;
    beforeSave?.();
    lastSaved.current = next;
    onSave(next);
    return true;
  }

  const editor = useEditor({
    extensions: buildEditorExtensions(),
    content: parseFailed ? '' : markdown,
    editable: !readOnly,
    editorProps: {
      handleKeyDown: (_view, event) => {
        if (
          (event.metaKey || event.ctrlKey) &&
          event.shiftKey &&
          event.key.toLowerCase() === 'c'
        ) {
          event.preventDefault();
          handleCopyRef.current();
          return true;
        }
        if (matchesShortcut(event, 'inlineAi', isMac)) {
          event.preventDefault();
          openInlineRef.current();
          return true;
        }
        return false;
      },
      handleClick: (view, pos) => {
        const cb = onWikilinkClickRef.current;
        if (!cb) return false;
        // Resolve the position to the parent text block and inspect the text.
        const resolved = view.state.doc.resolve(pos);
        const parent = resolved.parent;
        if (!parent || !parent.isTextblock) return false;
        // Walk inline children to find the text node at this offset and the
        // character position within it.
        const offsetInParent = resolved.parentOffset;
        let walked = 0;
        for (let i = 0; i < parent.childCount; i++) {
          const child = parent.child(i);
          const childEnd = walked + child.nodeSize;
          if (child.isText && child.text && offsetInParent >= walked && offsetInParent < childEnd) {
            const charOffset = offsetInParent - walked;
            const target = wikilinkAtOffset(child.text, charOffset);
            if (target) {
              cb(target);
              return true;
            }
            break;
          }
          walked += child.nodeSize;
        }
        return false;
      },
      handlePaste: (_view, event) => {
        const files = Array.from(event.clipboardData?.files ?? []).filter((f) =>
          f.type.startsWith('image/'),
        );
        if (files.length === 0 || !editorRef.current || !editorRef.current.isEditable) return false;
        event.preventDefault();
        files.forEach((f) =>
          void insertImageFile(editorRef.current!, jotIdRef.current, f).catch((e: Error) =>
            toast.error(`image insert failed: ${e.message}`),
          ),
        );
        return true;
      },
      handleDrop: (_view, event) => {
        const files = Array.from((event as DragEvent).dataTransfer?.files ?? []).filter((f) =>
          f.type.startsWith('image/'),
        );
        if (files.length === 0 || !editorRef.current || !editorRef.current.isEditable) return false;
        event.preventDefault();
        files.forEach((f) =>
          void insertImageFile(editorRef.current!, jotIdRef.current, f).catch((e: Error) =>
            toast.error(`image insert failed: ${e.message}`),
          ),
        );
        return true;
      },
    },
    onUpdate: ({ editor: updated }) => {
      scheduleSave(getMarkdown(updated));
    },
  });

  // Call onEditorReady via useEffect so it fires synchronously inside React's
  // act() in tests. TipTap fires onCreate via window.setTimeout(0), which with
  // fake timers would require advancing the clock — useEffect avoids that.
  // onEditorReady intentionally excluded: it is a callback that changes every
  // render but must only fire once per editor instance.
  /* eslint-disable react-hooks/exhaustive-deps */
  useEffect(() => {
    if (editor) {
      editorRef.current = editor;
      onEditorReady?.(editor);
    }
  }, [editor]);
  /* eslint-enable react-hooks/exhaustive-deps */

  // Inline AI's decoration diff (runtime plugin; the schema is untouched).
  useEffect(() => {
    if (!editor) return;
    return attachAiSuggestion(editor, { onKey: (key) => inlineKeyRef.current?.(key) ?? false });
  }, [editor]);

  // Subscribe to slash-command photo event emitted by the editor extensions.
  useEffect(() => {
    if (!editor) return;
    const handler = () => setCamOpen(!readOnly);
    editor.on('gb:slash:photo' as Parameters<typeof editor.on>[0], handler);
    return () => {
      editor.off('gb:slash:photo' as Parameters<typeof editor.off>[0], handler);
    };
  }, [editor, readOnly]);

  // Subscribe to the /template slash command (smart templates, C1).
  useEffect(() => {
    if (!editor) return;
    const handler = () => setTemplateOpen(true);
    editor.on('gb:slash:template' as Parameters<typeof editor.on>[0], handler);
    return () => {
      editor.off('gb:slash:template' as Parameters<typeof editor.off>[0], handler);
    };
  }, [editor]);

  useEffect(() => {
    if (!editor) return;
    return onGb(editor, 'gb:status:edit', ({ pos }) => setStatusPos(pos));
  }, [editor]);

  // Any document edit can move the lozenge — close the popover rather than act on a stale position.
  useEffect(() => {
    if (!editor) return;
    const onTransaction = ({ transaction }: { transaction: { docChanged: boolean } }): void => {
      if (transaction.docChanged) setStatusPos(null);
    };
    editor.on('transaction', onTransaction);
    return () => {
      editor.off('transaction', onTransaction);
    };
  }, [editor]);

  useEffect(() => {
    if (!editor) return;
    return onGb(editor, 'gb:diagram:open', ({ source }) => setDiagramSource(source));
  }, [editor]);

  // A live query result was clicked: open it the way a [[wikilink]] opens,
  // so the host's unsaved-changes guard applies.
  useEffect(() => {
    if (!editor) return;
    return onGb(editor, 'gb:query:open', ({ path }) => onWikilinkClickRef.current?.(noteTarget(path)));
  }, [editor]);

  // Open the camera whenever openCameraSignal is incremented (skip initial mount).
  useEffect(() => {
    if (openCameraSignal === prevCameraSignalRef.current) return;
    prevCameraSignalRef.current = openCameraSignal;
    setCamOpen(!readOnly);
  }, [openCameraSignal, readOnly]);

  function openInline(initial?: InlineAction): boolean {
    if (!editor || editor.isDestroyed || mode !== 'rich' || readOnly || !inlineAssist) return false;
    if (editor.state.selection instanceof CellSelection) {
      toast.error('select text inside one table cell for inline ai');
      return false;
    }
    if (inline) {
      if (!initial) return true;
      // A new action (docs panel) replaces the open popover: re-keying
      // unmounts the old one, whose teardown stops its stream.
      clearAiSuggestion(editor);
      flushSave();
      const fresh = captureInlineContext(editor);
      setInline((prev) => ({ ctx: fresh, initial, n: (prev?.n ?? 0) + 1 }));
      return true;
    }
    // Keystrokes typed before ⌘J are the user's: save them unattributed first.
    flushSave();
    const ctx = captureInlineContext(editor);
    setInline((prev) => ({ ctx, initial, n: (prev?.n ?? 0) + 1 }));
    return true;
  }

  function closeInline() {
    setInline(null);
    if (editor && !editor.isDestroyed) {
      clearAiSuggestion(editor);
      editor.commands.focus();
    }
  }

  function acceptInline() {
    if (!editor || editor.isDestroyed) return;
    // Defensive: anything still debounced is the user's, never the assistant's.
    flushSave();
    const changed = acceptAiSuggestion(editor);
    setInline(null);
    // One immediate save carrying exactly the accepted text, marked as the
    // assistant's; nothing is marked when the accept changed nothing.
    if (changed) flushSave(inlineAssist?.onAccept);
    editor.commands.focus();
  }

  // The popover's context is a position snapshot. Until an action locks the
  // document (a suggestion exists), any edit makes it stale: close instead.
  const inlineOpen = inline !== null;
  useEffect(() => {
    if (!editor || !inlineOpen) return;
    const onTransaction = ({ transaction }: { transaction: { docChanged: boolean } }): void => {
      if (transaction.docChanged && !getAiSuggestion(editor)) setInline(null);
    };
    editor.on('transaction', onTransaction);
    return () => {
      editor.off('transaction', onTransaction);
    };
  }, [editor, inlineOpen]);

  // Populate the imperative handle so docs-assist panel and PDF export can
  // programmatically read/replace editor content without prop drilling.
  // Keyed on editor + mode + handleRef so the handle stays fresh when mode
  // toggles between rich and source.
  useEffect(() => {
    if (!handleRef) return;
    handleRef.current = {
      getSelectionMarkdown(): string {
        // Source mode has no selection concept we can extract here.
        if (!editor || editor.isDestroyed || mode !== 'rich') return '';
        return selectionMarkdown(editor);
      },
      replaceWith(md: string, target: 'selection' | 'doc'): void {
        if (editor && !editor.isDestroyed) clearAiSuggestion(editor);
        setInline(null);
        if (mode === 'rich' && editor && !editor.isDestroyed) {
          if (target === 'selection') {
            // tiptap-markdown@0.8.10 overrides insertContentAt (and setContent)
            // in the merged command registry to parse strings through
            // editor.storage.markdown.parser — so insertContent(md) parses
            // markdown into rich content, replacing the current selection.
            editor.chain().focus().insertContent(md).run();
          } else {
            // Whole-doc replacement: same mechanism the markdown-prop resync
            // effect uses — setContent treats a string as markdown when
            // tiptap-markdown is active (emitUpdate=false so the resync does
            // not itself schedule a save).
            editor.commands.setContent(md, false);
          }
          scheduleSave(getMarkdown(editor));
        } else if (mode === 'source') {
          // Source mode: update the tracked current value and schedule a save.
          // The visible CodeMirror editor will reflect the new content only
          // on its next remount (when the user switches notes or toggles mode).
          // This is an accepted v1 limitation — a JotEditor ref API would be
          // needed to push content into a live CodeMirror instance.
          scheduleSave(md);
        }
      },
      getHTML(): string {
        if (!editor || editor.isDestroyed || mode !== 'rich') return '';
        return editor.getHTML();
      },
      getMarkdown(): string {
        return current.current;
      },
      startInlineAssist(action: InlineAction): boolean {
        return openInlineRef.current(action);
      },
    };
    return () => {
      if (handleRef) handleRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editor, mode, handleRef]);

  async function handleCopy() {
    if (!editor || editor.isDestroyed || mode !== 'rich') return;
    const payload = clipboardPayload(editor);
    try {
      const result = await window.gb.clipboard.writeRich({
        html: payload.html,
        text: payload.markdown,
      });
      if (result.ok) {
        toast.success('copied — paste anywhere');
      } else {
        toast.error(`copy failed: ${result.error}`);
      }
    } catch (err) {
      // ipcRenderer.invoke rejects if the channel is gone — never leave an
      // unhandled rejection behind a fire-and-forget void call.
      toast.error(`copy failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  }

  useEffect(() => {
    handleCopyRef.current = () => void handleCopy();
    onWikilinkClickRef.current = onWikilinkClick;
    openInlineRef.current = openInline;
  });

  // Cross-write guard (mirrors JotEditor): if the markdown prop switches
  // while a save is pending, the stale timer would fire with the previous
  // note's content — cancel it and resync the document.
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    lastSaved.current = markdown;
    current.current = markdown;
    if (editor && !editor.isDestroyed && getMarkdown(editor) !== markdown) {
      try {
        // tiptap-markdown overrides setContent to parse markdown strings;
        // emitUpdate=false so the resync never schedules a save.
        clearAiSuggestion(editor);
        setInline(null);
        editor.commands.setContent(markdown, false);
      } catch {
        setMode('source');
      }
    }
    // `editor` deliberately omitted: this effect must run on body switches,
    // not on editor (re)creation.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [markdown]);

  // Unmount cleanup — no save may fire after the component is gone.
  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  function switchMode(next: Mode) {
    if (next === mode) return;
    setStatusPos(null);
    if (next === 'source') {
      setInline(null);
      if (editor && !editor.isDestroyed) clearAiSuggestion(editor);
      if (editor && !editor.isDestroyed) current.current = getMarkdown(editor);
      setMode('source');
      return;
    }
    if (!editor || editor.isDestroyed) return;
    try {
      editor.commands.setContent(current.current, false);
      setMode('rich');
    } catch {
      toast.error('could not parse markdown — staying in source mode');
    }
  }

  return (
    <div
      className="flex h-full flex-col"
      data-testid="rich-markdown-editor"
      data-focus={focus ? 'on' : undefined}
    >
      {mode === 'rich' && editor && !focus && !readOnly && (
        <EditorToolbar
          editor={editor}
          onPhoto={() => setCamOpen(true)}
          onAssist={inlineAssist ? () => void openInline() : undefined}
        />
      )}
      <div className="flex-1 overflow-auto">
        {mode === 'rich' && editor && !readOnly && <TableToolbar editor={editor} />}
        {mode === 'rich' ? (
          <EditorContent
            editor={editor}
            className="gb-prose h-full px-4 py-3 text-14 leading-[1.65] text-ink-0 [&_.ProseMirror]:min-h-full [&_.ProseMirror]:outline-none"
          />
        ) : (
          <JotEditor
            body={current.current}
            debounceMs={debounceMs}
            readOnly={readOnly}
            onSave={(next) => {
              current.current = next;
              lastSaved.current = next;
              onSave(next);
            }}
          />
        )}
      </div>
      <div className="flex flex-shrink-0 items-center gap-2 border-t border-hairline px-3 py-[6px]">
        {mode === 'rich' && (
          <Btn
            variant="ghost"
            size="sm"
            icon={<Lucide name="clipboard-copy" size={12} />}
            onClick={() => void handleCopy()}
          >
            copy formatted
          </Btn>
        )}
        {mode === 'rich' && editor && <ReadAloudControls editor={editor} />}
        <div className="ml-auto flex items-center gap-1 font-mono text-10 text-ink-3">
          <button
            type="button"
            onClick={() => switchMode('rich')}
            className={
              mode === 'rich'
                ? 'rounded-sm bg-vellum px-2 py-[2px] text-ink-0'
                : 'rounded-sm px-2 py-[2px] hover:text-ink-1'
            }
          >
            rich
          </button>
          <button
            type="button"
            onClick={() => switchMode('source')}
            className={
              mode === 'source'
                ? 'rounded-sm bg-vellum px-2 py-[2px] text-ink-0'
                : 'rounded-sm px-2 py-[2px] hover:text-ink-1'
            }
          >
            src
          </button>
        </div>
      </div>
      {mode === 'rich' && editor && statusPos !== null && (
        <StatusPopover key={statusPos} editor={editor} pos={statusPos} onClose={closeStatus} />
      )}
      {diagramSource !== null && <DiagramModal source={diagramSource} onClose={closeDiagram} />}
      {mode === 'rich' && editor && !readOnly && inline && inlineAssist && (
        <InlineAssistPopover
          key={inline.n}
          editor={editor}
          target={inlineAssist.target}
          context={inline.ctx}
          initial={inline.initial}
          keyRef={inlineKeyRef}
          onAccept={acceptInline}
          onClose={closeInline}
        />
      )}
      <WebcamCaptureModal
        open={camOpen && !readOnly}
        onClose={() => setCamOpen(false)}
        onCapture={(file) => {
          if (!editorRef.current) return;
          void insertImageFile(editorRef.current, jotIdRef.current, file)
            .then((path) => onPhotoInserted?.(jotIdRef.current, path))
            .catch((e: Error) => toast.error(`photo insert failed: ${e.message}`));
        }}
      />
      {templateOpen && !readOnly && (
        <TemplateInsertDialog
          onClose={() => setTemplateOpen(false)}
          onInsert={(md) => {
            const ed = editorRef.current;
            if (!ed || ed.isDestroyed) return;
            // tiptap-markdown parses the string as markdown at the cursor;
            // onUpdate then schedules the normal autosave.
            ed.chain().focus().insertContent(md).run();
          }}
        />
      )}
    </div>
  );
}
