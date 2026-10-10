import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { sanitizePageTitle } from '../../lib/editor/page-title';

interface Props {
  /** Current title (or the fallback shown when the body owns none). */
  value: string;
  placeholder?: string;
  readOnly?: boolean;
  /** Same debounce as the body autosave. */
  debounceMs?: number;
  /** Called with a sanitised, non-empty, changed title. */
  onCommit: (title: string) => void;
  /** Enter: after committing, move into the page. */
  onEnter?: () => void;
}

function nativeFieldSizing(): boolean {
  return typeof CSS !== 'undefined' && CSS.supports?.('field-sizing', 'content') === true;
}

function fitHeight(el: HTMLTextAreaElement): void {
  el.style.height = 'auto';
  el.style.height = `${el.scrollHeight}px`;
}

/** The page's big editable title. Single line (pasted breaks become spaces),
 * wraps visually; saves on the body's debounce and at once on blur/Enter. */
export function PageTitle({
  value,
  placeholder = 'Untitled',
  readOnly = false,
  debounceMs = 1000,
  onCommit,
  onEnter,
}: Props) {
  const [draft, setDraft] = useState(value);
  const committed = useRef(value);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const ref = useRef<HTMLTextAreaElement>(null);

  // Grow with the text so long titles wrap like Confluence's. CSS
  // `field-sizing: content` does it natively (Chromium 123+, Electron 32 has
  // 128) and follows every width change. Without it, measure in JS and
  // re-measure whenever the width changes (page width, focus mode, window,
  // sidebars) or the display font finishes loading.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || nativeFieldSizing()) return;
    fitHeight(el);
  }, [draft]);
  useEffect(() => {
    const el = ref.current;
    if (!el || nativeFieldSizing()) return;
    let cancelled = false;
    let lastWidth = el.clientWidth;
    const ro =
      typeof ResizeObserver === 'undefined'
        ? null
        : new ResizeObserver(() => {
            // Only width changes reflow the text; our own height writes
            // must not loop back here.
            if (el.clientWidth === lastWidth) return;
            lastWidth = el.clientWidth;
            fitHeight(el);
          });
    ro?.observe(el);
    void document.fonts?.ready.then(() => {
      if (!cancelled) fitHeight(el);
    });
    return () => {
      cancelled = true;
      ro?.disconnect();
    };
  }, []);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const cancelTimer = () => {
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  };

  const commit = (raw: string): void => {
    cancelTimer();
    const next = sanitizePageTitle(raw);
    if (next === '' || next === committed.current) return;
    committed.current = next;
    onCommit(next);
  };

  return (
    <textarea
      ref={ref}
      aria-label="page title"
      rows={1}
      value={draft}
      placeholder={placeholder}
      readOnly={readOnly}
      spellCheck
      className="gb-page-title"
      onChange={(e) => {
        const next = e.target.value.replace(/\r?\n/g, ' ');
        setDraft(next);
        cancelTimer();
        timer.current = setTimeout(() => commit(next), debounceMs);
      }}
      onBlur={() => {
        commit(draft);
        // Show what was saved: collapsed whitespace, the 200-char cap, or the
        // previous title when the field was emptied.
        setDraft(committed.current);
      }}
      onKeyDown={(e) => {
        if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
          e.preventDefault();
          commit(draft);
          onEnter?.();
          return;
        }
        // Only a dirty title owns Esc; a clean one lets the viewer close.
        if (e.key === 'Escape' && draft !== committed.current) {
          e.preventDefault();
          cancelTimer();
          setDraft(committed.current);
        }
      }}
    />
  );
}
