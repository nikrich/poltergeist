import type { NoteKind } from '../../../shared/api-types';
import { toScreen, type Camera } from '../constellation-engine';
import {
  EDGE_COLOR,
  EDGE_HI_COLOR,
  FOCUS_COLOR,
  GHOST_COLOR,
  GROUND_COLOR,
  KIND_COLORS,
  LABEL_COLOR,
  LABEL_FONT,
} from './kinds';
import type { Scene } from './layout';

/** Level-of-detail budgets. A 30k-note vault has ~90k links: drawing them
 * all is unreadable and slow, so past the budget only the hovered/focused
 * node's links are drawn and the UI says "zoom in to see links". */
export const EDGE_BUDGET = 4000;
export const LABEL_BUDGET = 40;
export const LABEL_MIN_SCALE = 0.9;
export const DOT_MIN_PX = 1.5;
export const HIT_MIN_PX = 6;
export const VIEW_MARGIN_PX = 40;
export const LABEL_MAX_CHARS = 32;

export interface FrameOptions {
  hidden: ReadonlySet<NoteKind>;
  hover: number;
}

export interface FramePlan {
  /** node indices to draw (shown kind, in the viewport) */
  nodes: number[];
  /** edge indices to draw */
  edges: number[];
  /** node indices to label */
  labels: number[];
  /** links were dropped to stay within EDGE_BUDGET */
  edgesSkipped: boolean;
  /** screen position of every node */
  sx: Float32Array;
  sy: Float32Array;
}

export type DrawContext = Pick<
  CanvasRenderingContext2D,
  | 'setTransform' | 'fillRect' | 'beginPath' | 'moveTo' | 'lineTo' | 'arc' | 'rect' | 'fill' | 'stroke' | 'fillText'
  | 'fillStyle' | 'strokeStyle' | 'lineWidth' | 'font' | 'textAlign' | 'textBaseline' | 'globalAlpha'
>;

export function isHidden(scene: Scene, i: number, hidden: ReadonlySet<NoteKind>): boolean {
  const node = scene.nodes[i];
  return node !== undefined && i !== scene.focus && hidden.has(node.kind);
}

export function truncateLabel(title: string): string {
  return title.length > LABEL_MAX_CHARS ? `${title.slice(0, LABEL_MAX_CHARS - 1)}…` : title;
}

const HIDDEN = 0;
const OFF_SCREEN = 1;
const ON_SCREEN = 2;

export function planFrame(scene: Scene, cam: Camera, w: number, h: number, opts: FrameOptions): FramePlan {
  const count = scene.nodes.length;
  const sx = new Float32Array(count);
  const sy = new Float32Array(count);
  const state = new Uint8Array(count); // HIDDEN | OFF_SCREEN | ON_SCREEN
  const nodes: number[] = [];
  for (let i = 0; i < count; i++) {
    const n = scene.nodes[i]!;
    const [x, y] = toScreen(cam, w, h, n.x, n.y);
    sx[i] = x;
    sy[i] = y;
    if (isHidden(scene, i, opts.hidden)) continue;
    const pad = n.r * cam.scale + VIEW_MARGIN_PX;
    if (x < -pad || x > w + pad || y < -pad || y > h + pad) {
      state[i] = OFF_SCREEN;
      continue;
    }
    state[i] = ON_SCREEN;
    nodes.push(i);
  }

  const anchors = new Set<number>();
  if (scene.focus >= 0) anchors.add(scene.focus);
  if (opts.hover >= 0) anchors.add(opts.hover);

  let edges: number[] = [];
  const anchored: number[] = [];
  for (let k = 0; k < scene.edges.length; k++) {
    const e = scene.edges[k]!;
    const sa = state[e.a]!;
    const sb = state[e.b]!;
    if (sa === HIDDEN || sb === HIDDEN) continue;
    if (sa !== ON_SCREEN && sb !== ON_SCREEN) continue;
    edges.push(k);
    if (anchors.has(e.a) || anchors.has(e.b)) anchored.push(k);
  }
  let edgesSkipped = false;
  if (edges.length > EDGE_BUDGET) {
    edges = anchored.slice(0, EDGE_BUDGET);
    edgesSkipped = true;
  }

  const visibleAnchors = [...anchors].filter((i) => state[i] === ON_SCREEN);
  let labels = visibleAnchors;
  if (cam.scale >= LABEL_MIN_SCALE || nodes.length <= LABEL_BUDGET) {
    const ranked = nodes
      .filter((i) => !anchors.has(i))
      .sort((p, q) => scene.nodes[q]!.degree - scene.nodes[p]!.degree || p - q);
    labels = [...visibleAnchors, ...ranked.slice(0, Math.max(0, LABEL_BUDGET - visibleAnchors.length))];
  }
  return { nodes, edges, labels, edgesSkipped, sx, sy };
}

export function drawFrame(
  ctx: DrawContext,
  scene: Scene,
  cam: Camera,
  w: number,
  h: number,
  dpr: number,
  plan: FramePlan,
  hover: number,
): void {
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.globalAlpha = 1;
  ctx.fillStyle = GROUND_COLOR;
  ctx.fillRect(0, 0, w, h);

  // Links: one batched path for plain links, one for the focus/hover links.
  const highlighted = (k: number): boolean => {
    const e = scene.edges[k]!;
    return e.a === scene.focus || e.b === scene.focus || e.a === hover || e.b === hover;
  };
  for (const hi of [false, true]) {
    ctx.beginPath();
    let any = false;
    for (const k of plan.edges) {
      if (highlighted(k) !== hi) continue;
      const e = scene.edges[k]!;
      ctx.moveTo(plan.sx[e.a]!, plan.sy[e.a]!);
      ctx.lineTo(plan.sx[e.b]!, plan.sy[e.b]!);
      any = true;
    }
    if (!any) continue;
    ctx.strokeStyle = hi ? EDGE_HI_COLOR : EDGE_COLOR;
    ctx.lineWidth = hi ? 1.4 : 0.8;
    ctx.stroke();
  }

  // Nodes: one filled path per kind; ghosts as grey rings.
  const byKind = new Map<NoteKind, number[]>();
  const ghosts: number[] = [];
  for (const i of plan.nodes) {
    const n = scene.nodes[i]!;
    if (n.ghost) {
      ghosts.push(i);
      continue;
    }
    const list = byKind.get(n.kind);
    if (list) list.push(i);
    else byKind.set(n.kind, [i]);
  }
  for (const [kind, list] of byKind) {
    ctx.beginPath();
    for (const i of list) {
      const r = scene.nodes[i]!.r * cam.scale;
      const x = plan.sx[i]!;
      const y = plan.sy[i]!;
      if (r < DOT_MIN_PX) {
        ctx.rect(x - 1, y - 1, 2, 2);
      } else {
        ctx.moveTo(x + r, y);
        ctx.arc(x, y, r, 0, Math.PI * 2);
      }
    }
    ctx.fillStyle = KIND_COLORS[kind];
    ctx.fill();
  }
  if (ghosts.length > 0) {
    ctx.beginPath();
    for (const i of ghosts) {
      const r = Math.max(DOT_MIN_PX, scene.nodes[i]!.r * cam.scale);
      const x = plan.sx[i]!;
      const y = plan.sy[i]!;
      ctx.moveTo(x + r, y);
      ctx.arc(x, y, r, 0, Math.PI * 2);
    }
    ctx.strokeStyle = GHOST_COLOR;
    ctx.lineWidth = 1.5;
    ctx.stroke();
  }

  const ring = (i: number, color: string, width: number) => {
    const n = scene.nodes[i];
    if (!n) return;
    const r = Math.max(DOT_MIN_PX, n.r * cam.scale) + 4;
    const x = plan.sx[i]!;
    const y = plan.sy[i]!;
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arc(x, y, r, 0, Math.PI * 2);
    ctx.strokeStyle = color;
    ctx.lineWidth = width;
    ctx.stroke();
  };
  if (scene.focus >= 0) ring(scene.focus, FOCUS_COLOR, 2);
  if (hover >= 0 && hover !== scene.focus) ring(hover, LABEL_COLOR, 1.5);

  ctx.font = LABEL_FONT;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  ctx.fillStyle = LABEL_COLOR;
  for (const i of plan.labels) {
    const n = scene.nodes[i]!;
    ctx.fillText(truncateLabel(n.title), plan.sx[i]!, plan.sy[i]! + Math.max(DOT_MIN_PX, n.r * cam.scale) + 4);
  }
}

/** Index of the node under (px, py), nearest centre wins; -1 for a miss. A
 * linear scan is ~1 ms at 30k nodes, called at most once per pointer event. */
export function pickNode(
  scene: Scene,
  cam: Camera,
  w: number,
  h: number,
  px: number,
  py: number,
  hidden: ReadonlySet<NoteKind>,
): number {
  let best = -1;
  let bestD = Infinity;
  for (let i = 0; i < scene.nodes.length; i++) {
    if (isHidden(scene, i, hidden)) continue;
    const n = scene.nodes[i]!;
    const [x, y] = toScreen(cam, w, h, n.x, n.y);
    const r = Math.max(HIT_MIN_PX, n.r * cam.scale + 3);
    const d = (x - px) ** 2 + (y - py) ** 2;
    if (d <= r * r && d < bestD) {
      best = i;
      bestD = d;
    }
  }
  return best;
}
