import { useEffect, useRef, useState } from 'react';
import CodeMirror from '@uiw/react-codemirror';
import type { EditorView } from '@codemirror/view';
import { markdown } from '@codemirror/lang-markdown';

interface Props {
  body: string;
  onSave: (body: string) => void;
  /** Autosave debounce in ms. Defaults to 1000. */
  debounceMs?: number;
  /** Called once when the CodeMirror EditorView is created; useful for tests. */
  onCreateEditor?: (view: EditorView) => void;
}

export function JotEditor({ body, onSave, debounceMs = 1000, onCreateEditor }: Props) {
  const [value, setValue] = useState(body);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const lastSaved = useRef(body);

  // Reset state when the editor switches to a different jot. Also cancel any
  // pending save from the previous jot — otherwise the timer would fire with
  // the old jot's content, compare against the NEW jot's lastSaved, and call
  // onSave with the wrong body (cross-write/data-loss).
  useEffect(() => {
    if (timer.current) clearTimeout(timer.current);
    setValue(body);
    lastSaved.current = body;
  }, [body]);

  // Clear any pending save timer on unmount to prevent onSave firing after
  // the component is gone (deliberate improvement over the plan sketch which
  // omits this cleanup).
  useEffect(() => {
    return () => {
      if (timer.current) {
        clearTimeout(timer.current);
      }
    };
  }, []);

  function scheduleSave(next: string) {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      if (next !== lastSaved.current) {
        // Deliberate trade-off: lastSaved advances even if the caller's save
        // fails (no retry; acceptable for debounced autosave).
        lastSaved.current = next;
        onSave(next);
      }
    }, debounceMs);
  }

  return (
    <CodeMirror
      value={value}
      extensions={[markdown()]}
      basicSetup={{ lineNumbers: false, foldGutter: false }}
      onChange={(next) => {
        setValue(next);
        scheduleSave(next);
      }}
      onCreateEditor={onCreateEditor}
      theme="dark"
      className="h-full text-13"
    />
  );
}
