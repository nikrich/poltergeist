import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Lucide } from '../Lucide';
import { renderMermaid, type MermaidResult } from '../../lib/editor/mermaid-render';
import { sanitizedDiagramFragment } from '../../lib/editor/svg-sanitize';
import { boardToMermaid } from './board-mermaid';
import type { BoardModel } from '../../../shared/design-types';

interface Props {
  model: BoardModel;
}

const MIN_ZOOM = 0.25;
const MAX_ZOOM = 4;
const MAX_FIT = 2; // "fit" may enlarge a small diagram, but not absurdly
const STEP = 1.25;
const PAD = 32; // the viewport's p-4, both sides

const clamp = (z: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));

/** The diagram's own size, from mermaid's viewBox. */
function naturalSize(svg: SVGSVGElement): { w: number; h: number } | null {
  const [, , w = 0, h = 0] = (svg.getAttribute('viewBox') ?? '').trim().split(/[\s,]+/).map(Number);
  return w > 0 && h > 0 ? { w, h } : null;
}

/** The board as an architecture flowchart (contexts as subgraphs), zoomable
 *  with the corner controls, ⌘/Ctrl + scroll or a trackpad pinch, and
 *  draggable to pan. Opens fitted to the viewport and keeps re-fitting as the
 *  board grows until the user picks a zoom of their own. */
export function ArchitectureView({ model }: Props) {
  const source = useMemo(() => boardToMermaid(model), [model]);
  const [result, setResult] = useState<MermaidResult | null>(null);
  const [zoom, setZoom] = useState(1);
  const [fitted, setFitted] = useState(true);
  const viewport = useRef<HTMLDivElement>(null);
  const svgHost = useRef<HTMLDivElement>(null);
  // Content point to keep under the cursor across a wheel zoom.
  const anchor = useRef<{ x: number; y: number; ratio: number } | null>(null);

  useEffect(() => {
    let live = true;
    void renderMermaid(source).then((r) => {
      if (live) setResult(r);
    });
    return () => {
      live = false;
    };
  }, [source]);

  const svg = () => svgHost.current?.querySelector('svg') ?? null;

  const fitZoom = useCallback((): number | null => {
    const el = svg();
    const vp = viewport.current;
    const size = el && naturalSize(el);
    if (!el || !vp || !size) return null;
    // Measure the viewport without the diagram propping it open.
    el.style.display = 'none';
    const aw = vp.clientWidth - PAD;
    const ah = vp.clientHeight - PAD;
    el.style.display = '';
    if (aw <= 0) return null;
    const scale = Math.min(aw / size.w, ah > 0 ? ah / size.h : Infinity, MAX_FIT);
    return clamp(scale);
  }, []);

  // Sanitised in an inert template before it reaches the live DOM.
  useLayoutEffect(() => {
    if (result?.ok !== true) return;
    svgHost.current?.replaceChildren(sanitizedDiagramFragment(result.svg));
    if (fitted) {
      const z = fitZoom();
      if (z !== null) setZoom(z);
    }
    // Re-fit only for a new diagram, not when `fitted` flips.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, fitZoom]);

  // Size the svg from its viewBox; mermaid's width=100%/max-width would
  // otherwise pin it to the container.
  useLayoutEffect(() => {
    const el = svg();
    const size = el && naturalSize(el);
    if (!el || !size) return;
    el.style.maxWidth = 'none';
    el.style.width = `${size.w * zoom}px`;
    el.style.height = `${size.h * zoom}px`;
    const a = anchor.current;
    const vp = viewport.current;
    if (a && vp) {
      vp.scrollLeft = a.x * a.ratio - (a.x - vp.scrollLeft);
      vp.scrollTop = a.y * a.ratio - (a.y - vp.scrollTop);
    }
    anchor.current = null;
  }, [zoom, result]);

  const zoomTo = useCallback((z: number) => {
    setFitted(false);
    setZoom(clamp(z));
  }, []);

  const fit = () => {
    setFitted(true);
    const z = fitZoom();
    if (z !== null) setZoom(z);
  };

  // React's onWheel is passive, so preventDefault (stopping the page scroll
  // or Electron's own pinch-zoom) needs a native listener.
  useEffect(() => {
    const vp = viewport.current;
    if (!vp) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return; // a trackpad pinch arrives as ctrl+wheel
      e.preventDefault();
      const delta = Math.max(-50, Math.min(50, e.deltaY));
      setFitted(false);
      setZoom((z) => {
        const next = clamp(z * Math.exp(-delta * 0.005));
        const rect = vp.getBoundingClientRect();
        const ox = e.clientX - rect.left;
        const oy = e.clientY - rect.top;
        anchor.current = { x: vp.scrollLeft + ox, y: vp.scrollTop + oy, ratio: next / z };
        return next;
      });
    };
    vp.addEventListener('wheel', onWheel, { passive: false });
    return () => vp.removeEventListener('wheel', onWheel);
  }, [result]);

  // Drag to pan.
  const drag = useRef<{ x: number; y: number; left: number; top: number } | null>(null);
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return;
    const vp = e.currentTarget;
    drag.current = { x: e.clientX, y: e.clientY, left: vp.scrollLeft, top: vp.scrollTop };
    vp.setPointerCapture?.(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const d = drag.current;
    if (!d) return;
    e.currentTarget.scrollLeft = d.left - (e.clientX - d.x);
    e.currentTarget.scrollTop = d.top - (e.clientY - d.y);
  };
  const endDrag = () => {
    drag.current = null;
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === '+' || e.key === '=') zoomTo(zoom * STEP);
    else if (e.key === '-') zoomTo(zoom / STEP);
    else if (e.key === '0') zoomTo(1);
    else return;
    e.preventDefault();
  };

  if (result?.ok === false) {
    return (
      <div className="p-4 text-12 text-ink-2">
        Couldn&apos;t draw the architecture view: {result.error}
      </div>
    );
  }
  return (
    <div className="flex h-full min-h-[240px] flex-col">
      {result?.ok === true && (
        <div className="mb-2 flex items-center justify-end gap-[2px]">
          <ZoomButton label="Zoom out" onClick={() => zoomTo(zoom / STEP)}>
            <Lucide name="zoom-out" size={13} />
          </ZoomButton>
          <ZoomButton label="Actual size (100%)" onClick={() => zoomTo(1)} wide>
            {Math.round(zoom * 100)}%
          </ZoomButton>
          <ZoomButton label="Zoom in" onClick={() => zoomTo(zoom * STEP)}>
            <Lucide name="zoom-in" size={13} />
          </ZoomButton>
          <ZoomButton label="Fit to view" onClick={fit} pressed={fitted}>
            <Lucide name="maximize" size={13} />
          </ZoomButton>
        </div>
      )}
      <div
        ref={viewport}
        data-testid="architecture-viewport"
        tabIndex={0}
        onKeyDown={onKeyDown}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        className="min-h-0 flex-1 cursor-grab select-none overflow-auto rounded-md border border-hairline bg-paper p-4 outline-none active:cursor-grabbing"
      >
        {result === null && <div className="font-mono text-11 text-ink-3">Drawing…</div>}
        <div ref={svgHost} aria-label="Architecture diagram" className="w-max" />
      </div>
    </div>
  );
}

function ZoomButton({
  label,
  onClick,
  pressed,
  wide,
  children,
}: {
  label: string;
  onClick: () => void;
  pressed?: boolean;
  wide?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      onClick={onClick}
      className={`flex h-6 cursor-pointer items-center justify-center rounded-sm hover:bg-fog hover:text-ink-0 ${
        wide ? 'w-11 font-mono text-10 text-ink-2' : 'w-6 text-ink-1'
      } ${pressed ? 'text-neon-ink' : ''}`}
    >
      {children}
    </button>
  );
}
