import { describe, expect, it } from 'vitest';
import type { GraphKind } from '../../shared/api-types';
import { fitCamera, nodeRadius, toScreen, type Camera } from '../lib/constellation-engine';
import {
  EDGE_BUDGET,
  LABEL_BUDGET,
  LABEL_MAX_CHARS,
  drawFrame,
  pickNode,
  planFrame,
  truncateLabel,
  type DrawContext,
} from '../lib/graph/draw';
import { GHOST_COLOR, KIND_COLORS, NOTE_KINDS } from '../lib/graph/kinds';
import type { Scene, SceneNode } from '../lib/graph/layout';

const W = 1200;
const H = 800;
const NONE = new Set<GraphKind>();

/** Synthetic whole-vault scene: seeded positions, ~3 links per node. */
function bigScene(count = 30_000, linksPerNode = 3): Scene {
  let seed = 7;
  const rand = () => (seed = (seed * 16807) % 2147483647) / 2147483647;
  const nodes: SceneNode[] = Array.from({ length: count }, (_, i) => ({
    path: `n${i}.md`, title: `note ${i}`, kind: NOTE_KINDS[i % NOTE_KINDS.length]!, degree: i % 20,
    ghost: false, hop: 0, x: (rand() - 0.5) * 4000, y: (rand() - 0.5) * 4000, r: nodeRadius(i % 20),
  }));
  const edges = [];
  for (let a = 0; a < count; a++) {
    for (let k = 0; k < linksPerNode; k++) {
      const b = Math.floor(rand() * count);
      if (b !== a) edges.push({ a, b, weight: 0.5 });
    }
  }
  return { mode: 'vault', nodes, edges, focus: -1 };
}

const FIT = { min: 0.05, max: 1.6 };

describe('planFrame', () => {
  const scene = bigScene();

  it('plans a 30k-node vault zoomed out: every dot, no links, no labels', () => {
    const cam = fitCamera(scene.nodes, W, H, FIT);
    const plan = planFrame(scene, cam, W, H, { hidden: NONE, hover: -1 });
    expect(plan.nodes).toHaveLength(30_000);
    expect(plan.edgesSkipped).toBe(true);
    expect(plan.edges).toEqual([]);
    expect(plan.labels).toEqual([]);
  });

  it("keeps the hovered node's links when the budget is blown", () => {
    const cam = fitCamera(scene.nodes, W, H, FIT);
    const plan = planFrame(scene, cam, W, H, { hidden: NONE, hover: 5 });
    expect(plan.edgesSkipped).toBe(true);
    expect(plan.edges.length).toBeGreaterThan(0);
    expect(plan.edges.every((k) => scene.edges[k]!.a === 5 || scene.edges[k]!.b === 5)).toBe(true);
    expect(plan.labels).toEqual([5]);
  });

  it('zoomed in: culls to the viewport, respects the link and label budgets', () => {
    const cam: Camera = { x: 0, y: 0, scale: 2 };
    const plan = planFrame(scene, cam, W, H, { hidden: NONE, hover: -1 });
    expect(plan.nodes.length).toBeGreaterThan(0);
    expect(plan.nodes.length).toBeLessThan(2_000);
    for (const i of plan.nodes) {
      expect(plan.sx[i]!).toBeGreaterThan(-100);
      expect(plan.sx[i]!).toBeLessThan(W + 100);
    }
    expect(plan.edges.length).toBeLessThanOrEqual(EDGE_BUDGET);
    expect(plan.labels.length).toBeLessThanOrEqual(LABEL_BUDGET);
    const degrees = plan.labels.map((i) => scene.nodes[i]!.degree);
    expect(degrees).toEqual([...degrees].sort((p, q) => q - p));
  });

  it('hides filtered kinds and their links, but never the focus', () => {
    const focused: Scene = { ...scene, focus: 0 }; // node 0 is a person
    const hidden = new Set<GraphKind>(['person', 'note']);
    const plan = planFrame(focused, { x: 0, y: 0, scale: 2 }, W, H, { hidden, hover: -1 });
    const shown = plan.nodes.filter((i) => i !== 0);
    expect(shown.every((i) => !hidden.has(focused.nodes[i]!.kind))).toBe(true);
    for (const k of plan.edges) {
      const e = focused.edges[k]!;
      for (const end of [e.a, e.b]) {
        if (end !== 0) expect(hidden.has(focused.nodes[end]!.kind)).toBe(false);
      }
    }
    const camOnFocus: Camera = { x: focused.nodes[0]!.x, y: focused.nodes[0]!.y, scale: 2 };
    expect(planFrame(focused, camOnFocus, W, H, { hidden, hover: -1 }).nodes).toContain(0);
  });
});

describe('pickNode', () => {
  it('picks the right node in a 30k-node scene', () => {
    const scene = bigScene();
    const target = scene.nodes[12_345]!;
    const cam: Camera = { x: target.x, y: target.y, scale: 2 };
    expect(pickNode(scene, cam, W, H, W / 2, H / 2, NONE)).toBe(12_345);
  });

  it('misses empty space and hidden kinds', () => {
    const scene: Scene = {
      mode: 'ego', focus: -1, edges: [],
      nodes: [{ path: 'p.md', title: 'P', kind: 'person', degree: 1, ghost: false, hop: 1, x: 0, y: 0, r: 5 }],
    };
    const cam: Camera = { x: 0, y: 0, scale: 1 };
    const [x, y] = toScreen(cam, W, H, 0, 0);
    expect(pickNode(scene, cam, W, H, x, y, NONE)).toBe(0);
    expect(pickNode(scene, cam, W, H, x + 200, y, NONE)).toBe(-1);
    expect(pickNode(scene, cam, W, H, x, y, new Set<GraphKind>(['person']))).toBe(-1);
  });
});

interface Op {
  op: string;
  args: unknown[];
  fillStyle: unknown;
  strokeStyle: unknown;
}

function recordingContext(): { ctx: DrawContext; ops: Op[] } {
  const ops: Op[] = [];
  const ctx = {
    fillStyle: '', strokeStyle: '', lineWidth: 1, font: '',
    textAlign: 'start' as CanvasTextAlign, textBaseline: 'alphabetic' as CanvasTextBaseline, globalAlpha: 1,
  } as DrawContext;
  const methods = ['setTransform', 'fillRect', 'beginPath', 'moveTo', 'lineTo', 'arc', 'rect', 'fill', 'stroke', 'fillText'];
  for (const name of methods) {
    (ctx as unknown as Record<string, unknown>)[name] = (...args: unknown[]) => {
      ops.push({ op: name, args, fillStyle: ctx.fillStyle, strokeStyle: ctx.strokeStyle });
    };
  }
  return { ctx, ops };
}

describe('drawFrame', () => {
  const longTitle = 'A very long page title that keeps going well past the label limit';
  const scene: Scene = {
    mode: 'ego', focus: 0,
    nodes: [
      { path: 'a.md', title: longTitle, kind: 'decision', degree: 2, ghost: false, hop: 0, x: 0, y: 0, r: 8 },
      { path: 'later.md', title: 'Later', kind: 'note', degree: 1, ghost: true, hop: 1, x: 120, y: 0, r: 6 },
    ],
    edges: [{ a: 0, b: 1, weight: 0.5 }],
  };

  it('fills real nodes in their kind colour, rings ghosts in grey, and labels them', () => {
    const { ctx, ops } = recordingContext();
    const cam: Camera = { x: 60, y: 0, scale: 1 };
    const plan = planFrame(scene, cam, W, H, { hidden: NONE, hover: -1 });
    drawFrame(ctx, scene, cam, W, H, 2, plan, -1);
    expect(ops[0]).toMatchObject({ op: 'setTransform', args: [2, 0, 0, 2, 0, 0] });
    expect(ops.some((o) => o.op === 'fill' && o.fillStyle === KIND_COLORS.decision)).toBe(true);
    expect(ops.some((o) => o.op === 'stroke' && o.strokeStyle === GHOST_COLOR)).toBe(true);
    expect(ops.some((o) => o.op === 'fill' && o.fillStyle === KIND_COLORS.note)).toBe(false);
    const texts = ops.filter((o) => o.op === 'fillText').map((o) => o.args[0]);
    expect(texts).toEqual([truncateLabel(longTitle), 'Later']);
  });
});

describe('truncateLabel', () => {
  it('caps long titles with an ellipsis', () => {
    expect(truncateLabel('short')).toBe('short');
    const t = truncateLabel('x'.repeat(80));
    expect(t).toHaveLength(LABEL_MAX_CHARS);
    expect(t.endsWith('…')).toBe(true);
  });
});
