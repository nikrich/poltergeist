import { useCallback, useEffect, useRef, useState } from 'react';
import type { PointerEvent as ReactPointerEvent } from 'react';

import type { NoteKind } from '../../shared/api-types';
import { fitCamera, toWorld, type Camera, type ZoomBounds } from '../lib/constellation-engine';
import { drawFrame, pickNode, planFrame } from '../lib/graph/draw';
import type { Scene, SceneNode } from '../lib/graph/layout';

/** Whole-vault scenes span ±1000 world units, so zoom out further than the constellation. */
export const FIT_BOUNDS: ZoomBounds = { min: 0.05, max: 1.6 };
export const ZOOM_MIN = 0.03;
export const ZOOM_MAX = 4;
export const DRAG_SLOP_PX = 4;
export const DOUBLE_CLICK_MS = 350;
export const DOUBLE_CLICK_SLOP_PX = 8;
/** Ego graphs (≤ 300 nodes) get an accessible node list; whole-vault scenes are too big. */
export const A11Y_LIST_MAX = 400;

interface Props {
  scene: Scene;
  hiddenKinds: ReadonlySet<NoteKind>;
  onRecenter: (node: SceneNode) => void;
  onOpen: (node: SceneNode) => void;
}

export function nodeButtonLabel(node: SceneNode): string {
  return node.ghost ? `${node.title} (not written yet)` : node.title;
}

interface Drag {
  sx: number;
  sy: number;
  lx: number;
  ly: number;
  moved: boolean;
}

interface LastClick {
  node: SceneNode;
  at: number;
  x: number;
  y: number;
}

export function GraphCanvas({ scene, hiddenKinds, onRecenter, onOpen }: Props) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const camRef = useRef<Camera>({ x: 0, y: 0, scale: 1 });
  const sizeRef = useRef({ w: 0, h: 0, dpr: 1 });
  const hoverRef = useRef(-1);
  const pendingRef = useRef(false);
  const frameIdRef = useRef(0);
  const dragRef = useRef<Drag | null>(null);
  const lastClickRef = useRef<LastClick | null>(null);
  // Mirrors read by the draw and pointer code without re-binding listeners.
  const sceneRef = useRef(scene);
  const hiddenRef = useRef(hiddenKinds);
  const handlersRef = useRef({ onRecenter, onOpen });
  sceneRef.current = scene;
  hiddenRef.current = hiddenKinds;
  handlersRef.current = { onRecenter, onOpen };
  const [edgesSkipped, setEdgesSkipped] = useState(false);

  const draw = useCallback(() => {
    const ctx = canvasRef.current?.getContext('2d');
    if (!ctx) return;
    const { w, h, dpr } = sizeRef.current;
    const plan = planFrame(sceneRef.current, camRef.current, w, h, {
      hidden: hiddenRef.current,
      hover: hoverRef.current,
    });
    drawFrame(ctx, sceneRef.current, camRef.current, w, h, dpr, plan, hoverRef.current);
    setEdgesSkipped(plan.edgesSkipped);
  }, []);

  // On-demand drawing: at most one frame per animation tick, none while idle.
  const requestDraw = useCallback(() => {
    if (pendingRef.current) return;
    pendingRef.current = true;
    frameIdRef.current = requestAnimationFrame(() => {
      pendingRef.current = false;
      draw();
    });
  }, [draw]);

  const measure = useCallback(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas) return;
    const rect = wrap.getBoundingClientRect();
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    sizeRef.current = { w: rect.width, h: rect.height, dpr };
    canvas.width = Math.round(rect.width * dpr);
    canvas.height = Math.round(rect.height * dpr);
  }, []);

  useEffect(() => {
    measure();
    const { w, h } = sizeRef.current;
    camRef.current = fitCamera(scene.nodes, w, h, FIT_BOUNDS);
    hoverRef.current = -1;
    requestDraw();
  }, [scene, measure, requestDraw]);

  useEffect(() => {
    requestDraw();
  }, [hiddenKinds, requestDraw]);

  useEffect(() => {
    const wrap = wrapRef.current;
    if (!wrap || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      measure();
      requestDraw();
    });
    observer.observe(wrap);
    return () => observer.disconnect();
  }, [measure, requestDraw]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const { w, h } = sizeRef.current;
      const cam = camRef.current;
      const [wx, wy] = toWorld(cam, w, h, sx, sy);
      const scale = Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, cam.scale * Math.exp(-e.deltaY * 0.0014)));
      camRef.current = { scale, x: wx - (sx - w / 2) / scale, y: wy - (sy - h / 2) / scale };
      requestDraw();
    };
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
  }, [requestDraw]);

  useEffect(
    () => () => {
      cancelAnimationFrame(frameIdRef.current);
      pendingRef.current = false;
    },
    [],
  );

  const localPoint = (e: ReactPointerEvent<HTMLCanvasElement>): [number, number] => {
    const rect = e.currentTarget.getBoundingClientRect();
    return [e.clientX - rect.left, e.clientY - rect.top];
  };

  const pick = (x: number, y: number): number => {
    const { w, h } = sizeRef.current;
    return pickNode(sceneRef.current, camRef.current, w, h, x, y, hiddenRef.current);
  };

  const onPointerDown = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const [x, y] = localPoint(e);
    dragRef.current = { sx: x, sy: y, lx: x, ly: y, moved: false };
    e.currentTarget.setPointerCapture?.(e.pointerId);
  };

  const onPointerMove = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const [x, y] = localPoint(e);
    const drag = dragRef.current;
    if (drag) {
      if (!drag.moved && Math.abs(x - drag.sx) + Math.abs(y - drag.sy) <= DRAG_SLOP_PX) return;
      drag.moved = true;
      const cam = camRef.current;
      camRef.current = { ...cam, x: cam.x - (x - drag.lx) / cam.scale, y: cam.y - (y - drag.ly) / cam.scale };
      drag.lx = x;
      drag.ly = y;
      requestDraw();
      return;
    }
    const idx = pick(x, y);
    if (idx !== hoverRef.current) {
      hoverRef.current = idx;
      e.currentTarget.style.cursor = idx >= 0 ? 'pointer' : 'grab';
      requestDraw();
    }
  };

  const onPointerUp = (e: ReactPointerEvent<HTMLCanvasElement>) => {
    const drag = dragRef.current;
    dragRef.current = null;
    if (!drag || drag.moved) return;
    const [x, y] = localPoint(e);
    const now = performance.now();
    const last = lastClickRef.current;
    // The first click recentred, so the scene may have moved under the
    // pointer: a quick second click opens the node clicked first.
    if (
      last &&
      now - last.at <= DOUBLE_CLICK_MS &&
      Math.abs(x - last.x) + Math.abs(y - last.y) <= DOUBLE_CLICK_SLOP_PX
    ) {
      lastClickRef.current = null;
      handlersRef.current.onOpen(last.node);
      return;
    }
    const idx = pick(x, y);
    const node = idx >= 0 ? sceneRef.current.nodes[idx] : undefined;
    if (!node) {
      lastClickRef.current = null;
      return;
    }
    lastClickRef.current = { node, at: now, x, y };
    handlersRef.current.onRecenter(node);
  };

  const onPointerLeave = () => {
    if (hoverRef.current === -1) return;
    hoverRef.current = -1;
    requestDraw();
  };

  return (
    <div ref={wrapRef} className="relative flex flex-1 overflow-hidden">
      {/* the ground stays dark by design, like the constellation */}
      <canvas
        ref={canvasRef}
        role="img"
        aria-label="link graph"
        className="absolute inset-0 h-full w-full cursor-grab touch-none"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerLeave}
      />
      {edgesSkipped && (
        <div
          role="status"
          className="pointer-events-none absolute right-4 top-4 z-10 rounded-pill border border-hairline bg-paper/70 px-3 py-[6px] font-mono text-11 text-ink-1 backdrop-blur-md"
        >
          zoom in to see links
        </div>
      )}
      {scene.nodes.length <= A11Y_LIST_MAX && (
        <ul aria-label="graph nodes" className="sr-only">
          {scene.nodes.map((node, i) =>
            i !== scene.focus && hiddenKinds.has(node.kind) ? null : (
              <li key={node.path}>
                <button
                  type="button"
                  aria-current={i === scene.focus ? 'true' : undefined}
                  onClick={() => onRecenter(node)}
                >
                  {nodeButtonLabel(node)}
                </button>
                <button type="button" onClick={() => onOpen(node)}>
                  {`open ${node.title}`}
                </button>
              </li>
            ),
          )}
        </ul>
      )}
    </div>
  );
}
