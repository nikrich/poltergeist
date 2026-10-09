import { useEffect, useRef, useState } from 'react';
import type { DocSummary } from '../../../shared/api-types';
import { docUrl, KIND_META, kindLabel } from './kinds';
import { cancelRender, renderThumb } from './pdf';

const TINT: Record<string, string> = {
  pdf: 'linear-gradient(160deg,#2a1714,var(--bg-vellum))',
  image: 'linear-gradient(160deg,#122029,var(--bg-vellum))',
  docx: 'linear-gradient(160deg,#171a2e,var(--bg-vellum))',
  xlsx: 'linear-gradient(160deg,#16201A,var(--bg-vellum))',
  text: 'linear-gradient(160deg,#1a220c,var(--bg-vellum))',
  opaque: 'var(--bg-fog)',
};

// True once the element has scrolled into view (immediately where IntersectionObserver
// is unavailable, e.g. jsdom), so a grid of PDFs only loads the cards you can see.
function useSeen(ref: React.RefObject<Element | null>): boolean {
  const [seen, setSeen] = useState(() => typeof IntersectionObserver === 'undefined');
  useEffect(() => {
    const el = ref.current;
    if (seen || !el) return;
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        setSeen(true);
        io.disconnect();
      }
    }, { rootMargin: '200px' });
    io.observe(el);
    return () => io.disconnect();
  }, [ref, seen]);
  return seen;
}

function PdfThumb({ doc }: { doc: DocSummary }) {
  const ref = useRef<HTMLCanvasElement>(null);
  const [failed, setFailed] = useState(false);
  const seen = useSeen(ref);
  const url = docUrl(doc.original_path, doc.doc_id);
  useEffect(() => {
    setFailed(false);
    const canvas = ref.current;
    if (!canvas || !seen) return;
    let cancelled = false;
    renderThumb(canvas, url, 160).catch(() => {
      if (!cancelled) setFailed(true);
    });
    return () => {
      cancelled = true;
      cancelRender(canvas);
    };
  }, [url, seen]);
  if (failed) return <TextThumb doc={doc} />;
  return <canvas ref={ref} className="mt-3 w-[62%] self-end rounded-t-[3px] bg-white shadow-[0_-4px_20px_rgba(0,0,0,.3)]" />;
}

function TextThumb({ doc }: { doc: DocSummary }) {
  return (
    <div className="mt-3 h-[88%] w-[62%] self-end overflow-hidden rounded-t-[3px] bg-[#F4F4F0] p-2.5 text-[6.5px] leading-[1.45] text-[#3a3d44]">
      {doc.excerpt || <span className="font-mono text-[9px]" style={{ color: KIND_META[doc.kind].fg }}>{kindLabel(doc)}</span>}
    </div>
  );
}

export function Thumb({ doc }: { doc: DocSummary }) {
  let inner: React.ReactNode;
  if (doc.kind === 'image') {
    inner = <img src={docUrl(doc.original_path, doc.doc_id)} alt="" loading="lazy" className="h-full w-full object-cover" />;
  } else if (doc.kind === 'pdf') {
    inner = <PdfThumb doc={doc} />;
  } else if (doc.kind === 'opaque') {
    inner = <span className="font-mono text-12 text-ink-2">{kindLabel(doc)}</span>;
  } else {
    inner = <TextThumb doc={doc} />;
  }
  return (
    <div className="flex h-[120px] items-center justify-center overflow-hidden" style={{ background: TINT[doc.kind] }}>
      {inner}
    </div>
  );
}
