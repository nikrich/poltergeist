import { useEffect, useRef, useState } from 'react';
import { Editor } from '@tiptap/core';
import { EditorContent, useEditor } from '@tiptap/react';
import { buildEditorExtensions } from '../lib/editor/extensions';
import { clipboardPayload, getMarkdown, restoreWikilinks } from '../lib/editor/markdown';
import { toast } from '../stores/toast';
import { Btn } from './Btn';
import { JotEditor } from './JotEditor';
import { Lucide } from './Lucide';

export interface EditorHandle {
  /** Markdown for the current selection; '' when collapsed. */
  getSelectionMarkdown: () => string;
  /** Replace current selection (or whole doc when target='doc') with markdown. */
  replaceWith: (markdown: string, target: 'selection' | 'doc') => void;
  /** Full document as HTML (for PDF export); '' in source mode. */
  getHTML: () => string;
  /** Full document as markdown. */
  getMarkdown: () => string;
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

interface Props {
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
}: Props) {
  // Evaluated once per mount; parents remount per note via key={...}.
  const [parseFailed] = useState(() => !parsesAsRich(markdown));
  const [mode, setMode] = useState<Mode>(parseFailed ? 'source' : 'rich');

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
    if (editor) onEditorReady?.(editor);
  }, [editor]);
  /* eslint-enable react-hooks/exhaustive-deps */

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
        const { from, to, empty } = editor.state.selection;
        if (empty) return '';
        // v1: tiptap-markdown's serializer cannot operate on a partial range
        // without building a top-level doc node from the slice — use the
        // same slice→doc pattern as clipboardPayload (markdown.ts) for rich
        // content, falling back to plain text when the slice cannot form a doc.
        const slice = editor.state.selection.content();
        const docNode = editor.schema.topNodeType.createAndFill(null, slice.content);
        if (docNode) {
          const storage = editor.storage.markdown as {
            serializer: { serialize(content: unknown): string };
          };
          return restoreWikilinks(storage.serializer.serialize(docNode));
        }
        // Fallback: plain-text extraction (acceptable for v1 — no rich formatting).
        return editor.state.doc.textBetween(from, to, '\n');
      },
      replaceWith(md: string, target: 'selection' | 'doc'): void {
        if (mode === 'rich' && editor && !editor.isDestroyed) {
          if (target === 'selection') {
            // insertContent with a markdown string: tiptap-markdown's
            // transformPastedText:true makes setContent work, but insertContent
            // takes HTML/JSON — use setContent on a temporary doc is too
            // destructive.  Instead, delete the selection and use
            // editor.commands.setContent for the full replacement path, or for
            // selection-only replacement we use the same mechanism as
            // setContent but scoped:  insert the markdown as-is (tiptap-markdown
            // serialises back so the round-trip is preserved at next read).
            // The simplest reliable path for v1: focus, replace with insertContent
            // which accepts strings interpreted as HTML by default.  The sidecar
            // already returns proper markdown — convert to HTML via a headless
            // parse to preserve formatting.
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
    if (next === 'source') {
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
    <div className="flex h-full flex-col" data-testid="rich-markdown-editor">
      <div className="flex-1 overflow-auto">
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
    </div>
  );
}
