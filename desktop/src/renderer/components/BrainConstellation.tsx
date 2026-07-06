import { useEffect, useMemo, useRef, useState } from 'react';

import type { VaultGraphNode } from '../../shared/api-types';
import { useVaultGraph } from '../lib/api/hooks';
import {
  buildAdjacency,
  fitCamera,
  hitTest,
  toScreen,
  toWorld,
  type Camera,
} from '../lib/constellation-engine';
import { useNoteView } from '../stores/note-view';
import { useSettings } from '../stores/settings';
import { toast } from '../stores/toast';
import { Btn } from './Btn';
import { Ghost } from './Ghost';
import { Lucide } from './Lucide';
import { PanelError } from './PanelError';

// ── pure helpers (no React, no DOM) ────────────────────────────────────────

/** Node draw radius from degree. Mirrors the size formula baked into
 * constellation-engine's `hitTest` (not exported standalone) — keep in sync. */
function nodeRadius(degree: number): number {
  return 2.7 + Math.min(degree, 14) * 0.62;
}

function hexRgb(hex: string): { r: number; g: number; b: number } {
  const n = parseInt(hex.slice(1), 16);
  return { r: (n >> 16) & 255, g: (n >> 8) & 255, b: n & 255 };
}

function mixWhite(hex: string, t: number): string {
  const { r, g, b } = hexRgb(hex);
  return `rgb(${Math.round(r + (255 - r) * t)},${Math.round(g + (255 - g) * t)},${Math.round(b + (255 - b) * t)})`;
}

function randomItem<T>(arr: T[]): T | undefined {
  return arr.length === 0 ? undefined : arr[Math.floor(Math.random() * arr.length)];
}

const GLOW_SPRITE_SIZE = 96;

function makeGlowSprite(color: string): HTMLCanvasElement {
  const c = document.createElement('canvas');
  c.width = GLOW_SPRITE_SIZE;
  c.height = GLOW_SPRITE_SIZE;
  const g = c.getContext('2d');
  if (!g) return c;
  const { r, g: gr, b } = hexRgb(color);
  const rad = g.createRadialGradient(
    GLOW_SPRITE_SIZE / 2,
    GLOW_SPRITE_SIZE / 2,
    0,
    GLOW_SPRITE_SIZE / 2,
    GLOW_SPRITE_SIZE / 2,
    GLOW_SPRITE_SIZE / 2,
  );
  rad.addColorStop(
    0,
    `rgba(${Math.min(255, r + 70)},${Math.min(255, gr + 70)},${Math.min(255, b + 70)},0.98)`,
  );
  rad.addColorStop(0.18, `rgba(${r},${gr},${b},0.66)`);
  rad.addColorStop(0.5, `rgba(${r},${gr},${b},0.22)`);
  rad.addColorStop(1, `rgba(${r},${gr},${b},0)`);
  g.fillStyle = rad;
  g.fillRect(0, 0, GLOW_SPRITE_SIZE, GLOW_SPRITE_SIZE);
  return c;
}

interface RenderNode {
  index: number;
  node: VaultGraphNode;
  r: number;
  phase: number;
  tw: number;
  appear: number;
  /** current, drift-adjusted world position (mutated per frame) */
  x: number;
  y: number;
}

interface RenderEdge {
  a: RenderNode;
  b: RenderNode;
  weight: number;
  /** cross-context edge — the "discovery" synapses, drawn/emphasised like the mockup's bridges */
  bridge: boolean;
}

interface Signal {
  edge: RenderEdge;
  t: number;
  spd: number;
}

interface CamState extends Camera {
  tx: number;
  ty: number;
  tscale: number;
}

interface CardData {
  node: VaultGraphNode;
  color: string;
  related: { node: VaultGraphNode; weight: number }[];
}

// ── component ───────────────────────────────────────────────────────────────

export function BrainConstellation() {
  const graphQuery = useVaultGraph();
  const graph = graphQuery.data;
  const vaultPath = useSettings((s) => s.vaultPath);
  const openNote = useNoteView((s) => s.open);

  const reduceMotion = useMemo(
    () =>
      typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches,
    [],
  );

  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const hoverLabelRef = useRef<HTMLDivElement | null>(null);

  const [showEdges, setShowEdges] = useState(true);
  const [motionOn, setMotionOn] = useState(!reduceMotion);
  const [isolated, setIsolated] = useState<string | null>(null);
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

  // mutable mirrors read by the rAF loop / pointer handlers, kept in sync
  // with the state above so toggling doesn't require tearing down the loop
  const showEdgesRef = useRef(showEdges);
  const motionRef = useRef(motionOn);
  const isolatedRef = useRef(isolated);
  const selectedIdxRef = useRef(-1);
  const hoverIdxRef = useRef(-1);
  const camRef = useRef<CamState>({ x: 0, y: 0, scale: 1, tx: 0, ty: 0, tscale: 1 });

  useEffect(() => {
    showEdgesRef.current = showEdges;
  }, [showEdges]);
  useEffect(() => {
    motionRef.current = motionOn;
  }, [motionOn]);
  useEffect(() => {
    isolatedRef.current = isolated;
  }, [isolated]);

  const onOpenPath = async (relPath: string) => {
    const result = await window.gb.shell.openPath(`${vaultPath}/${relPath}`);
    if (!result.ok) toast.error(result.error);
  };

  const focusNodeRef = useRef<(path: string) => void>(() => {});

  // ── main effect: build render data + start the loop; re-run on new payload ──
  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap || !graph || graph.nodes.length === 0) return;

    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const regionColor = new Map(graph.regions.map((r) => [r.id, r.color] as const));
    const fallbackColor = '#8a8fa3';

    // The mockup was tuned on a few hundred synthetic nodes; a real vault packs
    // thousands into tight embedding clusters, and the additive glow/edge passes
    // saturate to solid white. Scale intensity and dot size down with density so
    // dense vaults stay legible while small ones keep the full bloom.
    const glowScale = Math.min(1, Math.sqrt(180 / Math.max(graph.nodes.length, 1)));
    const edgeScale = Math.min(1, Math.sqrt(600 / Math.max(graph.edges.length, 1)));
    const glowRadiusScale = 0.55 + 0.45 * glowScale;
    const nodeScale = 0.5 + 0.5 * glowScale;
    const coreDotDegree = graph.nodes.length > 1500 ? 14 : 6;

    const renderNodes: RenderNode[] = graph.nodes.map((node, index) => ({
      index,
      node,
      r: nodeRadius(node.degree) * nodeScale,
      phase: Math.random() * Math.PI * 2,
      tw: 0.6 + Math.random() * 0.8,
      appear: Math.random() * 0.5,
      x: node.x,
      y: node.y,
    }));
    const byPath = new Map(renderNodes.map((rn) => [rn.node.path, rn] as const));

    const renderEdges: RenderEdge[] = [];
    for (const e of graph.edges) {
      const a = byPath.get(e.source);
      const b = byPath.get(e.target);
      if (!a || !b) continue;
      renderEdges.push({ a, b, weight: e.weight, bridge: a.node.context !== b.node.context });
    }

    const adjacency = buildAdjacency(graph);

    const centroidSums = new Map<string, { sx: number; sy: number; n: number }>();
    for (const rn of renderNodes) {
      const s = centroidSums.get(rn.node.context) ?? { sx: 0, sy: 0, n: 0 };
      s.sx += rn.node.x;
      s.sy += rn.node.y;
      s.n += 1;
      centroidSums.set(rn.node.context, s);
    }
    const centroid = new Map<string, { x: number; y: number }>();
    for (const [context, s] of centroidSums)
      centroid.set(context, { x: s.sx / s.n, y: s.sy / s.n });

    const glowSprites = new Map<string, HTMLCanvasElement>();
    for (const color of new Set(graph.regions.map((r) => r.color))) {
      glowSprites.set(color, makeGlowSprite(color));
    }

    const signals: Signal[] = [];

    let W = 0;
    let H = 0;
    let DPR = 1;

    const resize = () => {
      const rect = wrap.getBoundingClientRect();
      DPR = Math.min(window.devicePixelRatio || 1, 2);
      W = rect.width;
      H = rect.height;
      canvas.width = W * DPR;
      canvas.height = H * DPR;
      canvas.style.width = `${W}px`;
      canvas.style.height = `${H}px`;
      ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    };
    resize();

    const cam = camRef.current;
    const fit = fitCamera(graph.nodes, W, H);
    cam.x = fit.x;
    cam.y = fit.y;
    cam.scale = fit.scale;
    cam.tx = fit.x;
    cam.ty = fit.y;
    cam.tscale = fit.scale;

    const resizeObserver = new ResizeObserver(() => resize());
    resizeObserver.observe(wrap);

    focusNodeRef.current = (path: string) => {
      const rn = byPath.get(path);
      if (!rn) return;
      cam.tx = rn.node.x;
      cam.ty = rn.node.y;
      cam.tscale = Math.max(cam.scale, 1.1);
    };

    // ── pointer: pan / hover / click ──
    let dragging = false;
    let dragMoved = false;
    let lastX = 0;
    let lastY = 0;
    let downX = 0;
    let downY = 0;

    const pointerPos = (e: PointerEvent): [number, number] => {
      const rect = canvas.getBoundingClientRect();
      return [e.clientX - rect.left, e.clientY - rect.top];
    };

    const pickHover = (sx: number, sy: number) => {
      const idx = hitTest(cam, W, H, graph.nodes, sx, sy);
      hoverIdxRef.current = idx;
      canvas.classList.toggle('cursor-pointer', idx !== -1);
      const label = hoverLabelRef.current;
      if (!label) return;
      const rn = idx !== -1 ? renderNodes[idx] : undefined;
      if (rn) {
        const [x, y] = toScreen(cam, W, H, rn.x, rn.y);
        label.style.left = `${x}px`;
        label.style.top = `${y}px`;
        const color = regionColor.get(rn.node.context) ?? fallbackColor;
        // built via safe DOM methods (not innerHTML) — note titles come from
        // vault content (can originate from imported Confluence/Jira/etc. text)
        // and must never be parsed as HTML.
        label.replaceChildren();
        const dot = document.createElement('span');
        dot.className = 'mr-[6px] inline-block h-[6px] w-[6px] rounded-full';
        dot.style.background = color;
        dot.style.boxShadow = `0 0 6px ${color}`;
        label.append(dot, document.createTextNode(rn.node.title));
        label.style.opacity = '1';
      } else {
        label.style.opacity = '0';
      }
    };

    const onPointerDown = (e: PointerEvent) => {
      dragging = true;
      dragMoved = false;
      const [x, y] = pointerPos(e);
      lastX = x;
      downX = x;
      lastY = y;
      downY = y;
      canvas.classList.add('cursor-grabbing');
      canvas.setPointerCapture(e.pointerId);
    };

    const onPointerMove = (e: PointerEvent) => {
      const [x, y] = pointerPos(e);
      if (dragging) {
        const dx = x - lastX;
        const dy = y - lastY;
        if (Math.abs(x - downX) + Math.abs(y - downY) > 4) dragMoved = true;
        cam.x -= dx / cam.scale;
        cam.y -= dy / cam.scale;
        cam.tx = cam.x;
        cam.ty = cam.y;
        lastX = x;
        lastY = y;
      } else {
        pickHover(x, y);
      }
    };

    // Selecting a node only opens the side card; the card's footer offers the
    // in-app viewer and the on-disk editor explicitly.
    const openNodeCard = (idx: number) => {
      const rn = renderNodes[idx];
      if (!rn) return;
      selectedIdxRef.current = idx;
      setSelectedPath(rn.node.path);
    };

    const onPointerUp = (e: PointerEvent) => {
      dragging = false;
      canvas.classList.remove('cursor-grabbing');
      if (!dragMoved) {
        const [x, y] = pointerPos(e);
        pickHover(x, y);
        if (hoverIdxRef.current !== -1) {
          openNodeCard(hoverIdxRef.current);
        } else {
          setSelectedPath(null);
          selectedIdxRef.current = -1;
        }
      }
    };

    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = canvas.getBoundingClientRect();
      const sx = e.clientX - rect.left;
      const sy = e.clientY - rect.top;
      const [wx, wy] = toWorld(cam, W, H, sx, sy);
      const factor = Math.exp(-e.deltaY * 0.0014);
      cam.scale = Math.max(0.2, Math.min(4, cam.scale * factor));
      cam.tscale = cam.scale;
      cam.x = wx - (sx - W / 2) / cam.scale;
      cam.y = wy - (sy - H / 2) / cam.scale;
      cam.tx = cam.x;
      cam.ty = cam.y;
    };

    canvas.addEventListener('pointerdown', onPointerDown);
    canvas.addEventListener('pointermove', onPointerMove);
    canvas.addEventListener('pointerup', onPointerUp);
    canvas.addEventListener('wheel', onWheel, { passive: false });

    // ── render loop ──
    let last = performance.now();
    const startT = performance.now();
    let rafId = 0;

    const frame = (now: number) => {
      const dt = Math.min(50, now - last);
      last = now;
      const t = now * 0.001;

      cam.x += (cam.tx - cam.x) * 0.12;
      cam.y += (cam.ty - cam.y) * 0.12;
      cam.scale += (cam.tscale - cam.scale) * 0.12;
      // wall-clock (not per-frame accumulation) — robust to background-tab rAF throttling
      const appearT = reduceMotion ? 1 : Math.min(1, (now - startT) / 1500);

      if (motionRef.current) {
        for (const rn of renderNodes) {
          rn.x = rn.node.x + Math.sin(t * 0.28 + rn.phase) * 5.5;
          rn.y = rn.node.y + Math.cos(t * 0.24 + rn.phase * 1.3) * 5.5;
        }
      }

      ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
      const bg = ctx.createRadialGradient(
        W / 2,
        H * 0.44,
        0,
        W / 2,
        H * 0.44,
        Math.max(W, H) * 0.75,
      );
      bg.addColorStop(0, '#101422');
      bg.addColorStop(0.55, '#090b14');
      bg.addColorStop(1, '#050609');
      ctx.fillStyle = bg;
      ctx.fillRect(0, 0, W, H);

      ctx.globalCompositeOperation = 'lighter';
      for (const region of graph.regions) {
        if (isolatedRef.current !== null && isolatedRef.current !== region.id) continue;
        const c = centroid.get(region.id);
        if (!c) continue;
        const [x, y] = toScreen(cam, W, H, c.x, c.y);
        const rad = 265 * cam.scale;
        const g = ctx.createRadialGradient(x, y, 0, x, y, rad);
        const { r, g: gr, b } = hexRgb(region.color);
        const a =
          (isolatedRef.current === region.id ? 0.32 : 0.17) * appearT * (0.5 + 0.5 * glowScale);
        g.addColorStop(0, `rgba(${r},${gr},${b},${a})`);
        g.addColorStop(1, `rgba(${r},${gr},${b},0)`);
        ctx.fillStyle = g;
        ctx.fillRect(x - rad, y - rad, rad * 2, rad * 2);
      }

      const focusIdx = selectedIdxRef.current !== -1 ? selectedIdxRef.current : hoverIdxRef.current;
      const focusNode = focusIdx !== -1 ? renderNodes[focusIdx] : undefined;
      let focusSet: Set<RenderNode> | null = null;
      if (focusNode) {
        focusSet = new Set([focusNode]);
        for (const neighborPath of adjacency.get(focusNode.node.path) ?? []) {
          const nrn = byPath.get(neighborPath);
          if (nrn) focusSet.add(nrn);
        }
      }
      const dimOf = (rn: RenderNode): number => {
        if (isolatedRef.current !== null && rn.node.context !== isolatedRef.current) return 0.12;
        if (focusSet && !focusSet.has(rn)) return 0.16;
        return 1;
      };

      if (showEdgesRef.current) {
        for (const e of renderEdges) {
          let dim = Math.min(dimOf(e.a), dimOf(e.b));
          const inFocus = !!focusNode && (e.a === focusNode || e.b === focusNode);
          if (focusSet && !inFocus) dim = Math.min(dim, 0.14);
          if (
            isolatedRef.current !== null &&
            e.a.node.context !== isolatedRef.current &&
            e.b.node.context !== isolatedRef.current
          )
            continue;
          const [x1, y1] = toScreen(cam, W, H, e.a.x, e.a.y);
          const [x2, y2] = toScreen(cam, W, H, e.b.x, e.b.y);
          if (
            Math.max(x1, x2) < -50 ||
            Math.min(x1, x2) > W + 50 ||
            Math.max(y1, y2) < -50 ||
            Math.min(y1, y2) > H + 50
          )
            continue;
          const col = hexRgb(regionColor.get(e.a.node.context) ?? fallbackColor);
          const base = (e.bridge ? 0.5 : 0.26) * (inFocus ? 1 : edgeScale);
          const a = base * dim * appearT * (inFocus ? 2.6 : 1);
          ctx.strokeStyle = `rgba(${col.r},${col.g},${col.b},${a})`;
          ctx.lineWidth = (e.bridge ? 1.4 : 0.9) * (inFocus ? 1.8 : 1);
          ctx.beginPath();
          ctx.moveTo(x1, y1);
          ctx.lineTo(x2, y2);
          ctx.stroke();
        }
      }

      if (motionRef.current) {
        if (Math.random() < 0.05 && signals.length < 22 && renderEdges.length > 0) {
          const edge = randomItem(renderEdges);
          if (edge) signals.push({ edge, t: 0, spd: 0.5 + Math.random() * 0.6 });
        }
        for (let i = signals.length - 1; i >= 0; i--) {
          const s = signals[i];
          if (!s) continue;
          s.t += (dt / 1000) * s.spd;
          if (s.t >= 1) {
            signals.splice(i, 1);
            continue;
          }
          const [x1, y1] = toScreen(cam, W, H, s.edge.a.x, s.edge.a.y);
          const [x2, y2] = toScreen(cam, W, H, s.edge.b.x, s.edge.b.y);
          const x = x1 + (x2 - x1) * s.t;
          const y = y1 + (y2 - y1) * s.t;
          const col = hexRgb(regionColor.get(s.edge.a.node.context) ?? fallbackColor);
          const rad = s.edge.bridge ? 9 : 6;
          const g = ctx.createRadialGradient(x, y, 0, x, y, rad);
          g.addColorStop(0, `rgba(${col.r},${col.g},${col.b},0.95)`);
          g.addColorStop(1, `rgba(${col.r},${col.g},${col.b},0)`);
          ctx.fillStyle = g;
          ctx.fillRect(x - 9, y - 9, 18, 18);
        }
      }

      for (const rn of renderNodes) {
        const na = appearT >= 1 ? 1 : Math.max(0, Math.min(1, (appearT - rn.appear) / 0.35));
        if (na <= 0) continue;
        const [x, y] = toScreen(cam, W, H, rn.x, rn.y);
        if (x < -60 || x > W + 60 || y < -60 || y > H + 60) continue;
        const dim = dimOf(rn);
        const isFoc = focusNode === rn;
        const tw = motionRef.current ? 0.82 + 0.18 * Math.sin(t * rn.tw * 1.6 + rn.phase) : 1;
        const glowR =
          (rn.r * cam.scale + 5) * (isFoc ? 3.8 : 2.7 * glowRadiusScale) * (0.9 + tw * 0.2);
        const sprite = glowSprites.get(regionColor.get(rn.node.context) ?? fallbackColor);
        if (!sprite) continue;
        ctx.globalAlpha = Math.min(1, dim * na * (isFoc ? 1.15 : 0.98 * glowScale) * tw);
        ctx.drawImage(sprite, x - glowR, y - glowR, glowR * 2, glowR * 2);
      }
      ctx.globalAlpha = 1;

      ctx.globalCompositeOperation = 'source-over';
      for (const rn of renderNodes) {
        const na = appearT >= 1 ? 1 : Math.max(0, Math.min(1, (appearT - rn.appear) / 0.35));
        if (na <= 0) continue;
        const [x, y] = toScreen(cam, W, H, rn.x, rn.y);
        if (x < -20 || x > W + 20 || y < -20 || y > H + 20) continue;
        const dim = dimOf(rn);
        const isFoc = focusNode === rn;
        const r = rn.r * cam.scale * (isFoc ? 1.5 : 1) * na;
        ctx.globalAlpha = Math.max(dim, 0.28) * na;
        ctx.fillStyle = mixWhite(
          regionColor.get(rn.node.context) ?? fallbackColor,
          isFoc ? 0.85 : 0.62,
        );
        ctx.beginPath();
        ctx.arc(x, y, Math.max(1, r), 0, Math.PI * 2);
        ctx.fill();
        if (isFoc || rn.node.degree >= coreDotDegree) {
          ctx.globalAlpha = na;
          ctx.fillStyle = '#fff';
          ctx.beginPath();
          ctx.arc(x, y, Math.max(0.5, r * 0.42), 0, Math.PI * 2);
          ctx.fill();
        }
      }
      ctx.globalAlpha = 1;

      if (hoverIdxRef.current !== -1 && !dragging) {
        const rn = renderNodes[hoverIdxRef.current];
        const label = hoverLabelRef.current;
        if (rn && label) {
          const [x, y] = toScreen(cam, W, H, rn.x, rn.y);
          label.style.left = `${x}px`;
          label.style.top = `${y}px`;
        }
      }

      rafId = requestAnimationFrame(frame);
    };
    rafId = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(rafId);
      resizeObserver.disconnect();
      canvas.removeEventListener('pointerdown', onPointerDown);
      canvas.removeEventListener('pointermove', onPointerMove);
      canvas.removeEventListener('pointerup', onPointerUp);
      canvas.removeEventListener('wheel', onWheel);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [graph, reduceMotion]);

  const card = useMemo<CardData | null>(() => {
    if (!graph || !selectedPath) return null;
    const node = graph.nodes.find((n) => n.path === selectedPath);
    if (!node) return null;
    const regionColor = new Map(graph.regions.map((r) => [r.id, r.color] as const));
    const byPath = new Map(graph.nodes.map((n) => [n.path, n] as const));
    const relatedByPath = new Map<string, { node: VaultGraphNode; weight: number }>();
    for (const e of graph.edges) {
      let n: VaultGraphNode | undefined;
      let weight = e.weight;
      if (e.source === selectedPath) {
        n = byPath.get(e.target);
      } else if (e.target === selectedPath) {
        n = byPath.get(e.source);
      }
      if (!n) continue;
      // The builder can emit two edges for the same pair (e.g. "related" +
      // "wikilink"); keep only the strongest one so keys and rows don't dupe.
      const existing = relatedByPath.get(n.path);
      if (!existing || weight > existing.weight) {
        relatedByPath.set(n.path, { node: n, weight });
      }
    }
    const related = Array.from(relatedByPath.values());
    related.sort((a, b) => b.weight - a.weight);
    return {
      node,
      color: regionColor.get(node.context) ?? '#8a8fa3',
      related: related.slice(0, 4),
    };
  }, [graph, selectedPath]);

  const closeCard = () => {
    setSelectedPath(null);
    selectedIdxRef.current = -1;
  };

  const openRelated = (path: string) => {
    focusNodeRef.current(path);
    setSelectedPath(path);
    const idx = graph?.nodes.findIndex((n) => n.path === path) ?? -1;
    selectedIdxRef.current = idx;
  };

  const resetView = () => {
    if (!graph || !wrapRef.current) return;
    const rect = wrapRef.current.getBoundingClientRect();
    const fit = fitCamera(graph.nodes, rect.width, rect.height);
    const cam = camRef.current;
    cam.tx = fit.x;
    cam.ty = fit.y;
    cam.tscale = fit.scale;
    closeCard();
    setIsolated(null);
  };

  if (graphQuery.isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center bg-paper">
        <Ghost size={48} floating />
      </div>
    );
  }

  if (graphQuery.isError) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center bg-paper">
        <PanelError
          message={
            graphQuery.error instanceof Error
              ? graphQuery.error.message
              : 'failed to load the vault graph'
          }
          onRetry={() => graphQuery.refetch()}
        />
      </div>
    );
  }

  if (!graph || graph.nodes.length === 0) {
    const onOpenVault = async () => {
      const result = await window.gb.shell.openPath(vaultPath);
      if (!result.ok) toast.error(result.error);
    };
    return (
      <div className="flex flex-1 flex-col bg-paper">
        <div className="flex flex-1 flex-col items-center justify-center gap-[18px] p-12">
          <Ghost size={72} floating />
          <h2 className="m-0 font-display text-28 font-semibold tracking-tight-x text-ink-0">
            your vault is on disk.
          </h2>
          <p className="m-0 max-w-[380px] text-center text-14 text-ink-2">
            poltergeist doesn&rsquo;t replace your editor — it feeds the vault. open it to see
            everything as markdown.
          </p>
          <Btn
            variant="primary"
            size="lg"
            icon={<Lucide name="external-link" size={14} color="#0E0F12" />}
            onClick={onOpenVault}
          >
            open vault folder
          </Btn>
          <span className="font-mono text-11 text-ink-3">{vaultPath}</span>
        </div>
      </div>
    );
  }

  return (
    <div ref={wrapRef} className="relative flex flex-1 overflow-hidden bg-paper">
      {/* the ground stays dark by design — additive glow needs a dark canvas
          regardless of the app's light/dark theme */}
      <canvas ref={canvasRef} className="absolute inset-0 h-full w-full cursor-grab" />

      {/* top stats */}
      <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-center justify-end gap-2 p-4">
        <div className="pointer-events-auto flex items-center gap-2 rounded-pill border border-hairline bg-paper/70 px-3 py-[6px] font-mono text-12 tabular-nums text-ink-1 backdrop-blur-md">
          <span
            className="h-[6px] w-[6px] rounded-full bg-neon"
            style={{ boxShadow: '0 0 8px var(--neon)' }}
          />
          <b className="font-semibold text-ink-0">{graph.nodes.length}</b> notes
        </div>
        <div className="pointer-events-auto flex items-center gap-2 rounded-pill border border-hairline bg-paper/70 px-3 py-[6px] font-mono text-12 tabular-nums text-ink-1 backdrop-blur-md">
          <span
            className="h-[6px] w-[6px] rounded-full bg-[#38bdf8]"
            style={{ boxShadow: '0 0 8px #38bdf8' }}
          />
          <b className="font-semibold text-ink-0">{graph.edges.length}</b> links
        </div>
        <div className="pointer-events-auto flex items-center gap-2 rounded-pill border border-hairline bg-paper/70 px-3 py-[6px] font-mono text-12 tabular-nums text-ink-1 backdrop-blur-md">
          <span
            className="h-[6px] w-[6px] rounded-full bg-[#a78bfa]"
            style={{ boxShadow: '0 0 8px #a78bfa' }}
          />
          <b className="font-semibold text-ink-0">{graph.regions.length}</b> regions
        </div>
      </div>

      {/* region legend */}
      <div className="absolute bottom-5 left-5 z-10 w-[216px] rounded-lg border border-hairline bg-paper/70 p-[14px] backdrop-blur-md">
        <div className="mb-[10px] font-mono text-10 uppercase tracking-eyebrow text-ink-2">
          regions
        </div>
        <div className="flex flex-col">
          {graph.regions.map((region) => (
            <button
              key={region.id}
              type="button"
              onClick={() => setIsolated((cur) => (cur === region.id ? null : region.id))}
              className={`flex w-full items-center gap-[10px] rounded-md border-0 bg-transparent px-[7px] py-[6px] text-left text-13 text-ink-1 transition-opacity hover:bg-vellum ${
                isolated !== null && isolated !== region.id ? 'opacity-30' : 'opacity-100'
              }`}
            >
              <span
                className="h-[9px] w-[9px] flex-none rounded-full"
                style={{ background: region.color, boxShadow: `0 0 9px ${region.color}` }}
              />
              <span className="flex-1 text-ink-0">{region.label}</span>
              <span className="font-mono text-11 tabular-nums text-ink-2">{region.count}</span>
            </button>
          ))}
        </div>
        <div className="mt-[9px] border-t border-hairline pt-[10px] text-11 leading-[1.5] text-ink-2">
          click a region to isolate · click a star to open its note
        </div>
      </div>

      {/* controls */}
      <div className="absolute bottom-5 right-5 z-10 flex gap-[7px]">
        <button
          type="button"
          onClick={() => setShowEdges((v) => !v)}
          className={`rounded-pill border px-3 py-[7px] font-mono text-11 tracking-wide transition-colors ${
            showEdges
              ? 'border-neon bg-neon text-[#08130d]'
              : 'border-hairline bg-paper/70 text-ink-1 backdrop-blur-md hover:text-ink-0'
          }`}
        >
          synapses
        </button>
        <button
          type="button"
          onClick={() => setMotionOn((v) => !v)}
          className={`rounded-pill border px-3 py-[7px] font-mono text-11 tracking-wide transition-colors ${
            motionOn
              ? 'border-neon bg-neon text-[#08130d]'
              : 'border-hairline bg-paper/70 text-ink-1 backdrop-blur-md hover:text-ink-0'
          }`}
        >
          motion
        </button>
        <button
          type="button"
          onClick={resetView}
          className="rounded-pill border border-hairline bg-paper/70 px-3 py-[7px] font-mono text-11 tracking-wide text-ink-1 backdrop-blur-md transition-colors hover:text-ink-0"
        >
          reset view
        </button>
      </div>

      {/* note card */}
      {card && (
        <div className="absolute right-5 top-[68px] z-20 w-[316px] rounded-[18px] border border-hairline-2 bg-paper/85 p-[18px] shadow-float backdrop-blur-xl">
          <button
            type="button"
            aria-label="close"
            onClick={closeCard}
            className="absolute right-[14px] top-[13px] grid h-[22px] w-[22px] place-items-center rounded-md border-0 bg-transparent text-15 leading-none text-ink-2 transition-colors hover:bg-vellum hover:text-ink-0"
          >
            ×
          </button>
          <div className="inline-flex items-center gap-[7px] font-mono text-10 uppercase tracking-eyebrow text-ink-1">
            <span
              className="h-2 w-2 rounded-full"
              style={{ background: card.color, boxShadow: `0 0 8px ${card.color}` }}
            />
            <span>{card.node.context}</span>
          </div>
          <h3 className="my-[11px] text-balance text-18 font-semibold leading-[1.24] tracking-tight-xx text-ink-0">
            {card.node.title}
          </h3>
          <div className="mb-3 break-all font-mono text-10 text-ink-2">{card.node.path}</div>
          {card.related.length > 0 && (
            <>
              <div className="mb-2 font-mono text-10 uppercase tracking-eyebrow text-ink-3">
                related — by meaning
              </div>
              <div className="mb-[15px] flex flex-col gap-[7px]">
                {card.related.map(({ node, weight }) => (
                  <button
                    key={node.path}
                    type="button"
                    onClick={() => openRelated(node.path)}
                    className="flex items-center gap-[9px] border-0 bg-transparent p-0 text-left text-[12.5px] text-ink-1 transition-colors hover:text-ink-0"
                  >
                    <span
                      className="h-[7px] w-[7px] flex-none rounded-full"
                      style={{
                        background: card.color,
                        boxShadow: `0 0 7px ${card.color}`,
                      }}
                    />
                    <span className="min-w-0 flex-1 truncate">{node.title}</span>
                    <span className="font-mono text-10 text-ink-3">{weight.toFixed(2)}</span>
                  </button>
                ))}
              </div>
            </>
          )}
          <div className="flex items-center gap-[12px] border-t border-hairline pt-[13px] text-[11.5px] text-ink-2">
            <span className="min-w-0 flex-1 truncate">
              {card.node.updated ? `updated ${card.node.updated}` : 'no update recorded'}
            </span>
            <button
              type="button"
              onClick={() => openNote(card.node.path)}
              className="flex shrink-0 items-center gap-[6px] whitespace-nowrap border-0 bg-transparent p-0 text-neon"
            >
              <Lucide name="eye" size={11} color="var(--neon)" />
              view note
            </button>
            <button
              type="button"
              onClick={() => onOpenPath(card.node.path)}
              className="flex shrink-0 items-center gap-[6px] whitespace-nowrap border-0 bg-transparent p-0 text-neon"
            >
              <Lucide name="external-link" size={11} color="var(--neon)" />
              open in vault
            </button>
          </div>
        </div>
      )}

      <div
        ref={hoverLabelRef}
        className="pointer-events-none absolute z-[6] whitespace-nowrap rounded-md border border-hairline-2 bg-paper/90 px-[10px] py-[5px] text-12 text-ink-0 opacity-0 backdrop-blur-sm"
        style={{ transform: 'translate(-50%, -140%)' }}
      />
    </div>
  );
}
