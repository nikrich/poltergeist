import { Fragment, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Lucide } from '../Lucide';

export interface ToolbarMenuItem {
  key: string;
  label: string;
  icon?: string;
  /** Right-aligned hint (a shortcut). */
  hint?: string;
  /** For radio menus: the current choice. */
  checked?: boolean;
  /** Rows with a different group than the row before get a hairline rule. */
  group?: string;
  /** Extra classes on the label (the text-style menu previews each style). */
  labelClassName?: string;
  onSelect: () => void;
}

interface Props {
  /** aria-label of the trigger and the menu. */
  label: string;
  title?: string;
  trigger: React.ReactNode;
  items: ToolbarMenuItem[];
  radio?: boolean;
  disabled?: boolean;
  /** Classes for the trigger button (width, emphasis). */
  triggerClassName?: string;
}

const GAP = 4;
const EDGE = 8;

/** Viewport position for a floating panel under `anchor`. Fixed positioning
 * keeps the panel out of the toolbar's overflow clipping; the panel stays in
 * the DOM subtree, so outside-click and key handling still see it. */
export function useAnchoredPanel(open: boolean, minWidth: number) {
  const anchorRef = useRef<HTMLElement | null>(null);
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null);
  useLayoutEffect(() => {
    if (!open) {
      setPos(null);
      return;
    }
    const place = () => {
      const r = anchorRef.current?.getBoundingClientRect();
      if (!r) return;
      const maxLeft = window.innerWidth - minWidth - EDGE;
      setPos({ top: r.bottom + GAP, left: Math.max(EDGE, Math.min(r.left, maxLeft)) });
    };
    place();
    window.addEventListener('resize', place);
    return () => window.removeEventListener('resize', place);
  }, [open, minWidth]);
  // Never hide the unplaced first frame: Chromium will not focus a
  // visibility:hidden element, and the open-time focus runs before the
  // re-render that places the panel. That re-render lands before paint,
  // so the unplaced frame is never seen.
  const style: React.CSSProperties = pos
    ? { position: 'fixed', top: pos.top, left: pos.left, minWidth }
    : { position: 'fixed', minWidth };
  return { anchorRef, style };
}

/** Closes on a mousedown outside `root` while `open`. */
export function useOutsideClose(
  open: boolean,
  root: React.RefObject<HTMLElement | null>,
  close: () => void,
) {
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) close();
    };
    document.addEventListener('mousedown', onDown);
    return () => document.removeEventListener('mousedown', onDown);
  }, [open, root, close]);
}

export const PANEL_CLASS =
  'z-40 rounded-md border border-hairline-2 bg-vellum shadow-float';

export const FOCUS_RING =
  'outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-ink-3';

/** Toolbar dropdown. Esc closes it and is preventDefault-ed, so NoteView's
 * Esc-to-close and A4's Esc-to-leave-focus both skip it. */
export function ToolbarMenu({
  label,
  title,
  trigger,
  items,
  radio = false,
  disabled = false,
  triggerClassName = '',
}: Props) {
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const itemRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const { anchorRef, style } = useAnchoredPanel(open, radio ? 220 : 236);
  const closeOutside = useCallback(() => setOpen(false), []);
  useOutsideClose(open, rootRef, closeOutside);

  useEffect(() => {
    if (open) itemRefs.current[active]?.focus();
  }, [open, active]);

  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);

  const closeToTrigger = () => {
    setOpen(false);
    triggerRef.current?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (!open || items.length === 0) return;
    if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      closeToTrigger();
    } else if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((i) => (i + 1) % items.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => (i - 1 + items.length) % items.length);
    } else if (e.key === 'Home') {
      e.preventDefault();
      setActive(0);
    } else if (e.key === 'End') {
      e.preventDefault();
      setActive(items.length - 1);
    } else if (e.key === 'Tab') {
      setOpen(false);
    }
  };

  return (
    <div ref={rootRef} className="relative flex-shrink-0" onKeyDown={onKeyDown}>
      <button
        ref={(el) => {
          triggerRef.current = el;
          anchorRef.current = el;
        }}
        type="button"
        aria-label={label}
        title={title ?? label}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => {
          const checked = radio ? items.findIndex((it) => it.checked) : -1;
          setActive(checked >= 0 ? checked : 0);
          setOpen((o) => !o);
        }}
        className={`flex h-7 items-center gap-[6px] rounded-sm px-2 text-ink-1 transition-colors duration-100 hover:bg-fog hover:text-ink-0 disabled:cursor-default disabled:text-ink-3 disabled:hover:bg-transparent ${FOCUS_RING} ${
          open ? 'bg-fog text-ink-0' : ''
        } ${triggerClassName}`}
      >
        {trigger}
      </button>
      {open && (
        <div
          role="menu"
          aria-label={label}
          style={style}
          className={`${PANEL_CLASS} max-h-[60vh] overflow-y-auto py-1`}
        >
          {items.map((it, i) => {
            const rule = i > 0 && it.group !== undefined && it.group !== items[i - 1]!.group;
            return (
              <Fragment key={it.key}>
                {rule && <div role="separator" className="mx-2 my-1 h-px bg-hairline" />}
                <button
                  ref={(el) => {
                    itemRefs.current[i] = el;
                  }}
                  type="button"
                  role={radio ? 'menuitemradio' : 'menuitem'}
                  aria-checked={radio ? it.checked === true : undefined}
                  tabIndex={i === active ? 0 : -1}
                  onMouseEnter={() => setActive(i)}
                  onClick={() => {
                    setOpen(false);
                    it.onSelect();
                  }}
                  className={`group/row mx-1 flex w-[calc(100%-8px)] items-center gap-[10px] rounded-sm px-2 py-[6px] text-left text-13 outline-none focus:bg-fog focus:text-ink-0 ${
                    it.checked ? 'text-ink-0' : 'text-ink-1'
                  }`}
                >
                  {radio ? (
                    <span className="flex w-[14px] justify-center text-ink-0">
                      {it.checked && <Lucide name="check" size={14} />}
                    </span>
                  ) : (
                    it.icon && <Lucide name={it.icon} size={15} className="text-ink-2 group-focus/row:text-ink-0" />
                  )}
                  <span className={`flex-1 truncate ${it.labelClassName ?? ''}`}>{it.label}</span>
                  {it.hint && (
                    <span className="ml-4 whitespace-nowrap font-mono text-10 text-ink-3">{it.hint}</span>
                  )}
                </button>
              </Fragment>
            );
          })}
        </div>
      )}
    </div>
  );
}
