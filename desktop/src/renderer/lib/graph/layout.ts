import {
  forceCollide,
  forceLink,
  forceManyBody,
  forceRadial,
  forceSimulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from 'd3-force';

import type { EgoGraph, NoteKind, VaultGraph } from '../../../shared/api-types';
import { nodeRadius } from '../constellation-engine';

export interface SceneNode {
  path: string;
  title: string;
  kind: NoteKind;
  degree: number;
  ghost: boolean;
  hop: number;
  /** world coordinates */
  x: number;
  y: number;
  /** world radius */
  r: number;
}

export interface SceneEdge {
  a: number;
  b: number;
  weight: number;
}

export interface Scene {
  mode: 'ego' | 'vault';
  nodes: SceneNode[];
  edges: SceneEdge[];
  /** index of the focus node, -1 for none */
  focus: number;
}

/** Fixed tick count, run synchronously: about 50 ms for a capped 300-node
 * ego graph. No animation loop, and the result is deterministic. */
export const EGO_TICKS = 300;
export const RING_GAP = 150;
export const EGO_RADIUS_SCALE = 1.8;

interface SimNode extends SimulationNodeDatum {
  hop: number;
  r: number;
}

function indexByPath(paths: readonly string[]): Map<string, number> {
  const index = new Map<string, number>();
  paths.forEach((p, i) => index.set(p, i));
  return index;
}

function mapEdges(
  edges: ReadonlyArray<{ source: string; target: string; weight: number }>,
  index: Map<string, number>,
): SceneEdge[] {
  const out: SceneEdge[] = [];
  for (const e of edges) {
    const a = index.get(e.source);
    const b = index.get(e.target);
    if (a === undefined || b === undefined || a === b) continue;
    out.push({ a, b, weight: e.weight });
  }
  return out;
}

export function layoutEgo(graph: EgoGraph, ticks: number = EGO_TICKS): Scene {
  const index = indexByPath(graph.nodes.map((n) => n.path));
  const count = Math.max(graph.nodes.length, 1);
  // Seed each node on its hop ring so the start is deterministic and spread.
  const sim: SimNode[] = graph.nodes.map((n, i) => {
    const angle = (i / count) * Math.PI * 2;
    const node: SimNode = {
      hop: n.hop,
      r: nodeRadius(n.degree) * EGO_RADIUS_SCALE,
      x: Math.cos(angle) * n.hop * RING_GAP,
      y: Math.sin(angle) * n.hop * RING_GAP,
    };
    if (n.path === graph.focus) {
      node.fx = 0;
      node.fy = 0;
    }
    return node;
  });
  const edges = mapEdges(graph.edges, index);
  const links: SimulationLinkDatum<SimNode>[] = edges.map((e) => ({ source: e.a, target: e.b }));
  forceSimulation<SimNode>(sim)
    .force('link', forceLink<SimNode, SimulationLinkDatum<SimNode>>(links).distance(RING_GAP * 0.6).strength(0.2))
    .force('charge', forceManyBody<SimNode>().strength(-220).distanceMax(RING_GAP * 4))
    .force('collide', forceCollide<SimNode>((n) => n.r + 8))
    .force('radial', forceRadial<SimNode>((n) => n.hop * RING_GAP, 0, 0).strength(0.8))
    .stop()
    .tick(ticks);

  const nodes: SceneNode[] = graph.nodes.map((n, i) => {
    const s = sim[i]!;
    return {
      path: n.path,
      title: n.title,
      kind: n.kind,
      degree: n.degree,
      ghost: n.ghost,
      hop: n.hop,
      x: s.x ?? 0,
      y: s.y ?? 0,
      r: s.r,
    };
  });
  return { mode: 'ego', nodes, edges, focus: index.get(graph.focus) ?? -1 };
}

/** Whole-vault mode: the sidecar's embedding positions (the constellation's
 * layout), so a 30k-note vault never runs a force simulation. */
export function sceneFromVaultGraph(graph: VaultGraph, focus: string | null = null): Scene {
  const index = indexByPath(graph.nodes.map((n) => n.path));
  const nodes: SceneNode[] = graph.nodes.map((n) => ({
    path: n.path,
    title: n.title,
    kind: n.kind ?? 'note',
    degree: n.degree,
    ghost: false,
    hop: 0,
    x: n.x,
    y: n.y,
    r: nodeRadius(n.degree),
  }));
  return {
    mode: 'vault',
    nodes,
    edges: mapEdges(graph.edges, index),
    focus: focus === null ? -1 : (index.get(focus) ?? -1),
  };
}
