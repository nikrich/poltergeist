import type { VaultGraph, VaultGraphNode } from '../../shared/api-types';

export type Camera = { x: number; y: number; scale: number };

export function toScreen(cam: Camera, w: number, h: number, wx: number, wy: number): [number, number] {
  return [(wx - cam.x) * cam.scale + w / 2, (wy - cam.y) * cam.scale + h / 2];
}

export function toWorld(cam: Camera, w: number, h: number, sx: number, sy: number): [number, number] {
  return [(sx - w / 2) / cam.scale + cam.x, (sy - h / 2) / cam.scale + cam.y];
}

export function fitCamera(nodes: VaultGraphNode[], w: number, h: number): Camera {
  if (nodes.length === 0) return { x: 0, y: 0, scale: 1 };
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
  for (const n of nodes) {
    minX = Math.min(minX, n.x); minY = Math.min(minY, n.y);
    maxX = Math.max(maxX, n.x); maxY = Math.max(maxY, n.y);
  }
  const pad = 70;
  const scale = Math.max(0.7, Math.min(1.5,
    Math.min(w / (maxX - minX + pad * 2), h / (maxY - minY + pad * 2)) * 1.04));
  return { x: (minX + maxX) / 2, y: (minY + maxY) / 2, scale };
}

export function hitTest(cam: Camera, w: number, h: number, nodes: VaultGraphNode[], sx: number, sy: number): number {
  let best = -1, bestD = Infinity;
  for (let i = 0; i < nodes.length; i++) {
    const n = nodes[i];
    if (!n) continue;
    const [x, y] = toScreen(cam, w, h, n.x, n.y);
    const d = (x - sx) ** 2 + (y - sy) ** 2;
    const r = Math.max(9, (2.7 + Math.min(n.degree, 14) * 0.62) * cam.scale + 7);
    if (d < r * r && d < bestD) { bestD = d; best = i; }
  }
  return best;
}

export function buildAdjacency(graph: VaultGraph): Map<string, string[]> {
  const adj = new Map<string, string[]>();
  const push = (a: string, b: string) => {
    const list = adj.get(a) ?? [];
    if (!list.includes(b)) list.push(b);
    adj.set(a, list);
  };
  for (const e of graph.edges) { push(e.source, e.target); push(e.target, e.source); }
  return adj;
}
