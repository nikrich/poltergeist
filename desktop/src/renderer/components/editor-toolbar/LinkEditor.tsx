import { useCallback, useRef, useState } from 'react';
import type { Editor } from '@tiptap/core';
import { applyLink, normalizeLinkHref } from '../../lib/editor/toolbar-actions';
import { Lucide } from '../Lucide';
import { FOCUS_RING, PANEL_CLASS, useAnchoredPanel, useOutsideClose } from './ToolbarMenu';

/** Link button + inline address form (Electron has no window.prompt).
 * No shortcut: ⌘K is the Today search. */
export function LinkEditor({ editor }: { editor: Editor }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState('');
  const [error, setError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const { anchorRef, style } = useAnchoredPanel(open, 320);
  const dismiss = useCallback(() => setOpen(false), []);
  useOutsideClose(open, rootRef, dismiss);
  const active = editor.isActive('link');

  const show = () => {
    setValue((editor.getAttributes('link').href as string | undefined) ?? '');
    setError(null);
    setOpen(true);
  };
  const close = () => {
    setOpen(false);
    editor.commands.focus();
  };
  const apply = () => {
    const r = normalizeLinkHref(value);
    if (!r.ok) {
      setError(r.error);
      return;
    }
    applyLink(editor, r.href);
    setOpen(false);
  };

  return (
    <div ref={rootRef} className="relative flex-shrink-0">
      <button
        ref={(el) => {
          anchorRef.current = el;
        }}
        type="button"
        aria-label="link"
        title="Link"
        aria-pressed={active}
        aria-expanded={open}
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => (open ? setOpen(false) : show())}
        className={`flex h-7 w-7 items-center justify-center rounded-sm transition-colors duration-100 hover:bg-fog hover:text-ink-0 ${FOCUS_RING} ${
          active || open ? 'bg-fog text-ink-0' : 'text-ink-2'
        }`}
      >
        <Lucide name="link" size={14} />
      </button>
      {open && (
        <form
          role="dialog"
          aria-label="edit link"
          style={style}
          onSubmit={(e) => {
            e.preventDefault();
            apply();
          }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              e.preventDefault();
              e.stopPropagation();
              close();
            }
          }}
          className={`${PANEL_CLASS} p-2`}
        >
          <div
            className={`flex items-center gap-2 rounded-sm border bg-paper px-2 ${
              error ? 'border-oxblood' : 'border-hairline-2 focus-within:border-hairline-3'
            }`}
          >
            <Lucide name="link" size={13} className="text-ink-3" />
            <input
              autoFocus
              aria-label="link address"
              aria-invalid={error !== null}
              value={value}
              placeholder="Paste or type a link"
              spellCheck={false}
              onChange={(e) => {
                setValue(e.target.value);
                setError(null);
              }}
              className="h-8 min-w-0 flex-1 bg-transparent text-13 text-ink-0 outline-none placeholder:text-ink-3"
            />
          </div>
          {error && (
            <div role="alert" className="mt-[6px] px-[2px] text-11 text-oxblood">
              {error}
            </div>
          )}
          <div className="mt-2 flex items-center justify-end gap-1">
            {active && (
              <button
                type="button"
                onClick={() => {
                  applyLink(editor, null);
                  setOpen(false);
                }}
                className={`mr-auto flex items-center gap-[6px] rounded-sm px-2 py-1 text-12 text-ink-2 hover:bg-fog hover:text-ink-0 ${FOCUS_RING}`}
              >
                <Lucide name="unlink" size={12} />
                Remove link
              </button>
            )}
            <button
              type="submit"
              className={`rounded-sm bg-fog px-3 py-1 text-12 text-ink-0 hover:bg-hairline-2 ${FOCUS_RING}`}
            >
              Apply
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
