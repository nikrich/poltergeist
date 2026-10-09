import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { cancelRender, loadPdf, type PdfHandle } from './pdf';

const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2];
const DEFAULT_ZOOM = 2; // index into ZOOMS → 1.0
const GAP = 16;
const NO_IO_RENDER = 3; // pages rendered when IntersectionObserver is unavailable (jsdom)

interface Loaded {
  pdf: PdfHandle;
  base: { width: number; height: number }; // page 1 at scale 1
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
  const [zoom, setZoom] = useState(DEFAULT_ZOOM);
  const [shown, setShown] = useState<Set<number>>(new Set());
  const [jump, setJump] = useState<string | null>(null);
  const onError = useCallback((e: string) => setError(e), []);

  const numPages = doc?.pdf.numPages ?? 0;
  const scale = ZOOMS[zoom]!;

  useEffect(() => {
    let live = true;
    setDoc(null);
    setPage(1);
    setZoom(DEFAULT_ZOOM);
    setError(null);
    setShown(new Set());
    setJump(null);
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
    if (doc) scroller.current?.focus({ preventScroll: true });
  }, [doc]);

  // Observers: one with a generous margin decides what to render, one on the
  // bare viewport decides which page is "current".
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
    const ratios = new Map<number, number>();
    const currentIO = new IntersectionObserver(
      (entries) => {
        for (const en of entries) ratios.set(num(en.target), en.isIntersecting ? en.intersectionRatio : 0);
        let best = 0;
        let bestRatio = 0;
        for (const [n, r] of ratios) if (r > bestRatio || (r === bestRatio && r > 0 && n < best)) { best = n; bestRatio = r; }
        if (best) setPage(best);
      },
      { root, threshold: [0, 0.1, 0.25, 0.5, 0.75, 1] },
    );
    pageEls.current.forEach((el) => {
      renderIO.observe(el);
      currentIO.observe(el);
    });
    return () => {
      renderIO.disconnect();
      currentIO.disconnect();
    };
  }, [doc]);

  const goTo = useCallback(
    (n: number) => {
      const target = Math.min(Math.max(n, 1), numPages);
      setPage(target);
      pageEls.current.get(target)?.scrollIntoView({ block: 'start' });
    },
    [numPages],
  );

  // Zoom resizes every placeholder: re-render only what is near, and keep the current page in view.
  const firstZoom = useRef(true);
  useLayoutEffect(() => {
    if (firstZoom.current) {
      firstZoom.current = false;
      return;
    }
    if (typeof IntersectionObserver !== 'undefined') setShown(new Set(near.current));
    pageEls.current.get(page)?.scrollIntoView({ block: 'start' });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- only on zoom changes
  }, [zoom]);

  const changeZoom = (fn: (z: number) => number) => setZoom((z) => Math.min(Math.max(fn(z), 0), ZOOMS.length - 1));

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.defaultPrevented || isTyping(e.target) || !doc) return;
    if (e.metaKey || e.ctrlKey) {
      if (e.altKey) return;
      if (e.key === '=' || e.key === '+') changeZoom((z) => z + 1);
      else if (e.key === '-' || e.key === '_') changeZoom((z) => z - 1);
      else if (e.key === '0') setZoom(DEFAULT_ZOOM);
      else return;
      e.preventDefault();
      return;
    }
    if (e.altKey || e.shiftKey) return;
    let target: number | null = null;
    if (e.key === 'ArrowRight' || e.key === 'j') target = page + 1;
    else if (e.key === 'ArrowLeft' || e.key === 'k') target = page - 1;
    else if (e.key === 'Home') target = 1;
    else if (e.key === 'End') target = numPages;
    if (target === null) return;
    e.preventDefault();
    goTo(target);
  };

  if (error) return <div className="p-8 text-13 text-oxblood">couldn&apos;t render this PDF: {error}</div>;

  const w = doc ? doc.base.width * scale : 0;
  const h = doc ? doc.base.height * scale : 0;

  return (
    <div
      ref={scroller}
      tabIndex={0}
      onKeyDown={onKeyDown}
      className="relative min-h-0 flex-1 overflow-auto bg-[radial-gradient(1200px_400px_at_50%_-10%,rgba(197,255,61,.05),transparent_60%)] p-6 outline-none focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-hairline-2"
    >
      {doc && (
        <div className="mx-auto flex w-fit flex-col pb-16" style={{ gap: GAP }}>
          {Array.from({ length: numPages }, (_, i) => i + 1).map((n) => (
            <div
              key={n}
              data-page={n}
              ref={(el) => {
                if (el) pageEls.current.set(n, el);
                else pageEls.current.delete(n);
              }}
              className="rounded-[3px] bg-vellum/40 shadow-[0_20px_50px_rgba(0,0,0,.55)]"
              style={{ width: w, height: h }}
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
              className="w-8 rounded bg-transparent text-center text-ink-0 outline-none ring-1 ring-hairline-2"
            />
          )}
          <span>/ {numPages}</span>
          <button type="button" aria-label="next page" disabled={page >= numPages} onClick={() => goTo(page + 1)} className="disabled:opacity-30">›</button>
          <span className="text-ink-3">|</span>
          <button type="button" aria-label="zoom out" disabled={zoom === 0} onClick={() => changeZoom((z) => z - 1)} className="disabled:opacity-30">−</button>
          <span>{Math.round(scale * 100)}%</span>
          <button type="button" aria-label="zoom in" disabled={zoom === ZOOMS.length - 1} onClick={() => changeZoom((z) => z + 1)} className="disabled:opacity-30">+</button>
        </div>
      )}
    </div>
  );
}
