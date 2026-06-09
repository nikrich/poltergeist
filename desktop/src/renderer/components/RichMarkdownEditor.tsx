import { useEffect, useRef, useState } from 'react';
import { Editor } from '@tiptap/core';
import { EditorContent, useEditor } from '@tiptap/react';
import { buildEditorExtensions } from '../lib/editor/extensions';
import { getMarkdown } from '../lib/editor/markdown';
import { toast } from '../stores/toast';
import { JotEditor } from './JotEditor';

interface Props {
  markdown: string;
  onSave: (markdown: string) => void;
  readOnly?: boolean;
  /** Autosave debounce in ms. Defaults to 1000. */
  debounceMs?: number;
  /** Called once when the TipTap Editor instance is created; useful for tests. */
  onEditorReady?: (editor: Editor) => void;
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
}: Props) {
  // Evaluated once per mount; parents remount per note via key={...}.
  const [parseFailed] = useState(() => !parsesAsRich(markdown));
  const [mode, setMode] = useState<Mode>(parseFailed ? 'source' : 'rich');

  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSaved = useRef(markdown);
  // Latest content from either mode — handed over when toggling so no
  // keystrokes are lost.
  const current = useRef(markdown);

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
    onUpdate: ({ editor: updated }) => {
      scheduleSave(getMarkdown(updated));
    },
  });

  // Call onEditorReady via useEffect so it fires synchronously inside React's
  // act() in tests. TipTap fires onCreate via window.setTimeout(0), which with
  // fake timers would require advancing the clock — useEffect avoids that.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (editor) onEditorReady?.(editor);
  }, [editor]);

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
