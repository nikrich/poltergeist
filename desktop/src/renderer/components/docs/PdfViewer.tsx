import { useEffect, useRef, useState } from 'react';
import { cancelRender, loadPdf, type PdfHandle } from './pdf';

const ZOOMS = [0.5, 0.75, 1, 1.25, 1.5, 2];

export function PdfViewer({ url }: { url: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [pdf, setPdf] = useState<PdfHandle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [zoom, setZoom] = useState(2); // index into ZOOMS → 1.0

  useEffect(() => {
    let live = true;
    setPdf(null);
    setPage(1);
    loadPdf(url).then((h) => live && setPdf(h)).catch((e: unknown) => live && setError(String(e)));
    return () => {
      live = false;
    };
  }, [url]);

  useEffect(() => {
    if (pdf && canvas.current) pdf.renderPage(canvas.current, page, ZOOMS[zoom]!).catch((e: unknown) => setError(String(e)));
  }, [pdf, page, zoom]);

  useEffect(() => {
    const el = canvas.current;
    return () => {
      if (el) cancelRender(el);
    };
  }, []);

  if (error) return <div className="p-8 text-13 text-oxblood">couldn&apos;t render this PDF: {error}</div>;

  return (
    <div className="relative flex min-h-0 flex-1 justify-center overflow-auto bg-[radial-gradient(1200px_400px_at_50%_-10%,rgba(197,255,61,.05),transparent_60%)] p-6">
      <canvas ref={canvas} className="h-fit rounded-[3px] shadow-[0_20px_50px_rgba(0,0,0,.55)]" />
      {pdf && (
        <div className="fixed bottom-6 left-1/2 flex -translate-x-1/2 items-center gap-3.5 rounded-full border border-hairline-2 bg-vellum/90 px-3.5 py-1.5 font-mono text-11 text-ink-1 shadow-[0_10px_30px_rgba(0,0,0,.5)] backdrop-blur">
          <button type="button" aria-label="previous page" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="disabled:opacity-30">‹</button>
          <b className="font-medium text-ink-0">{page}</b>
          <span>/ {pdf.numPages}</span>
          <button type="button" aria-label="next page" disabled={page >= pdf.numPages} onClick={() => setPage((p) => p + 1)} className="disabled:opacity-30">›</button>
          <span className="text-ink-3">|</span>
          <button type="button" aria-label="zoom out" disabled={zoom === 0} onClick={() => setZoom((z) => z - 1)} className="disabled:opacity-30">−</button>
          <span>{Math.round(ZOOMS[zoom]! * 100)}%</span>
          <button type="button" aria-label="zoom in" disabled={zoom === ZOOMS.length - 1} onClick={() => setZoom((z) => z + 1)} className="disabled:opacity-30">+</button>
        </div>
      )}
    </div>
  );
}
