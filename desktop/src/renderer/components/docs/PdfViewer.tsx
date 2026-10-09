import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { Lucide } from '../Lucide';
import { cancelRender, loadPdf, type PdfHandle } from './pdf';

const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2];
const PAD_X = 48; // scroller p-6, both sides
const PAD_Y = 48;

type ZoomMode = 'fit-width' | 'fit-page' | 'manual';

function fitScaleFor(el: HTMLElement, mode: ZoomMode, base: { width: number; height: number }): number | null {
  if (mode === 'manual' || !el.clientWidth || !base.width || !base.height) return null;
  const byWidth = (el.clientWidth - PAD_X) / base.width;
  const v = mode === 'fit-width' || !el.clientHeight ? byWidth : Math.min(byWidth, (el.clientHeight - PAD_Y) / base.height);
  return v > 0 ? Math.round(v * 1000) / 1000 : null;
}
const GAP = 16;
const NO_IO_RENDER = 3; // pages rendered when IntersectionObserver is unavailable (jsdom)

interface Size { width: number; height: number }
interface Loaded {
  pdf: PdfHandle;
  base: Size; // page 1 at scale 1: the default until a page's own size is known
}

function PageCanvas({ pdf, page, scale, onError }: { pdf: PdfHandle; page: number; scale: number; onError: (e: string) => void }) {
  const ref = useRef<HTMLCanvasElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    pdf.renderPage(el, page, scale).catch((e: unknown) => onError(String(e)));
    return () => {
      cancelRender(el);
    };
  }, [pdf, page, scale, onError]);
  return <canvas ref={ref} className="block" />;
}

const isTyping = (t: EventTarget | null): boolean => {
  const el = t as HTMLElement | null;
  return !!el && (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName) || el.isContentEditable);
};

export function PdfViewer({ url }: { url: string }) {
  const scroller = useRef<HTMLDivElement>(null);
  const pageEls = useRef(new Map<number, HTMLDivElement>());
  const near = useRef(new Set<number>());
  const [doc, setDoc] = useState<Loaded | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [mode, setMode] = useState<ZoomMode>('fit-width');
  const [fitScale, setFitScale] = useState<number | null>(null);
  const [manualScale, setManualScale] = useState(1);
  const [shown, setShown] = useState<Set<number>>(new Set());
  const [sizes, setSizes] = useState<Map<number, Size>>(new Map()); // per page, at scale 1
  const requested = useRef(new Set<number>());
  const prevScale = useRef<number | null>(null);
  const fitInit = useRef(false);
  const [jump, setJump] = useState<string | null>(null);
  const onError = useCallback((e: string) => setError(e), []);

  const numPages = doc?.pdf.numPages ?? 0;
  const scale = mode === 'manual' ? manualScale : (fitScale ?? 1);
  const scaleRef = useRef(scale);
  scaleRef.current = scale;

  useEffect(() => {
    let live = true;
    setDoc(null);
    setPage(1);
    setMode('fit-width');
    setFitScale(null);
    setManualScale(1);
    setError(null);
    setShown(new Set());
    setJump(null);
    setSizes(new Map());
    requested.current = new Set();
    prevScale.current = null;
    fitInit.current = false;
    near.current = new Set();
    loadPdf(url)
      .then(async (pdf) => {
        const base = await pdf.pageSize(1, 1);
        if (live) setDoc({ pdf, base });
      })
      .catch((e: unknown) => live && setError(String(e)));
    return () => {
      live = false; // PageCanvas cleanups cancel their renders as the pages unmount
    };
  }, [url]);

  // Focus the column so keyboard navigation works as soon as a PDF opens.
  useEffect(() => {
    const el = scroller.current;
    if (!doc || !el) return;
    const active = document.activeElement;
    if (!active || active === document.body || el.parentElement?.contains(active)) el.focus({ preventScroll: true });
  }, [doc]);

  // Real page sizes, fetched lazily for pages entering the render window.
  useEffect(() => {
    if (!doc) return;
    const reqs = requested.current;
    for (const n of shown) {
      if (reqs.has(n)) continue;
      reqs.add(n);
      doc.pdf
        .pageSize(n, 1)
        .then((sz) => {
          if (requested.current === reqs) setSizes((prev) => new Map(prev).set(n, sz));
        })
        .catch(() => reqs.delete(n));
    }
  }, [doc, shown]);

  // A generous-margin observer decides which pages to render.
  useEffect(() => {
    if (!doc) return;
    if (typeof IntersectionObserver === 'undefined') {
      setShown(new Set(Array.from({ length: Math.min(NO_IO_RENDER, doc.pdf.numPages) }, (_, i) => i + 1)));
      return;
    }
    const root = scroller.current;
    const num = (t: Element) => Number((t as HTMLElement).dataset.page);
    const renderIO = new IntersectionObserver(
      (entries) => {
        for (const en of entries) {
          if (en.isIntersecting) near.current.add(num(en.target));
          else near.current.delete(num(en.target));
        }
        setShown((prev) => {
          const next = new Set(prev);
          near.current.forEach((n) => next.add(n));
          return next.size === prev.size ? prev : next;
        });
      },
      { root, rootMargin: `${root?.clientHeight || 800}px 0px` },
    );
    pageEls.current.forEach((el) => {
      renderIO.observe(el);
    });
    return () => {
      renderIO.disconnect();
    };
  }, [doc]);

  // Current page from scroll position: the last page whose top is at/above the
  // viewport top (small offset), or the last page when scrolled to the bottom.
  const currentFromScroll = useCallback((): number | null => {
    const el = scroller.current;
    if (!el || el.clientHeight === 0) return null; // no layout
    if (el.scrollHeight > el.clientHeight && el.scrollTop + el.clientHeight >= el.scrollHeight - 1) return numPages;
    const line = el.scrollTop + 8;
    let cur = 1;
    for (let n = 1; n <= numPages; n++) {
      const top = pageEls.current.get(n)?.offsetTop;
      if (top !== undefined && top <= line) cur = n;
    }
    return cur;
  }, [numPages]);

  const raf = useRef<number | null>(null);
  const onScroll = () => {
    if (raf.current !== null) return;
    raf.current = requestAnimationFrame(() => {
      raf.current = null;
      const c = currentFromScroll();
      if (c !== null) setPage(c);
    });
  };
  useEffect(() => () => {
    if (raf.current !== null) cancelAnimationFrame(raf.current);
  }, []);

  const goTo = useCallback(
    (n: number) => {
      const target = Math.min(Math.max(n, 1), numPages);
      setPage(target);
      pageEls.current.get(target)?.scrollIntoView({ block: 'start' });
    },
    [numPages],
  );

  // A scale change resizes every placeholder: keep the current page in view. Not on a url reset.
  useLayoutEffect(() => {
    if (scale === prevScale.current) return;
    prevScale.current = scale;
    pageEls.current.get(page)?.scrollIntoView({ block: 'start' });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only on scale changes
  }, [scale]);

  // Shrink the render window in the same update as a scale change, so pages that
  // scrolled away don't start renders at the new scale.
  const shrinkWindow = () => {
    if (typeof IntersectionObserver !== 'undefined') setShown(new Set(near.current));
  };

  const setManual = (v: number) => {
    setManualScale(v);
    setMode('manual');
    shrinkWindow();
  };
  const stepZoom = (dir: 1 | -1) => {
    const cur = scaleRef.current;
    const next = dir > 0 ? ZOOMS.find((z) => z > cur + 0.001) : [...ZOOMS].reverse().find((z) => z < cur - 0.001);
    if (next !== undefined) setManual(next);
  };
  const fit = (m: 'fit-width' | 'fit-page') => {
    setMode(m);
    shrinkWindow();
  };

  // In a fit mode, the scale follows the scroller (window resize, panes collapsing).
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!doc || !el || mode === 'manual') return;
    const apply = () => {
      const v = fitScaleFor(el, mode, doc.base);
      if (v === null) return;
      if (!fitInit.current) {
        fitInit.current = true; // first fit on open: no scroll-restore
        prevScale.current = v;
      }
      if (v !== scaleRef.current) {
        scaleRef.current = v;
        setFitScale(v);
        shrinkWindow();
      }
    };
    apply();
    if (typeof ResizeObserver === 'undefined') return;
    let pending: number | null = null;
    const ro = new ResizeObserver(() => {
      if (pending !== null) return;
      pending = requestAnimationFrame(() => {
        pending = null;
        apply();
      });
    });
    ro.observe(el);
    return () => {
      ro.disconnect();
      if (pending !== null) cancelAnimationFrame(pending);
    };
  }, [doc, mode]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.defaultPrevented || isTyping(e.target) || !doc) return;
    // Modified keys stay with the app (⌘= etc. are window zoom).
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === '=' || e.key === '+') stepZoom(1);
    else if (e.key === '-' || e.key === '_') stepZoom(-1);
    else if (e.key === '0') setManual(1);
    else if (e.key === 'w') fit('fit-width');
    else if (e.key === 'f') fit('fit-page');
    else if (!e.shiftKey && ['ArrowRight', 'j', 'ArrowLeft', 'k', 'Home', 'End'].includes(e.key)) {
      goTo(
        e.key === 'ArrowRight' || e.key === 'j' ? page + 1
          : e.key === 'ArrowLeft' || e.key === 'k' ? page - 1
            : e.key === 'Home' ? 1 : numPages,
      );
    } else return;
    e.preventDefault();
  };

  if (error) return <div className="p-8 text-13 text-oxblood">couldn&apos;t render this PDF: {error}</div>;


  return (
    <div
      ref={scroller}
      tabIndex={0}
      onKeyDown={onKeyDown}
      onScroll={onScroll}
      className="relative min-h-0 flex-1 overflow-auto bg-[radial-gradient(1200px_400px_at_50%_-10%,rgba(197,255,61,.05),transparent_60%)] p-6 outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-hairline-2"
    >
      {doc && (
        <div className="mx-auto flex w-fit flex-col items-center pb-16" style={{ gap: GAP }}>
          {Array.from({ length: numPages }, (_, i) => i + 1).map((n) => (
            <div
              key={n}
              data-page={n}
              ref={(el) => {
                if (el) pageEls.current.set(n, el);
                else pageEls.current.delete(n);
              }}
              className="rounded-[3px] bg-vellum/40 shadow-[0_20px_50px_rgba(0,0,0,.55)]"
              style={{ width: (sizes.get(n) ?? doc.base).width * scale, height: (sizes.get(n) ?? doc.base).height * scale }}
            >
              {shown.has(n) && <PageCanvas pdf={doc.pdf} page={n} scale={scale} onError={onError} />}
            </div>
          ))}
        </div>
      )}
      {doc && (
        <div className="fixed bottom-6 left-1/2 flex -translate-x-1/2 items-center gap-3.5 rounded-full border border-hairline-2 bg-vellum/90 px-3.5 py-1.5 font-mono text-11 text-ink-1 shadow-[0_10px_30px_rgba(0,0,0,.5)] backdrop-blur">
          <button type="button" aria-label="previous page" disabled={page <= 1} onClick={() => goTo(page - 1)} className="disabled:opacity-30">‹</button>
          {jump === null ? (
            <button type="button" aria-label="go to page" onClick={() => setJump(String(page))} className="font-medium text-ink-0">{page}</button>
          ) : (
            <input
              autoFocus
              aria-label="page number"
              value={jump}
              inputMode="numeric"
              onChange={(e) => setJump(e.target.value.replace(/\D/g, ''))}
              onBlur={() => setJump(null)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  const n = parseInt(jump, 10);
                  if (n) goTo(n);
                  setJump(null);
                  scroller.current?.focus({ preventScroll: true });
                } else if (e.key === 'Escape') {
                  e.stopPropagation();
                  setJump(null);
                  scroller.current?.focus({ preventScroll: true });
                }
              }}
              className="w-12 rounded bg-transparent text-center text-ink-0 outline-none ring-1 ring-hairline-2"
            />
          )}
          <span>/ {numPages}</span>
          <button type="button" aria-label="next page" disabled={page >= numPages} onClick={() => goTo(page + 1)} className="disabled:opacity-30">›</button>
          <span className="text-ink-3">|</span>
          <button type="button" aria-label="zoom out" disabled={scale <= ZOOMS[0]! + 0.001} onClick={() => stepZoom(-1)} className="disabled:opacity-30">−</button>
          <span>{Math.round(scale * 100)}%</span>
          <button type="button" aria-label="zoom in" disabled={scale >= ZOOMS[ZOOMS.length - 1]! - 0.001} onClick={() => stepZoom(1)} className="disabled:opacity-30">+</button>
          <button type="button" aria-label="fit width" aria-pressed={mode === 'fit-width'} onClick={() => fit('fit-width')} className={mode === 'fit-width' ? 'text-neon' : 'text-ink-2'}>
            <Lucide name="move-horizontal" size={14} />
          </button>
          <button type="button" aria-label="fit page" aria-pressed={mode === 'fit-page'} onClick={() => fit('fit-page')} className={mode === 'fit-page' ? 'text-neon' : 'text-ink-2'}>
            <Lucide name="scan" size={14} />
          </button>
        </div>
      )}
    </div>
  );
}
